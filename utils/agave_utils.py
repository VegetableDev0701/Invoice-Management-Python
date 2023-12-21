import asyncio
import json
import os

import traceback
from typing import Dict, Tuple
import aiohttp

from fastapi import HTTPException
import requests
from global_vars.globals_io import (
    AGAVE_PASSTHROUGH_URL,
    AGAVE_VENDORS_URL,
    QBD_ITEM_TYPES,
)
from global_vars.globals_vendors import QBD_CUSTOM_FIELDS_LOOKUP
from utils.data_models.vendors import SummaryVendorData
from utils.database.firestore import get_from_firestore, push_to_firestore
from utils.io_utils import (
    access_secret_version,
    request_async_delete,
    request_async_get,
    request_async_post,
    run_async_coroutine,
)

from config import PROJECT_NAME, Config


def get_headers(account_token: str | None = None):
    headers = {
        "API-Version": Config.AGAVE_API_VERSION,
        "accept": "application/json",
        "Client-Id": Config.AGAVE_CLIENT_ID,
        "Client-Secret": Config.AGAVE_CLIENT_SECRET,
        "Account-Token": f"{account_token if account_token else Config.AGAVE_ACCOUNT_TOKEN}",
        "Content-Type": "application/json",
        "Include-Source-Data": "true",
    }

    return headers


async def get_all_vendors_from_agave(company_id: str) -> Dict[str, str]:
    if not Config.AGAVE_ACCOUNT_TOKEN:
        # TODO need a way to access which software is being integrated to include in the params for the secret id
        # secret_id = await create_secret_id(company_id)
        secret_id = f"AGAVE_{company_id.upper()}_QBD_ACCOUNT_TOKEN"
        Config.AGAVE_ACCOUNT_TOKEN = await access_secret_version(secret_id=secret_id)

    data = b"""<?xml version="1.0" encoding="utf-8"?>
    <?qbxml version="16.0"?>
    <QBXML>
        <QBXMLMsgsRq onError="stopOnError">
            <VendorQueryRq>
                <OwnerID>0</OwnerID>
            </VendorQueryRq>
        </QBXMLMsgsRq>
    </QBXML>"""

    headers = get_headers()

    response = requests.get(AGAVE_VENDORS_URL, headers=headers)
    response_extra = requests.post(AGAVE_PASSTHROUGH_URL, data=data, headers=headers)
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


def create_standard_req(vendor_summary: dict) -> Tuple[dict, dict]:
    """
    Need to create the standard dictionary to post a new vendor and the
    passthrough QBXML request body.
    """
    return {
        "address": {
            "street_1": vendor_summary.get("address"),
            "city": vendor_summary.get("city"),
            "state": vendor_summary.get("state"),
            "country": "US",
            "postal_code": vendor_summary.get("zipCode"),
        },
        "email": vendor_summary.get("email"),
        "fax": vendor_summary.get("fax"),
        "name": vendor_summary.get("vendorName"),
        "phone": vendor_summary.get("workPhone") or vendor_summary.get("cellPhone"),
        "tax_number": vendor_summary.get("taxNumber"),
    }


async def add_custom_fields(
    vendor_summary: dict, company_id: str, vendor_list_id: list[str]
):
    vendors_dict = await get_from_firestore(
        project_name=PROJECT_NAME,
        collection_name=company_id,
        document_name="quickbooks-desktop-data",
        doc_collection="vendors",
        doc_collection_document="vendors",
    )

    # traverse all vendors and pick out all unique names used
    unique_data_ext_names = set(
        data_ext["DataExtName"]
        for item in vendors_dict["data"]
        if "source_data" in item
        and "data" in item["source_data"]
        and "DataExtRet" in item["source_data"]["data"]
        for data_ext in item["source_data"]["data"]["DataExtRet"]
        if "DataExtName" in data_ext
    )

    full_xml_parts = []

    for list_id in vendor_list_id:
        for ext_name in unique_data_ext_names:
            value = vendor_summary.get(
                QBD_CUSTOM_FIELDS_LOOKUP.get(company_id).get(ext_name)
            )
            if value is None:
                continue
            full_xml_parts.append(
                f"""
                <QBXML>
                <QBXMLMsgsRq onError="stopOnError">
                    <DataExtModRq>
                        <DataExtMod>
                            <OwnerID>0</OwnerID>
                            <DataExtName>{ext_name}</DataExtName>
                            <ListDataExtType>Vendor</ListDataExtType>
                            <ListObjRef>
                                <ListID>{list_id}</ListID>
                            </ListObjRef>
                            <DataExtValue>{value}</DataExtValue>
                        </DataExtMod>
                    </DataExtModRq>
                </QBXMLMsgsRq>
                </QBXML>
                """
            )
    _ = await run_async_coroutine(
        request_async_post(
            url=AGAVE_PASSTHROUGH_URL, payloads=full_xml_parts, headers=get_headers()
        )
    )


async def add_vendors_to_qbd(
    vendor_summary: dict, company_id: str, is_update: bool = False
) -> str | dict | None:
    """
    Create and add/update vendors to QBD via Agave API.

    params:
        vendor_summary: dict
        company_id: str
        id_update: bool - if the vendor should be updated in qbd or added
    """
    # first add via standard api
    req_body = create_standard_req(vendor_summary)
    if is_update:
        response = requests.put(
            f"{AGAVE_VENDORS_URL}/{vendor_summary.get('agave_uuid')}",
            headers=get_headers(),
            json=req_body,
        )
    else:
        response = requests.post(
            AGAVE_VENDORS_URL, headers=get_headers(), json=req_body
        )
    # TODO add error handling. If this doesn't work retry 3 times then quit and return null for agave_uuid
    response_dict = json.loads(response.content)

    if response_dict.get("message") and (
        "already exists" in response_dict.get("message")
        or "offline" in response_dict.get("message")
    ):
        return response_dict

    list_id, agave_uuid = response_dict.get("source_id"), response_dict.get("id")

    if list_id:
        await add_custom_fields(
            vendor_summary=vendor_summary,
            company_id=company_id,
            vendor_list_id=[list_id],
        )
    if agave_uuid:
        return agave_uuid
    else:
        return None


async def handle_qbd_response(
    qbd_response: dict | str | None,
    company_id: str,
    summary_data: SummaryVendorData,
    is_sync: bool = False,
) -> dict:
    if isinstance(qbd_response, dict):
        if "already exists" in qbd_response["message"]:
            return {
                "message": qbd_response["message"][:-1]
                + " in Quickbooks. Successfully saved vendor to Stak."
            }
        else:
            return qbd_response

    # returns a string of the agave_uuid which needs to be added to the vendor summary and
    # uploaded to firestore
    if isinstance(qbd_response, str):
        # update firestore with agave_uuid
        agave_uuid = qbd_response
        updated_summary_data = summary_data.dict().copy()
        updated_summary_data.update({"agave_uuid": agave_uuid})
        await push_to_firestore(
            project_name=PROJECT_NAME,
            collection=company_id,
            data=updated_summary_data,
            document="vendors",
            doc_collection=summary_data.uuid,
            doc_collection_document="vendor-summary",
        )

        return {
            "message": f"Successfully {'synced' if is_sync else 'added'} new vendor.",
            "agave_uuid": agave_uuid,
            "uuid": summary_data.uuid,
        }
    return {
        "message": "Successfully added new vendor to Stak, but there was a problem adding to Quickbooks."
    }


async def get_agave_uuid_from_vendor_id(
    vendor_ids: [str],
    project_name: str,
    company_id: str,
    document_name: str,
):
    """
    Function to traverse the vendor collection and delete the vendor from QBD via agave API.
    """

    tasks = [
        get_from_firestore(
            project_name=project_name,
            collection_name=company_id,
            document_name=document_name,
            doc_collection=vendor_id,
            doc_collection_document="vendor-summary",
        )
        for vendor_id in vendor_ids
    ]

    agave_uuids = [vendor["agave_uuid"] for vendor in await asyncio.gather(*tasks)]

    return agave_uuids


async def delete_vendors_from_qbd(agave_uuids: [str], vendor_ids: [str]):
    try:
        result = await run_async_coroutine(
            request_async_delete(
                url=AGAVE_VENDORS_URL, ids=agave_uuids, headers=get_headers()
            )
        )
    except aiohttp.client_exceptions.ServerDisconnectedError as e:
        print(traceback.print_exc)
        return {
            "message_agave_error": "The server disconnected. You may not have Quickbooks running and the Web Connector turned on. Please refresh your browser and try and delete these Vendors again."
        }
    except Exception as e:
        print(e)
        print(traceback.print_exc)
        return {
            "message_agave_error": f"Error: {e}. You may not have Quickbooks running and the Web Connector turned on. Please refresh your browser and try and delete these Vendors again."
        }

    # handle the response
    if all([res == 200 for res in result]):
        return {"message_agave_success": "All vendors deleted from QBD."}
    elif all([res != 200 for res in result]):
        return {
            "message_agave_offline": "Stak is having trouble connecting to QBD, it may be offline."
        }
    else:
        uuid_with_error = [
            uuid for (res, uuid) in zip(result, vendor_ids) if res != 200
        ]
        return {
            "message_agave_some": f"The following vendors were not deleted from QBD: {uuid_with_error}"
        }


async def ingest_qbd_items(account_token: str | None = None):
    """
    Ingest QBD items. Items require a type query to collect different item types.
    """

    urls = ["https://api.agaveapi.com/items" + f"?type={typ}" for typ in QBD_ITEM_TYPES]

    result = await run_async_coroutine(
        request_async_get(urls=urls, headers=get_headers(account_token=account_token))
    )
    return result


async def ingest_qbd_data(url: str, account_token: str | None = None):
    """
    Ingest QBD data that doesn't require special type queries. This includes:
        * employees
        * customers
        * vendors
    """
    try:
        response = requests.get(url, headers=get_headers(account_token))
        data = json.loads(response.text)
        return data
    except Exception as e:
        print(e)
        print(traceback.print_exc)
        raise
