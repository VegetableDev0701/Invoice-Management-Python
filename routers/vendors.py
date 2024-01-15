import asyncio
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException
from utils.agave_utils import (
    add_vendors_to_qbd,
    delete_vendors_from_qbd,
    find_unique_entries,
    get_agave_uuid_from_vendor_id,
    get_all_vendors_from_agave,
    handle_qbd_response,
)

from config import PROJECT_NAME
from utils.database.firestore import (
    get_all_project_details_data,
    push_qbd_data_to_firestore,
    push_qbd_data_to_firestore_batched,
    push_to_firestore,
    push_update_to_firestore,
    delete_collections_from_firestore,
)

from utils import auth
from utils.data_models.vendors import (
    FullVendorDataToAdd,
    SummaryVendorData,
)
from utils.vendor_utils import (
    add_vendors_wrapper,
    traverse_all_docs_and_match_empty_vendors,
)

from validation import io_validation


router = APIRouter()


@router.get("/{company_id}/get-all-vendors")
async def get_projects_data(
    company_id: str, 
    # current_user=Depends(auth.get_current_user)
) -> dict:
    auth.check_user_data(company_id=company_id, current_user=current_user)

    doc = await get_all_project_details_data(
        project_name=PROJECT_NAME,
        collection_name=company_id,
        document_name="vendors",
        doc_names=["vendor-summary"],
    )

    return doc



@router.post("/{company_id}/add-vendor", status_code=201)
async def add_vendor(
    company_id: str,
    data: FullVendorDataToAdd,
    current_user=Depends(auth.get_current_user),
):
    auth.check_user_data(company_id=company_id, current_user=current_user)

    # Both the new project and a summary of that projects data come in at the same time
    full_data = data.fullData
    new_summary_data = data.summaryData

    validate_fields = io_validation.traverse_data_model(full_data)
    if not any([*validate_fields.values()]):
        raise HTTPException(
            status_code=400,
            detail="Invalid Email or Phone Number entered.",
        )

    task1 = push_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data=full_data.dict(),
        document="vendors",
        doc_collection=full_data.uuid,
        doc_collection_document="vendor-details",
    )

    task2 = push_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data=new_summary_data.dict(),
        document="vendors",
        doc_collection=new_summary_data.uuid,
        doc_collection_document="vendor-summary",
    )

    task3 = add_vendors_to_qbd(
        new_vendor_summary=new_summary_data.dict(), company_id=company_id
    )

    _, _, qbd_response = await asyncio.gather(task1, task2, task3)

    # returns a dict if the vendor already exists in quickbooks
    response_dict = await handle_qbd_response(
        qbd_response=qbd_response, company_id=company_id, summary_data=new_summary_data
    )

    return response_dict


@router.patch("/{company_id}/update-vendor")
async def update_vendor(
    company_id: str,
    vendor_id: str,
    data: FullVendorDataToAdd,
    current_user=Depends(auth.get_current_user),
):
    auth.check_user_data(company_id=company_id, current_user=current_user)
    full_data = data.fullData
    new_summary_data = data.summaryData

    task1 = push_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data=full_data.dict(),
        document="vendors",
        doc_collection=vendor_id,
        doc_collection_document="vendor-details",
    )

    task2 = push_update_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data=new_summary_data.dict(),
        document="vendors",
        doc_collection=vendor_id,
        doc_collection_document="vendor-summary",
    )

    # Only update in QBD if it already exists. If not the user has to manually sync this vendor.
    if new_summary_data.agave_uuid is not None:
        task3 = add_vendors_to_qbd(
            new_vendor_summary=new_summary_data.dict(),
            company_id=company_id,
            is_update=True,
        )
        _, _, qbd_response = await asyncio.gather(task1, task2, task3)
        # returns a dict if the vendor already exists in quickbooks
        response_dict = await handle_qbd_response(
            qbd_response=qbd_response,
            company_id=company_id,
            summary_data=new_summary_data,
        )
        return response_dict
    else:
        await asyncio.gather(task1, task2)

        return {
            "message": "Successfully updated vendor in Stak. Vendor is not synced to Quickbooks."
        }


@router.delete("/{company_id}/delete-vendors")
async def delete_vendor(
    company_id: str, data: List[str], 
    # current_user=Depends(auth.get_current_user)
):
    auth.check_user_data(company_id=company_id, current_user=current_user)

    agave_uuids = await get_agave_uuid_from_vendor_id(
        vendor_ids=data,
        project_name=PROJECT_NAME,
        company_id=company_id,
        document_name="vendors",
    )

    response_agave = await delete_vendors_from_qbd(agave_uuids, vendor_ids=data)

    await delete_collections_from_firestore(
        project_name=PROJECT_NAME,
        company_id=company_id,
        data=data,
        document_name="vendors",
    )

    response = {
        "message_stak": "Successfully deleted vendor(s).",
    }
    response.update(response_agave)

    return response


@router.get("/{company_id}/get-vendors-agave")
async def get_vendors_agave(
    company_id: str, 
    # current_user=Depends(auth.get_current_user)
) -> dict:
    auth.check_user_data(company_id=company_id, current_user=current_user)

    get_vendors_agave_task = get_all_vendors_from_agave(company_id)

    get_current_vendors_task = get_all_project_details_data(
        project_name=PROJECT_NAME,
        collection_name=company_id,
        document_name="vendors",
        doc_names="vendor-summary",
    )

    response_dict, current_vendors_dict = await asyncio.gather(
        get_vendors_agave_task, get_current_vendors_task
    )

    new_vendors = find_unique_entries(response_dict, current_vendors_dict)

    # to batch or not to batch, that is the question
    push_qbd_data_func = (
        push_qbd_data_to_firestore_batched
        if len(new_vendors["data"]) > 100
        else push_qbd_data_to_firestore
    )

    _ = await push_qbd_data_func(
        project_name=PROJECT_NAME,
        collection=company_id,
        data=new_vendors,
        document="quickbooks-desktop-data",
        doc_collection="vendors",
    )

    unique_data_ext_names = set(
        data_ext["DataExtName"]
        for item in response_dict["data"]
        if "source_data" in item
        and "data" in item["source_data"]
        and "DataExtRet" in item["source_data"]["data"]
        for data_ext in item["source_data"]["data"]["DataExtRet"]
        if "DataExtName" in data_ext
    )

    (
        vendor_data_to_add_to_firestore,
        update_doc_dict,
    ) = await add_vendors_wrapper(
        company_id=company_id,
        new_vendors_to_add=new_vendors,
        unique_data_ext_names=unique_data_ext_names,
    )

    return {
        "message": f"Succesfully retrieved all {len(new_vendors['data'])} new vendors.",
        "agave_response_data": vendor_data_to_add_to_firestore["summaryData"],
        "update_doc_data": update_doc_dict,
    }


@router.patch("/{company_id}/sync-vendors-agave")
async def sync_vendors_agave(
    company_id: str,
    data: Dict[str, SummaryVendorData],
    current_user=Depends(auth.get_current_user),
):
    auth.check_user_data(company_id=company_id, current_user=current_user)

    tasks = []

    for vendor in data.values():
        tasks.append(
            asyncio.create_task(
                add_vendors_to_qbd(
                    new_vendor_summary=vendor.dict(),
                    company_id=company_id,
                    is_update=False,
                )
            )
        )
    results = await asyncio.gather(*tasks)

    # Loop through all vendors that we are trying to sync and if they don't get synced return
    # TODO try and match the newly synced vendors to current docs without agave_uuid
    results_dict = {}
    vendor_summary_list = []
    for result, (vendor_id, vendor) in zip(results, data.items()):
        if result is None:
            results_dict[vendor_id] = {
                "message": "Error adding vendor",
                "uuid": vendor_id,
            }
        else:
            results_dict[vendor_id] = await handle_qbd_response(
                result, company_id, vendor, is_sync=True
            )
            if "agave_uuid" in results_dict[vendor_id]:
                vendor_summary_list.append(vendor.dict())

    update_doc_dict = {"contract": {}, "invoice": {}}
    if vendor_summary_list:
        update_doc_dict = await traverse_all_docs_and_match_empty_vendors(
            company_id=company_id,
            vendor_summary_list=vendor_summary_list,
        )

    return {"data": results_dict, "update_doc_data": update_doc_dict}
