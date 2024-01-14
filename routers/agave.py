import asyncio
import traceback
import requests
import json

from fastapi import APIRouter, Depends, HTTPException
from google.api_core.exceptions import AlreadyExists


from config import Config
from utils import auth
from utils.agave_utils import (
    init_ingest_all_qbd_data,
)
from utils.io_utils import create_secret


router = APIRouter()


@router.put("/{company_id}/agave-account-token")
async def get_and_save_agave_account_token(
    company_id: str,
    public_token: str,
    software_name: str,
    # current_user=Depends(auth.get_current_user),
) -> dict:
    # auth.check_user_data(company_id=company_id, current_user=current_user)

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
    secret_id = (
        f"AGAVE_{company_id.upper()}_{company_ein}_{software_id.upper()}_ACCOUNT_TOKEN"
    )

    try:
        create_secret(
            secret_id=secret_id,
            value=account_token,
        )
    except AlreadyExists:
        raise HTTPException(status_code=500, detail="The secret id already exists.")

    # This ingests all data from QBD and then saves it to the cutomers Firestore collection
    result = await init_ingest_all_qbd_data(
        # company_id=company_id, account_token=account_token
        company_id=company_id,
        account_token=None,
    )

    return result

