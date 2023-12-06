import asyncio
import json
from typing import List
import pandas as pd
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from validation import io_validation
from config import PROJECT_NAME
from utils import auth
from utils.data_models.projects import FullProjectDataToAdd
from utils.data_models.charts import B2AReportDataItem, FullB2ADataV2
from utils.database.firestore import (
    get_all_project_details_data,
    push_to_firestore,
    get_from_firestore,
    stream_all_project_data,
    push_update_to_firestore,
    delete_collections_from_firestore,
    delete_summary_data_from_firestore,
    update_project_status,
)


router = APIRouter()


@router.get("/{company_id}/projects-data")
async def get_projects_data(
    company_id: str,
    current_user=Depends(auth.get_current_user)
) -> str:
    """
    Fetches all project details data for a given company.

    This function checks the current user's authorization, then retrieves all project
    details for the specified company. The results are returned as a JSON string.

    Args:
        company_id (str): The ID of the company for which project data is to be retrieved.
        current_user (dict, optional): The current user's details. Defaults to the user
            returned by `auth.get_current_user()`.

    Returns:
        str: A JSON string containing all the project details for the specified company.
    """
    auth.check_user_data(company_id=company_id, current_user=current_user)

    doc = await get_all_project_details_data(
        project_name=PROJECT_NAME,
        collection_name=company_id,
        document_name="projects",
        details_doc_name="project-details",
    )

    return json.dumps(doc)


@router.get("/{company_id}/get-projects-summary")
async def get_projects_summary(
    company_id: str,
    current_user=Depends(auth.get_current_user)
) -> str:
    """
    Fetches the summary of projects for a given company.

    This function checks the current user's authorization, then retrieves the projects summary
    for the specified company. The results are returned as a JSON string.

    Args:
        company_id (str): The ID of the company for which the projects summary is to be retrieved.
        current_user (dict, optional): The current user's details. Defaults to the user
            returned by `auth.get_current_user()`.

    Returns:
        str: A JSON string containing the projects summary for the specified company.
    """
    auth.check_user_data(company_id=company_id, current_user=current_user)

    projects_summary = await get_from_firestore(
        project_name=PROJECT_NAME,
        collection_name=company_id,
        document_name="project-summary",
    )

    return json.dumps(projects_summary)


@router.get("/{company_id}/get-all-project-data")
async def get_all_project_data(
    company_id: str,
    project_id: str,
    current_user=Depends(auth.get_current_user)
) -> str | None:
    """
    Fetches all data related to a specific project for a given company.

    This function checks the current user's authorization, then retrieves all data
    for the specified project and company. The results are returned as a JSON string.

    Args:
        company_id (str): The ID of the company for which the project data is to be retrieved.
        project_id (str): The ID of the project for which the data is to be retrieved.
        current_user (dict, optional): The current user's details. Defaults to the user
            returned by `auth.get_current_user()`.

    Returns:
        str: A JSON string containing all the project data for the specified company and project.
            If no data is found, returns None.
    """
    auth.check_user_data(company_id=company_id, current_user=current_user)

    project_data = await stream_all_project_data(
        project_name=PROJECT_NAME,
        collection_name=company_id,
        document_name="projects",
        project_id=project_id,
    )

    if project_data is None:
        pass
    else:
        return json.dumps(project_data)


@router.post("/{company_id}/add-project", status_code=201)
async def add_project(
    company_id: str,
    data: FullProjectDataToAdd,
    current_user=Depends(auth.get_current_user),
) -> dict:
    """
    Adds a new project to a given company's project collection.

    This function checks the current user's authorization, validates the provided data,
    and adds a new project and its summary to the Firestore database. If any fields are
    invalid, it raises an HTTPException with status code 400.

    Args:
        company_id (str): The ID of the company to which the project will be added.
        data (data_model.FullProjectDataToAdd): The data model containing the full project
            data and the summary data to be added.
        current_user (dict, optional): The current user's details. Defaults to the user
            returned by `auth.get_current_user()`.

    Returns:
        dict: A dictionary containing a success message if the operation was successful.

    Raises:
        HTTPException: If any fields in the provided data are invalid.
    """
    auth.check_user_data(company_id=company_id, current_user=current_user)
    # Both the new project and a summary of that projects data come in at the same time
    full_data = data.fullData
    new_summary_data = data.summaryData
    new_summary_data.uuid = full_data.uuid

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
        document="projects",
        doc_collection=full_data.uuid,
        doc_collection_document="project-details",
    )

    task2 = push_update_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data={full_data.uuid: new_summary_data.dict()},
        document="project-summary",
        sub_document_name="allProjects",
    )

    await asyncio.gather(task1, task2)

    return {
        "message": "Successfully added new project.",
    }


@router.patch("/{company_id}/update-project")
async def update_project(
    company_id: str,
    project_id: str,
    data: FullProjectDataToAdd,
    current_user=Depends(auth.get_current_user),
) -> dict:
    """
    Updates a specific project of a given company.

    This function checks the current user's authorization, then updates the provided
    project data and its summary in the Firestore database.

    Args:
        company_id (str): The ID of the company for which the project is to be updated.
        project_id (str): The ID of the project to be updated.
        data (data_model.FullProjectDataToAdd): The data model containing the full project
            data and the summary data to be updated.
        current_user (dict, optional): The current user's details. Defaults to the user
            returned by `auth.get_current_user()`.

    Returns:
        dict: A dictionary containing a success message if the operation was successful.
    """
    auth.check_user_data(company_id=company_id, current_user=current_user)

    full_data = data.fullData
    new_summary_data = data.summaryData

    task1 = push_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data=full_data.dict(),
        document="projects",
        doc_collection=project_id,
        doc_collection_document="project-details",
    )

    task2 = push_update_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data={project_id: new_summary_data.dict()},
        document="project-summary",
        sub_document_name="allProjects",
    )

    await asyncio.gather(task1, task2)

    return {"message": "Successfully updated project."}


@router.patch("/{company_id}/change-project-status")
async def change_project_status(
    company_id: str,
    data: List[str],
    change_status_to: str,
    current_user=Depends(auth.get_current_user),
) -> dict:
    """
    Changes the status of specific projects of a given company.

    This function checks the current user's authorization, then updates the status
    of the provided project IDs in the Firestore database.

    Args:
        company_id (str): The ID of the company for which the projects' status is to be updated.
        change_status_to (str): The new status to be set for the projects.
        data (List[str]): A list of project IDs for which the status is to be updated.
        current_user (dict, optional): The current user's details. Defaults to the user
            returned by `auth.get_current_user()`.

    Returns:
        dict: A dictionary containing a success message if the operation was successful.
    """
    auth.check_user_data(company_id=company_id, current_user=current_user)

    # Update in the summary data
    await update_project_status(
        project_name=PROJECT_NAME,
        collection=company_id,
        data={"isActive": change_status_to},
        item_ids=data,
    )

    return {"message": "Project status successfully changed."}


@router.delete("/{company_id}/delete-projects")
async def delete_project(
    company_id: str,
    data: List[str],
    current_user=Depends(auth.get_current_user)
) -> dict:
    """
    Deletes specific projects of a given company.

    This function checks the current user's authorization, then deletes the provided
    project IDs from the Firestore database and the associated project summary data.

    Args:
        company_id (str): The ID of the company for which the projects are to be deleted.
        data (List[str]): A list of project IDs to be deleted.
        current_user (dict, optional): The current user's details. Defaults to the user
            returned by `auth.get_current_user()`.

    Returns:
        dict: A dictionary containing a success message if the operation was successful.
    """
    auth.check_user_data(company_id=company_id, current_user=current_user)

    task1 = delete_collections_from_firestore(
        project_name=PROJECT_NAME,
        company_id=company_id,
        data=data,
        document_name="projects",
    )

    task2 = delete_summary_data_from_firestore(
        project_name=PROJECT_NAME,
        company_id=company_id,
        data=data,
        document_name="project-summary",
        sub_document_name="allProjects",
    )

    await asyncio.gather(task1, task2)

    return {"message": "Successfully deleted project(s)."}


@router.post("/{company_id}/add-b2achartdata")
async def add_project_b2a_chart_data(
    company_id: str,
    project_id: str,
    data: FullB2ADataV2,
    current_user=Depends(auth.get_current_user),
) -> dict:
    auth.check_user_data(company_id=company_id, current_user=current_user)

    await push_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data=data.dict(),
        document="projects",
        doc_collection=project_id,
        doc_collection_document="b2a",
    )

    return {"message": "Successfully updated B2A Chart Data."}


@router.post("/{company_id}/build-b2a-report")
async def build_b2a_report(
    company_id: str,
    project_id: str,
    data: List[B2AReportDataItem],
    current_user=Depends(auth.get_current_user),
) -> dict :
    auth.check_user_data(company_id=company_id, current_user=current_user)
    
    report_data = {
        'Service': [],
        'Budget': [],
        'Actual Costs': [],
        'Difference': [],
        '%': [],
    }

    for item in data:
        report_data["Service"].append(item.title)
        report_data["Budget"].append(item.budgetAmount)
        report_data["Actual Costs"].append(item.actualAmount)
        report_data["Difference"].append(item.difference)
        report_data["%"].append(item.percent)

    df = pd.DataFrame(report_data)

    unique_filename = f"{str(datetime.now()).replace(' ', '_').replace(':', '-').split('.')[0]}.xlsx"

    df.to_excel(f"static/{unique_filename}", index=False)

    return {"message": "Successfully built B2A Report.", "download_url": unique_filename}
