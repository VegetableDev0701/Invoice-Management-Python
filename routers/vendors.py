import asyncio
import json
from typing import List

from fastapi import APIRouter, Depends
from utils.agave_utils import find_unique_entries, get_all_vendors_from_agave

from config import PROJECT_NAME
from utils.database.firestore import (
    get_all_project_details_data,
    push_to_firestore,
    push_update_to_firestore,
    delete_collections_from_firestore,
)

from utils import auth
from utils.data_models.vendors import FullBulkVendorDataToAdd, FullVendorDataToAdd


router = APIRouter()


@router.get("/{company_id}/get-all-vendors")
async def get_projects_data(
    company_id: str, current_user=Depends(auth.get_current_user)
) -> str:
    auth.check_user_data(company_id=company_id, current_user=current_user)

    doc = await get_all_project_details_data(
        project_name=PROJECT_NAME,
        collection_name=company_id,
        document_name="vendors",
        doc_names=["vendor-details", "vendor-summary"],
    )

    return json.dumps(doc)


@router.post("/{company_id}/add-vendors-bulk", status_code=201)
async def add_vendors_bulk(
    company_id: str,
    data: FullBulkVendorDataToAdd,
    current_user=Depends(auth.get_current_user),
) -> dict:
    auth.check_user_data(company_id=company_id, current_user=current_user)

    full_data = data.fullData
    summary_data = data.summaryData

    tasks = []
    if full_data:
        # the summary data and full data should have the same set of keys
        for i, vendor_id in enumerate(full_data.keys()):
            tasks.append(
                asyncio.create_task(
                    push_to_firestore(
                        project_name=PROJECT_NAME,
                        collection=company_id,
                        data=full_data[vendor_id].dict(),
                        document="vendors",
                        doc_collection=vendor_id,
                        doc_collection_document="vendor-details",
                    )
                )
            )
            tasks.append(
                asyncio.create_task(
                    push_to_firestore(
                        project_name=PROJECT_NAME,
                        collection=company_id,
                        data=summary_data[vendor_id].dict(),
                        document="vendors",
                        doc_collection=vendor_id,
                        doc_collection_document="vendor-summary",
                    )
                )
            )
        _ = await asyncio.gather(*tasks)

        return {"message": f"Succesfully added all {i + 1} vendor(s)."}
    else:
        return {"message": "No new vendors."}


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

    # TODO add to QBD via agave function
    _ = await asyncio.gather(task1, task2)

    return {
        "message": "Succesfully saved new vendor.",
    }


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

    _ = await asyncio.gather(task1, task2)

    return {"message": "Succesfully updated vendor."}


@router.delete("/{company_id}/delete-vendors")
async def delete_vendor(
    company_id: str, data: List[str], current_user=Depends(auth.get_current_user)
):
    auth.check_user_data(company_id=company_id, current_user=current_user)

    await delete_collections_from_firestore(
        project_name=PROJECT_NAME,
        company_id=company_id,
        data=data,
        document_name="vendors",
    )

    return {"message": "Successfully deleted vendor(s)."}


@router.get("/{company_id}/get-vendors-agave")
async def get_vendors_agave(company_id, current_user=Depends(auth.get_current_user)):
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

    # save raw vendor data into firestore
    await push_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data=response_dict,
        document="quickbooks-desktop-data",
        doc_collection="vendors",
        doc_collection_document="vendors",
    )
    return {
        "message": f"Succesfully retrieved all {len(new_vendors)} new vendors.",
        "agave_response_data": new_vendors,
    }
