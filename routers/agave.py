import requests
import json

from fastapi import APIRouter, Depends
from config import Config


from utils import auth
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
        return {
            "error": "Agave account token not received.",
            "status": response.status_code,
        }
    else:
        data = json.loads(response.content)
        # use this to signify a specific company file
        # a single customer can have multuple company files and each will have a unique id.
        company_ein = data["connection"]["properties"]["company_ein"].replace("-", "")
        account_token = data["account_token"]

    # TODO this needs to expand to other software choices in the future
    if software_name.lower() == "quickbooks desktop":
        software_id = "qbd"

    secret_id = f"AGAVE_{company_id.upper()}_{software_id.upper()}_ACCOUNT_TOKEN"

    create_secret(
        secret_id=secret_id,
        value=account_token,
    )

    return {"message": "Account token retrieved and saved to google secrets."}
