import json
from typing import Dict

from fastapi import HTTPException
import requests
from utils.io_utils import access_secret_version

from config import Config


async def get_all_vendors_from_agave(company_id: str) -> Dict[str, str]:
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

    url = "https://api.agaveapi.com/vendors"
    url_extra = "https://api.agaveapi.com/passthrough"

    data = b"""<?xml version="1.0" encoding="utf-8"?>
    <?qbxml version="16.0"?>
    <QBXML>
        <QBXMLMsgsRq onError="stopOnError">
            <VendorQueryRq>
                <OwnerID>0</OwnerID>
            </VendorQueryRq>
        </QBXMLMsgsRq>
    </QBXML>"""

    response = requests.get(url, headers=headers)
    response_extra = requests.post(url_extra, data=data, headers=headers)
    response_message_dict = response.json()
    if response.status_code != 200 or response_extra.status_code != 200:
        if response_message_dict.get("error"):
            message = response_message_dict["error"]
        else:
            message = list(response_message_dict.values())[0]
        raise HTTPException(status_code=response.status_code, detail=message)

    response_dict: Dict[str, dict] = json.loads(response.content)
    response_extra_dict: Dict[str, dict] = json.loads(response_extra.content)

    lookup_dict = {
        item["ListID"]: item for item in response_extra_dict["body"]["VendorRet"]
    }
    for item in response_dict["data"]:
        # Extract ListID from the item's source_data
        list_id = item["source_data"]["data"]["ListID"]

        # Check if this ListID is in lookup_dict
        if list_id in lookup_dict:
            # Extend the item with data from lookup_dict
            item["source_data"]["data"] = lookup_dict[list_id]

    return response_dict


def find_unique_entries(response_dict, current_vendors_dict):
    """
    Return only the unique values in the first dict by comparing to the second.

    Params:
        response_dict: this is the response dictionary for getting vendors from agave
        current_vendors_dict: the vendor-summary for all vendors currently in teh db
    """
    # Extract the list from 'data' key in the first dictionary
    first_list = response_dict.get("data", [])

    # Create a set of 'agave_uuid' values from the second dictionary
    agave_uuids = {
        info["vendor-summary"]["agave_uuid"]
        for _, info in current_vendors_dict.items()
        if "vendor-summary" in info and "agave_uuid" in info["vendor-summary"]
    }

    # Find items from the first list whose 'id' is not in the set of agave_uuids
    unique_entries = [item for item in first_list if item["id"] not in agave_uuids]

    return {"data": unique_entries}


# def add_vendors_to_agave()
