from typing import List
import json
import logging
import sys

from google.cloud import firestore
from tenacity import (
    retry_if_exception_type,
    wait_exponential_jitter,
    stop_after_attempt,
    AsyncRetrying,
    RetryError,
    before_sleep_log,
)
from utils.retry_utils import RETRYABLE_EXCEPTIONS

from global_vars.globals_invoice import PROJECT_DETAILS_MATCHING_KEYS
from global_vars.globals_io import RETRY_TIMES

# Create a logger
firestore_io_logger = logging.getLogger("error_logger")
firestore_io_logger.setLevel(logging.DEBUG)

# Create a file handler
# handler = logging.FileHandler(
#     "/Users/mgrant/STAK/app/stak-backend/api/logs/firestore_read_write_error_logs.log"
# )
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)

# Create a logging format
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)

# Add the handlers to the logger
firestore_io_logger.addHandler(handler)


async def get_from_firestore(
    project_name: str,
    collection_name: str,
    document_name: str,
    doc_collection: str | None = None,
    doc_collection_document: str | None = None,
):
    db = firestore.AsyncClient(project=project_name)
    try:
        document_ref = db.collection(collection_name).document(document_name)
        if doc_collection and doc_collection_document:
            document_ref = document_ref.collection(doc_collection).document(
                doc_collection_document
            )
            doc = await document_ref.get()
            db.close()
            return doc.to_dict()
        else:
            doc = await document_ref.get()
            db.close()
            return doc.to_dict()
    except Exception as e:
        firestore_io_logger.exception(
            f"An error occurred streaming all project data: {e}"
        )
    finally:
        db.close()


async def get_all_project_details_data(
    project_name: str,
    collection_name: str,
    document_name: str,
    details_doc_name: str,
):
    """
    Used to collect all the details data. Used to grab all project details, vendor
    details, contracts etc. This will pull all the details for any group needed.
    """
    db = firestore.AsyncClient(project=project_name)
    try:
        collections = (
            db.collection(collection_name).document(document_name).collections()
        )
        docs = {}

        async for collection in collections:
            doc = await collection.document(details_doc_name).get()
            docs[collection.id] = doc.to_dict()
        db.close()
        return docs
    except Exception as e:
        firestore_io_logger.exception(
            f"An error occurred getting all project details: {e}"
        )
    finally:
        db.close()


async def stream_all_project_data(
    project_name: str,
    collection_name: str,
    document_name: str,
    project_id: str,
):
    db = firestore.AsyncClient(project=project_name)
    try:
        project_collection_ref = (
            db.collection(collection_name)
            .document(document_name)
            .collection(project_id)
        )

        project_data = {}
        async for doc in project_collection_ref.list_documents():
            if doc.id == "client-bills":
                continue
            else:
                doc = await doc.get()
                project_data[doc.id] = doc.to_dict()

        if "b2a" in project_data.keys():
            # Hacky workaround becuase Firestore will not accept numbers as keys
            # and here I want them as numbers and sorted.
            new_dict_outer = {}
            for key, value in project_data["b2a"]["b2aChartData"].items():
                try:
                    new_dict_outer[int(key)] = value
                except ValueError:
                    pass
            project_data["b2a"]["b2aChartData"] = dict(sorted(new_dict_outer.items()))

            for key, value in project_data["b2a"]["b2aChartData"].items():
                new_dict_inner = {}
                for innerKey, innerValue in value["subDivisions"].items():
                    new_dict_inner[float(innerKey)] = innerValue
                project_data["b2a"]["b2aChartData"][key]["subDivisions"] = dict(
                    sorted(new_dict_inner.items())
                )
        db.close()
        return project_data
    except Exception as e:
        firestore_io_logger.exception(
            f"An error occurred streaming all project data: {e}"
        )
    finally:
        db.close()


async def stream_entire_collection(
    project_name: str,
    collection_name: str,
    document_name: str,
    doc_collection_name: str,
    sub_collection_document: str | None = None,
    sub_collection: str | None = None,
) -> dict:
    """
    Get all the base form JSON data used to build the empty forms for
    adding projects, vendors, contracts, budgets etc.
    """
    docs = {}
    db = firestore.AsyncClient(project=project_name)
    try:
        collection_ref = (
            db.collection(collection_name)
            .document(document_name)
            .collection(doc_collection_name)
        )

        if sub_collection and sub_collection_document:
            collection_ref = collection_ref.document(
                sub_collection_document
            ).collection(sub_collection)

        async for doc in collection_ref.stream():
            doc_dict = doc.to_dict()
            if doc_collection_name == "processed_documents":
                del doc_dict["full_document_text"]
                del doc_dict["entities"]
            docs[doc.id] = doc_dict
        db.close()
        return docs
    except Exception as e:
        firestore_io_logger.exception(
            f"An error occurred streaming entire {document_name}/{doc_collection_name} collection project data: {e}"
        )
    finally:
        db.close()


async def get_all_company_data(project_name: str, collection_name: str):
    """
    Traverse the firestore db for all company data including:
        * Base forms
        * Projects
        * Vendors
        ...Coming soon: contracts, labor, invoices etc.

    Args:
        project_name: str
        collection_name: str
            The collection for that company's data
    """
    db = firestore.AsyncClient(project=project_name)
    try:
        company_ref = db.collection(collection_name)

        base_forms = {"base_forms": {}}
        project_forms = {"projects": {}}
        vendor_forms = {"vendors": {}}
        async for doc in company_ref.list_documents():
            if doc.id == "base-forms":
                async for coll in doc.collections():
                    async for docc in coll.stream():
                        base_forms["base_forms"][docc.id] = docc.to_dict()
            elif doc.id == "projects":
                async for coll in doc.collections():
                    # project_uuid = coll.id.split("::")
                    # project = project_uuid[0]
                    # uuid = project_uuid[1]
                    async for docc in coll.stream():
                        if docc.id == "project-details":
                            project_forms["projects"][coll.id] = docc.to_dict()
            elif doc.id == "vendors":
                async for coll in doc.collections():
                    # vendor_uuid = coll.id.split("::")
                    # vendor = vendor_uuid[0]
                    # uuid = vendor_uuid[1]
                    async for docc in coll.stream():
                        if docc.id == "vendor-details":
                            vendor_forms["vendors"][coll.id] = docc.to_dict()
            else:
                pass
        db.close()
        return json.dumps({**base_forms, **project_forms, **vendor_forms})
    except Exception as e:
        firestore_io_logger.exception(
            f"An error occurred getting all company data: {e}"
        )
    finally:
        db.close()


async def push_to_firestore(
    project_name: str,
    collection: str,
    data: dict | None = None,
    path_to_json: str | None = None,
    document: str | None = None,
    doc_collection: str | None = None,
    doc_collection_document: str | None = None,
):
    db = firestore.AsyncClient(project=project_name)
    try:
        document_ref = db.collection(collection).document(document)

        if doc_collection and doc_collection_document:
            document_ref = document_ref.collection(doc_collection).document(
                doc_collection_document
            )

        if path_to_json:
            with open(path_to_json, "r") as file:
                json_data = json.load(file)

        doc = await document_ref.get()
        if doc.exists:
            await document_ref.update(data)
        else:
            await document_ref.set(data)
    except Exception as e:
        firestore_io_logger.exception(
            f"An error occurred pushing data to firestore: {e}"
        )
    finally:
        db.close()


# TODO this function is has all fucked up naming convention and needs to be refactored if not rewritten
async def delete_collections_from_firestore(
    project_name: str,
    company_id: str,
    data: List[str],
    document_name: str,
    collection_name: str | None = None,
    doc_collection_name: str | None = None,
    doc_collection_doc_name: str | None = None,
) -> None:
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                # If deleting one specific collection, used for invoices
                if collection_name:
                    collection_ref = (
                        db.collection(company_id)
                        .document(document_name)
                        .collection(collection_name)
                    )
                    async for doc in collection_ref.stream():
                        if doc.id in data:
                            await doc.reference.delete()

                # When deleting multiple collections, used for deleting an entire project, client bill, vendor
                else:
                    collection_ref = db.collection(company_id).document(document_name)
                    # for a nested collection
                    if (
                        doc_collection_name is not None
                        and doc_collection_doc_name is not None
                    ):
                        collection_ref = collection_ref.collection(
                            doc_collection_name
                        ).document(doc_collection_doc_name)
                    async for coll in collection_ref.collections():
                        if coll.id in data:
                            async for doc in coll.stream():
                                await doc.reference.delete()

    except RetryError as e:
        firestore_io_logger.error(
            f"{e} occured while trying to delete whole collections from firestore"
        )
        raise
    except Exception as e:
        firestore_io_logger.exception(
            f"Unexpected error occured while trying to delete whole collections from firestore: {e}"
        )
        raise
    finally:
        db.close()


async def delete_summary_data_from_firestore(
    project_name: str,
    company_id: str,
    data: List[str],
    document_name: str,
    sub_document_name: str | None = None,
):
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                ref = db.collection(company_id).document(document_name)
                for id in data:
                    if sub_document_name:
                        await ref.update(
                            {f"{sub_document_name}.{id}": firestore.DELETE_FIELD}
                        )
                    else:
                        await ref.update({f"{id}": firestore.DELETE_FIELD})
    except RetryError as e:
        firestore_io_logger.error(
            f"{e} occured while trying to delete summary data from firestore"
        )
        raise
    except Exception as e:
        firestore_io_logger.exception(
            f"Unexpected error occured while trying to delete summary data from firestore: {e}"
        )
        raise
    finally:
        db.close()


async def delete_project_items_from_firestore(
    project_name: str,
    company_id: str,
    ids: List[str],
    document_name: str,
    project_key: str,
    doc_collection_names: List[str],
):
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                project_ref = (
                    db.collection(company_id)
                    .document(document_name)
                    .collection(project_key)
                    .where("__name__", "in", doc_collection_names)
                )

                async for doc in project_ref.stream():
                    for id in ids:
                        await doc.reference.update({id: firestore.DELETE_FIELD})

    except RetryError as e:
        firestore_io_logger.error(f"{e} occured while trying to delete project items")
        raise
    except Exception as e:
        firestore_io_logger.exception(
            f"Unexpected error occured while trying to delete project items: {e}"
        )
        raise
    finally:
        db.close()


async def update_invoice_projects_in_firestore(
    project_name: str,
    company_id: str,
    invoices: List[str],
    document_name: str,
    collection_name: str,
):
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                invoices_collection = (
                    db.collection(company_id)
                    .document(document_name)
                    .collection(collection_name)
                )
                invoice_ids = list(invoices.__root__.keys())

                async for doc in invoices_collection.stream():
                    if doc.id in invoice_ids:
                        await doc.reference.update(
                            {"project": dict(invoices.__root__[doc.id])}
                        )

    except RetryError as e:
        firestore_io_logger.error(
            f"{e} occured while trying to update invoice projects"
        )
        raise
    except Exception as e:
        firestore_io_logger.exception(
            f"Unexpected error occured while trying to update invoice projects: {e}"
        )
        raise
    finally:
        db.close()


async def update_processed_invoices_in_firestore(
    project_name: str,
    company_id: str,
    invoice_id: str,
    document_name: str,
    collection_name: str,
    data: dict,
) -> None:
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                invoice_doc_ref = (
                    db.collection(company_id)
                    .document(document_name)
                    .collection(collection_name)
                    .document(invoice_id)
                )
                if data["processedInvoiceData"]["change_order"] is not None:
                    change_order = data["processedInvoiceData"]["change_order"]
                else:
                    change_order = None

                await invoice_doc_ref.update(
                    {
                        "processed": data["isProcessed"],
                        "project": data["project"],
                        "processedData": data["processedInvoiceData"],
                        "change_order": change_order,
                    }
                )
    except RetryError as e:
        firestore_io_logger.error(
            f"{e} occured while trying to update processed invoices"
        )
        raise
    except Exception as e:
        firestore_io_logger.exception(
            f"Unexpected error occured while trying to update processed invoices: {e}"
        )
        raise
    finally:
        db.close()


async def remove_change_order_id_from_invoices_in_firestore(
    project_name: str,
    company_id: str,
    invoice_ids: List[str],
    change_order_id: str,
    document_name: str,
    collection_name: str,
) -> None:
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                invoice_doc_ref = (
                    db.collection(company_id)
                    .document(document_name)
                    .collection(collection_name)
                    .where("__name__", "in", invoice_ids)
                )
                async for doc in invoice_doc_ref.stream():
                    processed_data = doc.to_dict()["processedData"]

                    # if there are line items, have to search for the invoice there to remove it
                    # if no invoice is found, the dict will not change
                    update_line_items = {}
                    if processed_data["line_items"]:
                        for item_num, item in processed_data["line_items"].items():
                            if (
                                item["change_order"]
                                and item["change_order"]["uuid"] == change_order_id
                            ):
                                item["change_order"] = None
                                # item["bounding_box"] = None
                                update_line_items.update({item_num: item})
                            else:
                                update_line_items.update({item_num: item})
                        processed_data.update(
                            {
                                "change_order": None,
                                # "remove_from_change_order": None,
                                "line_items": update_line_items,
                            }
                        )
                        await doc.reference.update({"processedData": processed_data})
                    # if there are no line items, then we must have a change order for whole invoice
                    else:
                        await doc.reference.update(
                            {"change_order": None, "processedData": processed_data}
                        )

    except RetryError as e:
        firestore_io_logger.error(
            f"{e} occured while trying to delete document from DB"
        )
        raise
    except Exception as e:
        firestore_io_logger.exception(
            f"Unexpected error occurred while copying document to DB: {e}"
        )
        raise
    finally:
        db.close()


async def add_gpt_line_items_to_invoice_data_in_firestore(
    project_name: str,
    company_id: str,
    invoice_id: str,
    document_name: str,
    collection_name: str,
    data: dict,
) -> None:
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                invoice_doc = (
                    db.collection(company_id)
                    .document(document_name)
                    .collection(collection_name)
                    .document(invoice_id)
                )

                await invoice_doc.update(
                    {
                        "line_items_gpt": data,
                    }
                )
    except RetryError as e:
        firestore_io_logger.error(
            f"{e} occured while adding gpt line items to firestore. "
        )
        raise
    except Exception as e:
        firestore_io_logger.exception(
            f"Unexpected error occured while adding gpt line items to firestore: {e}"
        )
        raise
    finally:
        db.close()


async def update_approved_invoice_in_firestore(
    project_name: str,
    company_id: str,
    invoice_id: str,
    document_name: str,
    collection_name: str,
    is_approved: bool,
) -> None:
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                invoice_doc = (
                    db.collection(company_id)
                    .document(document_name)
                    .collection(collection_name)
                    .document(invoice_id)
                )

                await invoice_doc.update({"approved": is_approved})

    except RetryError as e:
        firestore_io_logger.error(
            f"{e} occured while trying update invoice approval in firestore. "
        )
        raise
    except Exception as e:
        firestore_io_logger.exception(
            f"Unexpected error occured while trying to update invoice approval in firestore: {e}"
        )
        raise
    finally:
        db.close()


async def push_update_to_firestore(
    project_name: str,
    collection: str,
    data: dict,
    document: str,
    sub_document_name: str | None = None,
    doc_collection: str | None = None,
    doc_collection_document: str | None = None,
) -> None:
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                document_ref = db.collection(collection).document(document)

                if doc_collection and doc_collection_document:
                    document_ref = document_ref.collection(doc_collection).document(
                        doc_collection_document
                    )

                doc = await document_ref.get()
                if doc.exists:
                    if sub_document_name:
                        for key, value in data.items():
                            await document_ref.update(
                                {f"{sub_document_name}.{key}": value}
                            )
                    else:
                        await document_ref.update(data)
                else:
                    if sub_document_name:
                        for key, value in data.items():
                            await document_ref.set(
                                {f"{sub_document_name}.{key}": value}
                            )
                    else:
                        await document_ref.set(data)

    except RetryError as e:
        firestore_io_logger.error(
            f"{e} occured while trying to make general push to firestore to document: {document} and (if exists) doc_collection: {doc_collection}. "
        )
        raise
    except Exception as e:
        firestore_io_logger.exception(
            f"Unexpected error occured while trying to make general push to firestore to document: {document} and (if exists) doc_collection: {doc_collection}: {e}"
        )
        raise
    finally:
        db.close()


async def update_project_status(
    project_name: str,
    collection: str,
    data: dict,
    item_ids: List[str],
) -> None:
    db = firestore.AsyncClient(project=project_name)
    try:
        document_ref_summary = db.collection(collection).document("project-summary")
        for key, value in data.items():
            for item_id in item_ids:
                await document_ref_summary.update(
                    {f"allProjects.{item_id}.{key}": value}
                )

        for item_id in item_ids:
            document_ref_full_data = (
                db.collection(collection)
                .document("projects")
                .collection(item_id)
                .document("project-details")
            )
            for key, value in data.items():
                await document_ref_full_data.update({key: value})
    except Exception as e:
        firestore_io_logger.exception(
            f"An error occurred updating project status {collection}: {e}"
        )
    finally:
        db.close()


async def get_project_docs_from_firestore(
    company_id: str,
    document: str,
    project: str,
    get_only_active_projects: bool = True,
) -> dict:
    docs = {}
    db = firestore.AsyncClient(project=project)
    try:
        collections = db.collection(company_id).document(document).collections()
        async for collection in collections:
            async for doc in collection.stream():
                if doc.id != "project-details":
                    continue
                project = doc.to_dict()
                if get_only_active_projects:
                    if project["isActive"]:
                        project_doc, owner = [], []
                        for main_cat in project["mainCategories"]:
                            for items in main_cat["inputElements"]:
                                if items["addressElements"]:
                                    for addr_el in items["addressElements"]:
                                        for item in addr_el["items"]:
                                            if item["id"] == "project-address":
                                                address = item["value"]
                                            if (
                                                item["id"]
                                                in PROJECT_DETAILS_MATCHING_KEYS
                                            ):
                                                project_doc.append(item["value"])
                                elif items["items"]:
                                    for item in items["items"]:
                                        if item["id"] in PROJECT_DETAILS_MATCHING_KEYS:
                                            project_doc.append(item["value"])
                                        if item["id"] == "client-first-name":
                                            owner.append(item["value"])
                                        if item["id"] == "client-last-name":
                                            owner.append(item["value"])
                                        if item["id"] == "project-name":
                                            project_name = item["value"]

                        docs[collection.id] = {
                            "doc": " ".join(project_doc),
                            "project_name": project_name,
                            "address": address,
                            "address_id": collection.id,
                            "owner": " ".join(owner),
                            "uuid": project["uuid"],
                        }
                else:
                    project_doc, owner = [], []
                    for main_cat in project["mainCategories"]:
                        for items in main_cat["inputElements"]:
                            if items["addressElements"]:
                                for addr_el in items["addressElements"]:
                                    for item in addr_el["items"]:
                                        if item["id"] == "project-address":
                                            address = item["value"]
                                        if item["id"] in PROJECT_DETAILS_MATCHING_KEYS:
                                            project_doc.append(item["value"])
                            elif items["items"]:
                                for item in items["items"]:
                                    if item["id"] in PROJECT_DETAILS_MATCHING_KEYS:
                                        project_doc.append(item["value"])
                                    if item["id"] == "client-first-name":
                                        owner.append(item["value"])
                                    if item["id"] == "client-last-name":
                                        owner.append(item["value"])
                                    if item["id"] == "project-name":
                                        project_name = item["value"]
                    docs[collection.id] = {
                        "doc": " ".join(project_doc),
                        "project_name": project_name,
                        "address": address,
                        "address_id": collection.id,
                        "owner": " ".join(owner),
                        "uuid": project["uuid"],
                    }
        db.close()
        return docs
    except Exception as e:
        firestore_io_logger.exception(
            f"An error occurred getting project {company_id}: {e}"
        )
    finally:
        db.close()
