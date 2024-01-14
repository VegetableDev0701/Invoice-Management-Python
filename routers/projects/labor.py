from typing import List

from fastapi import APIRouter, Depends

from config import PROJECT_NAME
from utils import auth
from utils.data_models.projects import FullLaborDataToAdd
from utils.database.firestore import (
    push_to_firestore,
    delete_project_items_from_firestore,
)

router = APIRouter()


@router.post("/{company_id}/add-labor")
async def add_labor(
    company_id: str,
    project_id: str,
    data: FullLaborDataToAdd,
    # current_user=Depends(auth.get_current_user),
) -> dict:
    # auth.check_user_data(company_id=company_id, current_user=current_user)

    full_data = data.fullData
    new_summary_data = data.summaryData

    await push_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data={full_data.uuid: full_data.dict()},
        document="projects",
        doc_collection=project_id,
        doc_collection_document="labor",
    )

    await push_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data={full_data.uuid: new_summary_data.dict()},
        document="projects",
        doc_collection=project_id,
        doc_collection_document="labor-summary",
    )

    return {
        "message": "Succesfully added new labor to project.",
    }


@router.patch("/{company_id}/update-labor")
async def update_labor(
    company_id: str,
    project_id: str,
    labor_id: str,
    data: FullLaborDataToAdd,
    # current_user=Depends(auth.get_current_user),
) -> dict:
    # auth.check_user_data(company_id=company_id, current_user=current_user)

    full_data = data.fullData
    new_summary_data = data.summaryData
    new_summary_data.currentLabor = True

    await push_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data={labor_id: full_data.dict()},
        document="projects",
        doc_collection=project_id,
        doc_collection_document="labor",
    )

    await push_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data={labor_id: new_summary_data.dict()},
        document="projects",
        doc_collection=project_id,
        doc_collection_document="labor-summary",
    )

    return {
        "message": "Succesfully updated labor.",
    }


@router.delete("/{company_id}/delete-labor")
async def delete_labor(
    company_id: str,
    project_id: str,
    data: List[str],
    # current_user=Depends(auth.get_current_user),
) -> dict:
    # auth.check_user_data(company_id=company_id, current_user=current_user)

    await delete_project_items_from_firestore(
        project_name=PROJECT_NAME,
        company_id=company_id,
        ids=data,
        document_name="projects",
        project_key=project_id,
        doc_collection_names=["labor-summary", "labor"],
    )

    return {"message": "Succesfully deleted labor."}
