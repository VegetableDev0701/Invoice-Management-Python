import json

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from config import PROJECT_NAME
from utils.database.firestore import get_from_firestore, push_to_firestore
from utils import auth
from utils.data_models.budgets import CostCodes

router = APIRouter()


@router.get("/{company_id}/cost-codes")
async def get_cost_codes(
    company_id: str,
    #current_user=Depends(auth.get_current_user)
) -> str:
    #auth.check_user_data(company_id=company_id, current_user=current_user)

    cost_codes = await get_from_firestore(
        project_name=PROJECT_NAME,
        collection_name=company_id,
        document_name="cost-codes",
    )

    return json.dumps(cost_codes)

@router.post("/{company_id}/update-cost-codes")
async def update_cost_codes(
    company_id: str,
    data: CostCodes,
    #current_user=Depends(auth.get_current_user),
) -> dict:
    #auth.check_user_data(company_id=company_id, current_user=current_user)
    print(data)
    await push_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data=data.dict(),
        document="cost-codes",
    )

    return {"message": "Cost codes updated successfully."}
