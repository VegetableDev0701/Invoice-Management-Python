import asyncio
import json

from fastapi import APIRouter, Depends

from config import PROJECT_NAME
from utils.database.firestore import get_from_firestore, push_to_firestore
from utils import auth
from utils.data_models.budgets import CostCodes
from utils.storage_utils import save_updated_cost_codes_to_gcs

router = APIRouter()


@router.get("/{company_id}/get-employees-customers")
async def get_employees_and_customer_data(
    company_id: str, current_user=Depends(auth.get_current_user)
) -> dict:
    auth.check_user_data(company_id=company_id, current_user=current_user)

    get_employees_task = get_from_firestore(
        project_name=PROJECT_NAME, collection_name=company_id, document_name="employees"
    )
    get_customers_task = get_from_firestore(
        project_name=PROJECT_NAME, collection_name=company_id, document_name="customers"
    )

    employees, customers = await asyncio.gather(get_employees_task, get_customers_task)
    return {"employees": employees, "customers": customers}
