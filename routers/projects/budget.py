from fastapi import APIRouter, Depends

from typing import List
from config import PROJECT_NAME
from utils import auth
from utils.data_models.projects import ProjectBudget
from utils.data_models.budgets import UpdateCostCode
from utils.database.firestore import (
    push_to_firestore,
)
from utils.database.projects import utils as project_utils

router = APIRouter()


@router.patch("/{company_id}/update-budget")
async def update_budget(
    company_id: str,
    project_id: str,
    data: ProjectBudget,
    # current_user=Depends(auth.get_current_user),
) -> dict:
    # auth.check_user_data(company_id=company_id, current_user=current_user)

    await push_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data=data.dict(),
        document="projects",
        doc_collection=project_id,
        doc_collection_document="budget",
    )

    return {"message": "Successfully updated budget."}


@router.patch("/{company_id}/update-all-project-budgets")
async def update_all_budgets(
    company_id: str,
    data: List[UpdateCostCode],
    # current_user=Depends(auth.get_current_user),
) -> dict:
    # auth.check_user_data(company_id=company_id, current_user=current_user)

    await project_utils.update_all_project_budgets(
        project_name=PROJECT_NAME,
        collection=company_id,
        data=data,
        document="projects",
    )

    return {"message": "Successfully updated all project budgets."}
