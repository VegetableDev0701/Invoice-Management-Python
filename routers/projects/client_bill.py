import json
from typing import List
import requests

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from config import PROJECT_NAME, Config
from global_vars.globals_io import AGAVE_AR_INVOICES_URL
from utils import auth
from utils.database.firestore import (
    push_update_to_firestore,
)
from utils.database.projects.utils import (
    get_client_bill_from_firestore,
    add_new_client_bill,
    add_client_bill_actuals,
    get_client_bill_current_actuals_from_firestore,
    update_client_bill_details,
)
from utils.database.projects.client_bill_utils import (
    delete_client_bill_background,
)
from utils.data_models.projects import AddClientBillData, UpdateClientBillData
from utils.database.projects.build_ar_invoice_utils import (
    get_agave_customer_id,
    build_ar_invoice_request_data,
)
from utils.io_utils import access_secret_version

router = APIRouter()


@router.get("/{company_id}/get-client-bill")
async def get_client_bill(
    company_id: str,
    project_id: str,
    client_bill_id: str,
    is_only_current_actuals: str,
    current_user=Depends(auth.get_current_user),
) -> dict:
    auth.check_user_data(company_id=company_id, current_user=current_user)

    if is_only_current_actuals == "true":
        current_actuals = await get_client_bill_current_actuals_from_firestore(
            project_name=PROJECT_NAME,
            collection=company_id,
            project_id=project_id,
            client_bill_id=client_bill_id,
        )
        return current_actuals
    else:
        client_bill = await get_client_bill_from_firestore(
            project_name=PROJECT_NAME,
            collection=company_id,
            project_id=project_id,
            client_bill_id=client_bill_id,
        )
    return client_bill


@router.post("/{company_id}/update-client-bill")
async def update_client_bill(
    company_id: str,
    project_id: str,
    client_bill_id: str,
    data: UpdateClientBillData,
    current_user=Depends(auth.get_current_user),
) -> dict:
    auth.check_user_data(company_id=company_id, current_user=current_user)

    return_data = await update_client_bill_details(
        project_name=PROJECT_NAME,
        collection=company_id,
        project_id=project_id,
        client_bill_id=client_bill_id,
        data=data,
    )

    if return_data:
        return return_data
    else:
        return {"message": "Successfully updated client bill."}


@router.post("/{company_id}/add-client-bill")
async def add_client_bill(
    company_id: str,
    project_id: str,
    client_bill_id: str,
    data: AddClientBillData,
    current_user=Depends(auth.get_current_user),
) -> dict:
    auth.check_user_data(company_id=company_id, current_user=current_user)

    if (
        data.currentActuals is not None
        and data.currentActualsChangeOrders is not None
        and data.clientBillSummary is None
        and data.invoiceIds is None
        and data.laborIds is None
        and data.clientBillObj is None
    ):
        return_data = await add_client_bill_actuals(
            project_name=PROJECT_NAME,
            collection=company_id,
            project_id=project_id,
            client_bill_id=client_bill_id,
            data=data,
        )

    else:
        return_data = await add_new_client_bill(
            project_name=PROJECT_NAME,
            collection=company_id,
            project_id=project_id,
            client_bill_id=client_bill_id,
            data=data,
        )

    if return_data:
        return return_data
    else:
        return {"message": "Successfully created new client bill."}


class CustomerInfo(BaseModel):
    customerName: str
    customerEmail: str


@router.post("/{company_id}/build-ar-invoice")
async def build_ar_invoice(
    company_id: str,
    project_id: str,
    client_bill_id: str,
    data: CustomerInfo,
    current_user=Depends(auth.get_current_user),
) -> dict:
    auth.check_user_data(company_id=company_id, current_user=current_user)
    customer_name = data.customerName
    customer_email = data.customerEmail

    customer_id = await get_agave_customer_id(
        company_id=company_id,
        customer_name=customer_name,
        customer_email=customer_email,
    )

    if customer_id is None:
        raise HTTPException(
            status_code=404,
            detail=f"No customer ID found for {customer_name} or {customer_email}.",
        )

    if not Config.AGAVE_ACCOUNT_TOKEN:
        # TODO need a way to access which software is being integrated to include in the params for the secret id
        # secret_id = await create_secret_id(company_id)
        secret_id = f"AGAVE_{company_id.upper()}_QBD_ACCOUNT_TOKEN"
        Config.AGAVE_ACCOUNT_TOKEN = await access_secret_version(secret_id=secret_id)

    headers = {
        "API-Version": Config.AGAVE_API_VERSION,
        "accept": "application/json",
        "Client-Id": Config.AGAVE_CLIENT_ID,
        "Client-Secret": Config.AGAVE_CLIENT_SECRET,
        "Account-Token": Config.AGAVE_ACCOUNT_TOKEN,
        "Content-Type": "application/json",
        "Include-Source-Data": "true",
    }

    line_items = await build_ar_invoice_request_data(
        company_id=company_id, project_id=project_id, client_bill_id=client_bill_id
    )

    if line_items is None:
        raise HTTPException(status_code=404, detail="No line_items returned.")

    ar_invoice_data = {
        "customer_id": customer_id,
        "description": "June, 2021 Invoice -- Grant Lakehouse",
        "due_date": "2021-07-15",  # TODO due dates and issued dates need to be defined dynamically!!!
        "issue_date": "2021-06-30",
        "line_items": line_items,
        "number": "1",
    }

    response = requests.post(
        url=AGAVE_AR_INVOICES_URL,
        headers=headers,
        data=json.dumps(ar_invoice_data),
    )

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text,
        )
    else:
        return {"message": "Sucessfully built AR Invoice."}


@router.delete("/{company_id}/delete-client-bills")
async def delete_client_bills(
    company_id: str,
    project_id: str,
    data: List[str],
    background_tasks: BackgroundTasks,
    current_user=Depends(auth.get_current_user),
) -> dict:
    auth.check_user_data(company_id=company_id, current_user=current_user)

    await push_update_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data={"is_deleting_docs": True},
        document="logging",
    )
    # Keep for now, may want to implement some check for the number of invoices
    # or client bills being deleted and not run the background task for a small
    # number of items to be deleted
    # invoice_ids = await get_invoice_ids_from_client_bills(
    #     company_id=company_id, project_id=project_id, client_bill_ids=data
    # )

    # if len(invoice_ids) < 10:
    #     task1 = delete_project_items_from_firestore(
    #         project_name=PROJECT_NAME,
    #         company_id=company_id,
    #         ids=data,
    #         document_name="projects",
    #         project_key=project_id,
    #         doc_collection_names=["client-bills-summary"],
    #     )
    #     task2 = delete_collections_from_firestore(
    #         project_name=PROJECT_NAME,
    #         company_id=company_id,
    #         data=data,
    #         document_name="projects",
    #         collection_name=None,
    #         doc_collection_name=project_id,
    #         doc_collection_doc_name="client-bills",
    #     )

    #     task3 = delete_invoices_from_storage(company_id=company_id, data=invoice_ids)

    #     try:
    #         await asyncio.gather(task1, task2, task3)
    #     except Exception as e:
    #         client_bill_utils_logger.exception(
    #             f"Unexpected error occurred while trying to delete client bills: {e}"
    #         )

    #     if len(data) == 1:
    #         return {"message": f"Successfully deleted {len(data)} client bill."}
    #     else:
    #         return {"message": f"Successfully deleted {len(data)} client bills."}

    background_tasks.add_task(
        delete_client_bill_background,
        company_id=company_id,
        project_id=project_id,
        data=data,
    )

    if len(data) == 1:
        return {"message": f"Successfully deleted {len(data)} client bill."}
    else:
        return {"message": f"Successfully deleted {len(data)} client bills."}
