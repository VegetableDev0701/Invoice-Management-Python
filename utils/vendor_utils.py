import asyncio
import traceback
from typing import Awaitable, Dict, List, Set
import copy
import re

from google.cloud import firestore

from config import PROJECT_NAME
from data_processing_pipeline.matching_algorithm_utils import (
    init_sentence_similarity_model,
    match_predicted_vendor,
)
from global_vars.globals_io import BATCH_SIZE_CUTOFF, QBD_VENDOR_EXT_NAMES_LOOKUP_KEY
from utils.database.firestore import (
    fetch_all_vendor_summaries,
    get_from_firestore,
    push_to_firestore,
    push_to_firestore_batch,
    stream_entire_collection,
)

from utils.data_models.vendors import (
    FullBulkVendorDataToAdd,
    ReferenceDict,
)
from utils.io_utils import create_short_uuid


async def add_vendors_wrapper(
    company_id: str,
    new_vendors_to_add: dict,
    unique_data_ext_names: set[str] | list[str],
):
    company_lookup_dict = await get_company_lookup_dict(
        company_id=company_id, unique_data_ext_names=unique_data_ext_names
    )

    # Create the full data and summary data in the backend here
    vendor_data_to_add_to_firestore = await create_vendor_data(
        vendors_dict=new_vendors_to_add,
        lookup_dict=company_lookup_dict,
        company_id=company_id,
    )

    add_vendors_bulk_func = (
        add_vendors_bulk_batch
        if len(vendor_data_to_add_to_firestore["fullData"]) > BATCH_SIZE_CUTOFF
        else add_vendors_bulk
    )

    # Run these two coroutines concurrently. They are both longer running.
    add_vendors_bulk_task = add_vendors_bulk_func(
        company_id=company_id, data=vendor_data_to_add_to_firestore
    )
    match_vendors_to_docs_task = traverse_all_docs_and_match_empty_vendors(
        company_id=company_id,
        vendor_summary_list=list(
            vendor_data_to_add_to_firestore["summaryData"].values()
        ),
    )

    _, update_doc_dict = await asyncio.gather(
        add_vendors_bulk_task, match_vendors_to_docs_task
    )

    return (
        vendor_data_to_add_to_firestore,
        update_doc_dict,
    )


async def fetch_agave_uuid(doc_ref):
    """Fetch agave_uuid from a vendor-summary document."""
    doc = await doc_ref.get()
    doc_dict = doc.to_dict()
    if doc_dict is None:
        return None
    else:
        return doc_dict.get("agave_uuid", None)


async def get_agave_uuids(db, company_id):
    # Reference to the parent document
    parent_doc_ref = db.collection(company_id).document("vendors")

    # Prepare tasks for fetching each agave_uuid
    tasks = []
    async for coll in parent_doc_ref.collections():
        doc_ref = coll.document("vendor-summary")
        tasks.append(fetch_agave_uuid(doc_ref))

    # Run all fetch operations concurrently
    result_agave_uuids = await asyncio.gather(*tasks)
    return result_agave_uuids


async def add_vendor_full_and_summary(
    company_id: str, vendor_id: str, initial: int, jitter: int, full_data, summary_data
) -> None:
    await push_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data=full_data[vendor_id],
        document="vendors",
        doc_collection=vendor_id,
        doc_collection_document="vendor-details",
        initial=initial,
        jitter=jitter,
    )
    await push_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data=summary_data[vendor_id],
        document="vendors",
        doc_collection=vendor_id,
        doc_collection_document="vendor-summary",
        initial=initial,
        jitter=jitter,
    )


async def add_vendor_full_and_summary_batch(
    vendor_id: str, full_data: List[Dict], summary_data: List[Dict]
) -> List[Dict]:
    full_data_dict = {
        "document": "vendors",
        "doc_collection": vendor_id,
        "doc_collection_document": "vendor-details",
        "data": full_data[vendor_id],
    }
    summary_data_dict = {
        "document": "vendors",
        "doc_collection": vendor_id,
        "doc_collection_document": "vendor-summary",
        "data": summary_data[vendor_id],
    }
    return [full_data_dict, summary_data_dict]


async def add_vendors_bulk(
    company_id: str,
    data: FullBulkVendorDataToAdd,
    initial: int = 10,
    jitter: int = 5,
) -> None:
    full_data = data["fullData"]
    summary_data = data["summaryData"]

    tasks = []
    if full_data:
        # the summary data and full data should have the same set of keys
        for vendor_id in full_data.keys():
            tasks.append(
                asyncio.create_task(
                    add_vendor_full_and_summary(
                        company_id=company_id,
                        vendor_id=vendor_id,
                        full_data=full_data,
                        summary_data=summary_data,
                        initial=initial,
                        jitter=jitter,
                    )
                )
            )
        _ = await asyncio.gather(*tasks)

    # Need to make sure that all vendors were successfully added to firestore
    try:
        db = firestore.AsyncClient(project=PROJECT_NAME)
        result_agave_uuids = await get_agave_uuids(db, company_id)
        return result_agave_uuids
    finally:
        db.close()


async def add_vendors_bulk_batch(
    company_id: str,
    data: FullBulkVendorDataToAdd,
    initial: int = 10,
    jitter: int = 5,
) -> None:
    full_data = data["fullData"]
    summary_data = data["summaryData"]

    batch_data = []
    if full_data:
        for vendor_id in full_data.keys():
            vendor_batch_data = await add_vendor_full_and_summary_batch(
                vendor_id=vendor_id,
                full_data=full_data,
                summary_data=summary_data,
            )
            batch_data.extend(vendor_batch_data)

        await push_to_firestore_batch(
            project_name=PROJECT_NAME,
            collection=company_id,
            documents=batch_data,
            initial=initial,
            jitter=jitter,
        )


async def create_vendor_data(
    vendors_dict: Dict[str, List[dict] | dict],
    lookup_dict: Dict[str, Dict[str, set | None]],
    company_id: str,
) -> FullBulkVendorDataToAdd:
    all_vendor_form_data = {}
    all_vendor_summary_data = {}

    add_vendor_form_dict = await get_from_firestore(
        project_name=PROJECT_NAME,
        collection_name=company_id,
        document_name="base-forms",
        doc_collection="forms",
        doc_collection_document="add-vendor",
    )

    for vendor in vendors_dict["data"]:
        uuid = create_short_uuid()
        form_state = create_vendor_form_state(vendor, lookup_dict)
        form_data = create_vendor_form_data(add_vendor_form_dict, form_state)
        form_data["uuid"] = uuid
        summary_data = create_single_vendor_summary(form_data, uuid, vendor["id"])
        all_vendor_form_data[uuid] = form_data
        all_vendor_summary_data[uuid] = summary_data

    return {"fullData": all_vendor_form_data, "summaryData": all_vendor_summary_data}


def create_vendor_form_state(
    vendor: Dict[str, str | dict],
    lookup_dict: Dict[str, Set[str] | List[str]],
) -> Dict[str, str]:
    vendor_form_state = {}
    # standard fields
    if vendor.get("address", None):
        vendor_form_state["vendor-address"] = {"value": vendor["address"]["street_1"]}
        vendor_form_state["city-vendor"] = {"value": vendor["address"]["city"]}
        vendor_form_state["state-vendor"] = {"value": vendor["address"]["state"]}
        vendor_form_state["zip-code-vendor"] = {
            "value": vendor["address"]["postal_code"]
        }
    vendor_form_state["vendor-name"] = {"value": vendor["name"]}
    vendor_form_state["email"] = {"value": vendor["email"]}
    vendor_form_state["work-phone"] = {"value": vendor["phone"]}
    vendor_form_state["tax-number"] = {"value": vendor["tax_number"]}
    vendor_form_state["vendor-type"] = {"value": vendor["type"]}
    vendor_form_state["is-active"] = {
        "value": vendor["source_data"]["data"]["IsActive"]
    }

    # extract the custom fields if they exist
    source_data_custom_fields = vendor["source_data"]["data"].get("DataExtRet", None)
    # and if so, extract them into the form state dict
    if source_data_custom_fields:
        for custom_name, (_, form_state_key) in lookup_dict.items():
            if form_state_key is None:
                continue
            vendor_form_state[form_state_key] = {
                "value": next(
                    (
                        x["DataExtValue"]
                        for x in source_data_custom_fields
                        if x["DataExtName"] == custom_name
                    ),
                    None,
                )
            }
    return vendor_form_state


def create_vendor_form_data(form_data, form_state_data):
    """
    Python version of the function that takes form state data and transforms it
    into form data.
    """
    # Assuming form_data is a dictionary and form_state_data is a dictionary
    new_form_data = copy.deepcopy(form_data)

    if "mainCategories" in new_form_data:
        for i, category in enumerate(new_form_data["mainCategories"]):
            for j, el in enumerate(category.get("inputElements", [])):
                if (
                    "addressElements" in el
                ):  # Assuming this checks for InputElementWithAddressElements
                    for j_add, add_el in enumerate(el["addressElements"]):
                        for k_add, add_item in enumerate(add_el["items"]):
                            for key, value in form_state_data.items():
                                if key == add_item["id"]:
                                    new_form_data["mainCategories"][i]["inputElements"][
                                        j
                                    ]["addressElements"][j_add]["items"][k_add][
                                        "value"
                                    ] = value[
                                        "value"
                                    ]

                elif "items" in el:  # Assuming this checks for InputElementWithItems
                    for k, item in enumerate(el["items"]):
                        for key, value in form_state_data.items():
                            if key == item["id"]:
                                if item.get("isCurrency"):
                                    new_form_data["mainCategories"][i]["inputElements"][
                                        j
                                    ]["items"][k]["value"] = (
                                        re.sub(r"[^0-9.]", "", value["value"])
                                        if value["value"]
                                        else None
                                    )
                                elif item.get("isPhoneNumber"):
                                    new_form_data["mainCategories"][i]["inputElements"][
                                        j
                                    ]["items"][k]["value"] = (
                                        re.sub(r"\D", "", value["value"])
                                        if value["value"]
                                        else None
                                    )
                                else:
                                    new_form_data["mainCategories"][i]["inputElements"][
                                        j
                                    ]["items"][k]["value"] = value["value"]

    return new_form_data


def get_target_value(target_id, input_elements):
    for element in input_elements:
        if "items" in element:  # Assuming this checks for InputElementWithItems
            found_item = next(
                (item for item in element["items"] if item["id"] == target_id), None
            )
            if found_item:
                return found_item["value"]

        if (
            "addressElements" in element
        ):  # Assuming this checks for InputElementWithAddressElements
            for address_element in element["addressElements"]:
                found_item = next(
                    (
                        item
                        for item in address_element["items"]
                        if item["id"] == target_id
                    ),
                    None,
                )
                if found_item:
                    return found_item["value"]

    return None


def create_single_vendor_summary(vendor, uuid, agave_uuid):
    vendor_details = vendor["mainCategories"][0]
    license_ins_details = vendor["mainCategories"][1]

    vendor_table_row = {
        "vendorName": get_target_value("vendor-name", vendor_details["inputElements"]),
        "primaryContact": get_target_value(
            "primary-contact", vendor_details["inputElements"]
        ),
        "workPhone": get_target_value("work-phone", vendor_details["inputElements"]),
        "cellPhone": get_target_value("cell-phone", vendor_details["inputElements"]),
        "email": get_target_value("email", vendor_details["inputElements"]),
        "address": get_target_value("vendor-address", vendor_details["inputElements"]),
        "city": get_target_value("city-vendor", vendor_details["inputElements"]),
        "state": get_target_value("state-vendor", vendor_details["inputElements"]),
        "zipCode": get_target_value("zip-code-vendor", vendor_details["inputElements"]),
        "vendorType": get_target_value("vendor-type", vendor_details["inputElements"]),
        "businessLicNumber": get_target_value(
            "business-license-number", license_ins_details["inputElements"]
        ),
        "businessLicExpirationDate": get_target_value(
            "license-expiration-date", license_ins_details["inputElements"]
        ),
        "insuranceName": get_target_value(
            "insurance-name", license_ins_details["inputElements"]
        ),
        "insuranceExpirationDate": get_target_value(
            "insurance-expiration-date", license_ins_details["inputElements"]
        ),
        "insuranceCoverageAmt": get_target_value(
            "insurance-coverage-amount", license_ins_details["inputElements"]
        ),
        "landiLicNumber": get_target_value(
            "landi-number", license_ins_details["inputElements"]
        ),
        "landiExpirationDate": get_target_value(
            "landi-expiration-date", license_ins_details["inputElements"]
        ),
        "workersCompExpirationDate": get_target_value(
            "workers-compensation-expiration", license_ins_details["inputElements"]
        ),
        "bondCompanyName": get_target_value(
            "bond-company-name", license_ins_details["inputElements"]
        ),
        "bondAmt": get_target_value(
            "bond-amount", license_ins_details["inputElements"]
        ),
        "w9OnFile": get_target_value(
            "w9-on-file", license_ins_details["inputElements"]
        ),
        "taxNumber": get_target_value(
            "tax-number", license_ins_details["inputElements"]
        ),
        "uuid": uuid,
        "agave_uuid": agave_uuid or None,
    }

    return vendor_table_row


async def get_company_lookup_dict(
    company_id: str,
    unique_data_ext_names: set | list,
) -> Dict[str, list | set]:
    org_docs = await stream_entire_collection(
        project_name=PROJECT_NAME, collection_name="organizations"
    )

    lookup_dict = update_custom_fields_lookup(
        company_id=company_id,
        org_docs=org_docs,
        unique_data_ext_names=unique_data_ext_names,
    )

    # will update the organization document if it exists and create one if not
    _ = await push_to_firestore(
        project_name=PROJECT_NAME,
        collection="organizations",
        document=company_id,
        data={QBD_VENDOR_EXT_NAMES_LOOKUP_KEY: lookup_dict},
    )

    return lookup_dict


def update_custom_fields_lookup(
    company_id: str,
    org_docs: Dict[str, Dict[str, str | dict]],
    unique_data_ext_names: set | list,
):
    """
    Update the custom field lookup dict for new companies or companies that don't have
    a lookup dict in their company data.
    """
    if (
        company_id in org_docs
        and org_docs[company_id].get(QBD_VENDOR_EXT_NAMES_LOOKUP_KEY) is None
    ):
        # Initialize the new entry with default values
        new_entry = {key: (None, None) for key in unique_data_ext_names}

        # Iterate through existing entries to find matches
        for fields in org_docs.values():
            for key in unique_data_ext_names:
                if (
                    fields.get(QBD_VENDOR_EXT_NAMES_LOOKUP_KEY) is not None
                    and key in fields[QBD_VENDOR_EXT_NAMES_LOOKUP_KEY]
                ):
                    # Update the new entry with the value from the existing match
                    new_entry[key] = fields[QBD_VENDOR_EXT_NAMES_LOOKUP_KEY][key]

        # Update the dictionary with the new entry
        org_docs[company_id].update({QBD_VENDOR_EXT_NAMES_LOOKUP_KEY: new_entry})

    elif company_id not in org_docs:
        # Initialize the new entry with default values
        new_entry = {key: (None, None) for key in unique_data_ext_names}

        # Iterate through existing entries to find matches
        for fields in org_docs.values():
            for key in unique_data_ext_names:
                if (
                    fields.get(QBD_VENDOR_EXT_NAMES_LOOKUP_KEY) is not None
                    and key in fields[QBD_VENDOR_EXT_NAMES_LOOKUP_KEY]
                ):
                    # Update the new entry with the value from the existing match
                    new_entry[key] = fields[QBD_VENDOR_EXT_NAMES_LOOKUP_KEY][key]

        # Update the dictionary with the new entry
        org_docs[company_id] = {QBD_VENDOR_EXT_NAMES_LOOKUP_KEY: new_entry}

    return org_docs[company_id][QBD_VENDOR_EXT_NAMES_LOOKUP_KEY]


async def update_document(ref, key_name, result):
    for key in key_name:
        if key is not None:
            if "vendor" in key:
                result = {"name": result["supplier_name"], "uuid": result.get("uuid")}
            update_data = {key: result}
            await ref.update(update_data)


async def traverse_all_docs_and_match_empty_vendors(
    company_id: str,
    vendor_summary_list: list[dict],
) -> None:
    all_vendor_uuid_list = [
        vendor["uuid"]
        for vendor in await fetch_all_vendor_summaries(
            company_id=company_id, project_name=PROJECT_NAME
        )
    ]
    vendor_name_list = [
        {
            "name": vendor.get("vendorName"),
            "agave_uuid": vendor.get("agave_uuid"),
            "uuid": vendor.get("uuid"),
        }
        for vendor in vendor_summary_list
        if vendor
    ]
    model, vendors_emb = init_sentence_similarity_model(
        [x["name"] for x in vendor_name_list]
    )

    db = firestore.AsyncClient(project=PROJECT_NAME)
    try:
        project_ref = db.collection(company_id).document("projects")
        doc_ref = (
            db.collection(company_id)
            .document("documents")
            .collection("processed_documents")
        )

        match_tasks = []
        refs_dict = {}

        async for project in project_ref.collections():
            # Invoices in a client bill
            client_bill_ref = project_ref.collection(project.id).document(
                "client-bills"
            )
            contracts_ref = project_ref.collection(project.id).document("contracts")
            async for client_bill in client_bill_ref.collections():
                invoices_ref = client_bill_ref.collection(client_bill.id).document(
                    "invoices"
                )
                doc = await invoices_ref.get()
                if doc.exists:
                    doc_dict = doc.to_dict()
                    for uuid, doc_data in doc_dict.items():
                        predicted_supplier_name = doc_data.get(
                            "predicted_supplier_name", {}
                        )
                        agave_uuid = predicted_supplier_name.get("agave_uuid")
                        if (
                            agave_uuid is None
                            or predicted_supplier_name.get("uuid")
                            not in all_vendor_uuid_list
                        ):
                            match_task = match_predicted_vendor(
                                company_id=company_id,
                                pred_vendor_name_dict=predicted_supplier_name,
                                all_vendor_summary_list=vendor_summary_list,
                                model=model,
                                vendors_emb=vendors_emb,
                            )
                            match_tasks.append(match_task)
                            refs_dict[match_task] = {
                                "ref": invoices_ref,
                                "key": [
                                    f"{uuid}.predicted_supplier_name",
                                    f"{uuid}.processedData.vendor"
                                    if doc_data.get("processedData")
                                    else None,
                                ],
                                "doc_type": "client_bill_invoice",
                                "doc_uuid": uuid,
                                "project_id": project.id,
                            }

            # Contracts
            doc = await contracts_ref.get()
            if doc.exists:
                doc_dict = doc.to_dict()
                for uuid, doc_data in doc_dict.items():
                    summary_data = doc_data.get("summaryData", {})
                    vendor_dict = summary_data.get("vendor", {})
                    agave_uuid = vendor_dict.get("agave_uuid")
                    if (
                        agave_uuid is None
                        or vendor_dict.get("uuid") not in all_vendor_uuid_list
                    ):
                        match_task = match_predicted_vendor(
                            company_id=company_id,
                            pred_vendor_name_dict=summary_data,
                            all_vendor_summary_list=vendor_summary_list,
                            model=model,
                            vendors_emb=vendors_emb,
                        )
                        match_tasks.append(match_task)
                        refs_dict[match_task] = {
                            "ref": contracts_ref,
                            "key": [f"{uuid}.summaryData"],
                            "doc_type": "contract",
                            "doc_uuid": uuid,
                            "project_id": project.id,
                        }

        # Invoices not attached to client bill
        async for document in doc_ref.list_documents():
            doc = await document.get()
            if doc.exists:
                doc_dict = doc.to_dict()
                predicted_supplier_name = doc_dict.get("predicted_supplier_name", {})
                agave_uuid = predicted_supplier_name.get("agave_uuid")
                if (
                    agave_uuid is None
                    or predicted_supplier_name.get("uuid") not in all_vendor_uuid_list
                ):
                    match_task = match_predicted_vendor(
                        company_id=company_id,
                        pred_vendor_name_dict=predicted_supplier_name,
                        all_vendor_summary_list=vendor_summary_list,
                        model=model,
                        vendors_emb=vendors_emb,
                    )
                    match_tasks.append(match_task)
                    refs_dict[match_task] = {
                        "ref": document,
                        "key": [
                            "predicted_supplier_name",
                            "processedData.vendor"
                            if doc_dict.get("processedData")
                            else None,
                        ],
                        "doc_type": "invoice",
                        "doc_uuid": doc_dict["doc_id"],
                        "project_id": None,
                    }

        results = await asyncio.gather(*match_tasks)

        update_tasks = [
            update_document(refs_dict[task]["ref"], refs_dict[task]["key"], result)
            for task, result in zip(match_tasks, results)
        ]

        _ = await asyncio.gather(*update_tasks)

        # create a dictionary of document updates to send to the front end to update the state
        # don't need to update the client bill because that data always gets pulled form backend
        update_doc_dict = create_update_doc_dict(
            match_tasks=match_tasks, results=results, refs_dict=refs_dict
        )

        return update_doc_dict

    except Exception as e:
        print(e)
        traceback.print_exc()

    finally:
        db.close()


def create_update_doc_dict(
    match_tasks: List[Awaitable[List[Dict[str, str | dict]]]],
    results: List[Dict[str, str | dict]],
    refs_dict: ReferenceDict,
):
    update_doc_dict = {"contract": {}, "invoice": {}}
    for task, result in zip(match_tasks, results):
        if refs_dict[task]["doc_type"] != "client_bill_invoice":
            uuid = refs_dict[task]["doc_uuid"]
            if refs_dict[task]["doc_type"] == "invoice":
                update_data = {
                    "project_id": refs_dict[task]["project_id"],
                    "predicted_supplier_name": result,
                    "vendor": {
                        "name": result["supplier_name"],
                        "uuid": result.get("uuid"),
                    },
                }
            elif refs_dict[task]["doc_type"] == "contract":
                update_data = {
                    "project_id": refs_dict[task]["project_id"],
                    "summaryData": result,
                }
            update_doc_dict[refs_dict[task]["doc_type"]].update({uuid: update_data})
    return update_doc_dict
