import asyncio

from fastapi import APIRouter, Depends

from config import PROJECT_NAME
from utils.database.firestore import get_from_firestore, push_to_firestore
from utils import auth
from utils.data_models.budgets import CostCodes
from utils.storage_utils import save_updated_cost_codes_to_gcs

router = APIRouter()


@router.get("/{company_id}/cost-codes")
async def get_cost_codes(
    company_id: str, 
    # current_user=Depends(auth.get_current_user)
) -> dict:
    auth.check_user_data(company_id=company_id, current_user=current_user)

    cost_codes = await get_from_firestore(
        project_name=PROJECT_NAME,
        collection_name=company_id,
        document_name="cost-codes",
    )

    return cost_codes


@router.post("/{company_id}/update-cost-codes")
async def update_cost_codes(
    company_id: str,
    data: CostCodes,
    current_user=Depends(auth.get_current_user),
) -> dict:
    auth.check_user_data(company_id=company_id, current_user=current_user)

    task1 = push_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data=data.dict(),
        document="cost-codes",
    )

    task2 = save_updated_cost_codes_to_gcs(
        company_id=company_id, data=data.dict(), bucket="stak-customer-cost-codes"
    )

    # TODO Add a sync to quickbooks function like with vendors.
    # TODO add the newly returned agave_uuids to firestore and storage
    # TODO return the agave_uuids to the frontend to be added to the state

    _ = asyncio.gather(task1, task2)

    return {"message": "Cost codes updated successfully."}
