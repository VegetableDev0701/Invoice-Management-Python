import asyncio

from fastapi import APIRouter, Depends

from config import PROJECT_NAME
from utils import auth
from utils.data_models.change_orders import (
    FullChangeOrderDataToAdd,
    ChangeOrderContent,
    DeleteChangeOrderData,
)
from utils.database.invoice_utils import update_invoice_processed_data
from utils.database.firestore import (
    push_to_firestore,
    delete_project_items_from_firestore,
    push_update_to_firestore,
)

router = APIRouter()


@router.post("/{company_id}/add-change-order")
async def add_labor(
    company_id: str,
    project_id: str,
    data: FullChangeOrderDataToAdd,
    current_user=Depends(auth.get_current_user),
):
    auth.check_user_data(company_id=company_id, current_user=current_user)

    full_data = data.fullData
    new_summary_data = data.summaryData

    task1 = push_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data={full_data.uuid: full_data.dict()},
        document="projects",
        doc_collection=project_id,
        doc_collection_document="change-orders",
    )

    task2 = push_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data={full_data.uuid: new_summary_data.dict()},
        document="projects",
        doc_collection=project_id,
        doc_collection_document="change-orders-summary",
    )

    await asyncio.gather(task1, task2)

    return {
        "message": "Succesfully added new change order to project.",
    }


@router.patch("/{company_id}/update-change-order")
async def update_labor(
    company_id: str,
    project_id: str,
    change_order_id: str,
    data: FullChangeOrderDataToAdd,
    current_user=Depends(auth.get_current_user),
):
    auth.check_user_data(company_id=company_id, current_user=current_user)

    full_data = data.fullData
    new_summary_data = data.summaryData

    task1 = push_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data={change_order_id: full_data.dict()},
        document="projects",
        doc_collection=project_id,
        doc_collection_document="change-orders",
    )

    task2 = push_update_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data={change_order_id: new_summary_data.dict()},
        document="projects",
        doc_collection=project_id,
        doc_collection_document="change-orders-summary",
    )

    await asyncio.gather(task1, task2)

    return {
        "message": "Succesfully updated change order.",
    }


# Used to add/update specifically the content of a change order. Done when a user
@router.patch("/{company_id}/update-change-order-content")
async def update_labor(
    company_id: str,
    project_id: str,
    data: ChangeOrderContent,
    current_user=Depends(auth.get_current_user),
):
    auth.check_user_data(company_id=company_id, current_user=current_user)

    tasks = []
    for change_order_id in data.dict()["__root__"].keys():
        coroutine = push_update_to_firestore(
            project_name=PROJECT_NAME,
            collection=company_id,
            data=data.dict()["__root__"][change_order_id],
            document="projects",
            doc_collection=project_id,
            doc_collection_document="change-orders-summary",
            sub_document_name=change_order_id,
        )
        tasks.append(asyncio.create_task(coroutine))

    await asyncio.gather(*tasks)

    return {
        "message": "Succesfully updated change order content.",
    }


# used when a user deletes a
@router.patch("/{company_id}/update-change-order-summary")
@router.delete("/{company_id}/delete-change-order")
async def delete_labor(
    company_id: str,
    project_id: str,
    data: DeleteChangeOrderData,
    current_user=Depends(auth.get_current_user),
) -> dict:
    auth.check_user_data(company_id=company_id, current_user=current_user)

    change_order_ids_to_remove = data.removeChangeOrderIds
    update_processed_data = data.updateProcessedData

    task1 = delete_project_items_from_firestore(
        project_name=PROJECT_NAME,
        company_id=company_id,
        ids=change_order_ids_to_remove,
        document_name="projects",
        project_key=project_id,
        doc_collection_names=["change-orders-summary", "change-orders"],
    )

    task2 = update_invoice_processed_data(
        project_name=PROJECT_NAME,
        company_id=company_id,
        document_name="documents",
        collection_name="processed_documents",
        data=update_processed_data,
    )

    # task3 =

    await asyncio.gather(task1, task2)

    return {"message": "Succesfully deleted change order."}
