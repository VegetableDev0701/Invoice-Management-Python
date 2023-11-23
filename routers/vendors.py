import asyncio
import json
from typing import List

from fastapi import APIRouter, Depends, HTTPException

from validation import io_validation
from config import PROJECT_NAME
from utils.database.firestore import (
    get_all_project_details_data,
    push_to_firestore,
    get_from_firestore,
    push_update_to_firestore,
    delete_collections_from_firestore,
    delete_summary_data_from_firestore,
)

from utils import auth
from utils.data_models.vendors import FullVendorDataToAdd


router = APIRouter()


@router.get("/{company_id}/vendors-data")
async def get_projects_data(
    company_id: str, current_user=Depends(auth.get_current_user)
) -> str:
    auth.check_user_data(company_id=company_id, current_user=current_user)

    doc = await get_all_project_details_data(
        project_name=PROJECT_NAME,
        collection_name=company_id,
        document_name="vendors",
        details_doc_name="vendor-details",
    )

    return json.dumps(doc)


@router.get("/{company_id}/get-vendors-summary")
async def get_vendors_summary(
    company_id: str, current_user=Depends(auth.get_current_user)
) -> str:
    auth.check_user_data(company_id=company_id, current_user=current_user)

    vendors_summary = await get_from_firestore(
        project_name=PROJECT_NAME,
        collection_name=company_id,
        document_name="vendor-summary",
    )

    return json.dumps(vendors_summary)


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
            status_code=400, detail="Invalid Email or Phone Number entered."
        )

    task1 = push_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data=full_data.dict(),
        document="vendors",
        doc_collection=full_data.uuid,
        doc_collection_document="vendor-details",
    )

    task2 = push_update_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data={full_data.uuid: new_summary_data.dict()},
        document="vendor-summary",
        sub_document_name="allVendors",
    )
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

    validate_fields = io_validation.traverse_data_model(full_data)
    if not any([*validate_fields.values()]):
        raise HTTPException(
            status_code=400, detail="Invalid Email or Phone Number entered."
        )

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
        data={vendor_id: new_summary_data.dict()},
        document="vendor-summary",
        sub_document_name="allVendors",
    )

    _ = await asyncio.gather(task1, task2)

    return {"message": "Succesfully updated vendor."}


@router.delete("/{company_id}/delete-vendors")
async def delete_vendor(
    company_id: str, data: List[str], current_user=Depends(auth.get_current_user)
):
    auth.check_user_data(company_id=company_id, current_user=current_user)

    task1 = delete_collections_from_firestore(
        project_name=PROJECT_NAME,
        company_id=company_id,
        data=data,
        document_name="vendors",
    )

    task2 = delete_summary_data_from_firestore(
        project_name=PROJECT_NAME,
        company_id=company_id,
        data=data,
        document_name="vendor-summary",
        sub_document_name="allVendors",
    )
    _ = asyncio.gather(task1, task2)

    return {"message": "Successfully deleted vendor(s)."}
