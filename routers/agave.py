import asyncio
import traceback
import requests
import json

from fastapi import APIRouter, Depends, HTTPException
from google.api_core.exceptions import AlreadyExists

from config import PROJECT_NAME, Config
from global_vars.globals_io import (
    AGAVE_CUSTOMERS_URL,
    AGAVE_EMPLOYEES_URL,
    AGAVE_VENDORS_URL,
)
from utils import auth
from utils.agave_utils import ingest_qbd_data, ingest_qbd_items
from utils.database.firestore import (
    push_qbd_data_to_firestore,
    push_qbd_items_data_to_firestore,
)
from utils.io_utils import create_secret


router = APIRouter()


@router.put("/{company_id}/agave-account-token")
async def get_and_save_agave_account_token(
    company_id: str,
    public_token: str,
    software_name: str,
    current_user=Depends(auth.get_current_user),
):
    auth.check_user_data(company_id=company_id, current_user=current_user)

    headers = {
        "API-Version": Config.AGAVE_API_VERSION,
        "Client-Id": Config.AGAVE_CLIENT_ID,
        "Client-Secret": Config.AGAVE_CLIENT_SECRET,
    }

    response = requests.post(
        url=Config.AGAVE_TOKEN_EXCHANGE_URL,
        json={"public_token": public_token},
        headers=headers,
    )

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code, detail="Agave account token not received."
        )
    else:
        data = json.loads(response.content)
        # use this to signify a specific company file
        # a single customer can have multuple company files and each will have a unique id.
        company_ein = data["connection"]["properties"]["company_ein"].replace("-", "")
        account_token = data["account_token"]

    # TODO this needs to expand to other software choices in the future
    if software_name.lower() == "quickbooks desktop":
        software_id = "qbd"

    # TODO debug why I stopped uising the ein from the company....i think there was a reason but can't remember
    secret_id = f"AGAVE_{company_id.upper()}_{software_id.upper()}_ACCOUNT_TOKEN"

    try:
        create_secret(
            secret_id=secret_id,
            value=account_token,
        )
    except AlreadyExists:
        raise HTTPException(status_code=500, detail="The secret id already exists.")

    try:
        # Once the account token has been created and saved, ingest all Quickbooks data.
        init_qbd_items_data = ingest_qbd_items(account_token)
        init_qbd_customers = ingest_qbd_data(
            url=AGAVE_CUSTOMERS_URL, account_token=account_token
        )
        init_qbd_vendors = ingest_qbd_data(
            url=AGAVE_VENDORS_URL, account_token=account_token
        )
        init_qbd_employees = ingest_qbd_data(
            url=AGAVE_EMPLOYEES_URL, account_token=account_token
        )
        items, customers, employees, vendors = await asyncio.gather(
            init_qbd_items_data,
            init_qbd_customers,
            init_qbd_employees,
            init_qbd_vendors,
        )

        # save all data to firestore
        if items:
            push_items = push_qbd_items_data_to_firestore(
                project_name=PROJECT_NAME,
                collection=company_id,
                document="quickbooks-desktop-data",
                items_data=items,
            )
        if customers:
            push_customers = push_qbd_data_to_firestore(
                project_name=PROJECT_NAME,
                collection=company_id,
                document="quickbooks-desktop-data",
                doc_collection="customers",
                data=customers,
            )
        if employees:
            push_employees = push_qbd_data_to_firestore(
                project_name=PROJECT_NAME,
                collection=company_id,
                document="quickbooks-desktop-data",
                doc_collection="employees",
                data=employees,
            )
        if vendors:
            push_vendors = push_qbd_data_to_firestore(
                project_name=PROJECT_NAME,
                collection=company_id,
                document="quickbooks-desktop-data",
                doc_collection="vendors",
                data=vendors,
            )
        _ = await asyncio.gather(
            push_items, push_customers, push_employees, push_vendors
        )

    except Exception as e:
        print(e)
        print(traceback.print_exc)
        return {
            "message": "Account token saved but error ingesting data. Please manually ingest the data."
        }

    return json.dumps(
        {
            "message": "Account token saved and all data ingested.",
            "items": items,
            "customers": customers,
            "employees": employees,
            "vendors": vendors,
        }
    )
