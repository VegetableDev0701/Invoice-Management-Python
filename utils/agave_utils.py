import asyncio
import json
import logging
import re
import sys
import traceback
from typing import Awaitable, Dict, List, Tuple
import aiohttp
import requests

from fastapi import HTTPException
from tenacity import (
    retry_if_exception_type,
    wait_exponential_jitter,
    stop_after_attempt,
    AsyncRetrying,
    RetryError,
    before_sleep_log,
)

from global_vars.globals_io import (
    AGAVE_CUSTOMERS_URL,
    AGAVE_EMPLOYEES_URL,
    AGAVE_PASSTHROUGH_URL,
    AGAVE_VENDORS_URL,
    BATCH_SIZE_CUTOFF,
    QBD_ITEM_TYPES,
)
from utils.cost_code_utils import create_and_push_init_cost_codes
from utils.data_models.qbd import ItemResponseData, VendorResponseData
from utils.data_models.vendors import SummaryVendorData
from utils.database.firestore import (
    get_all_project_details_data,
    get_from_firestore,
    push_qbd_data_to_firestore,
    push_qbd_data_to_firestore_batched,
    push_qbd_items_data_to_firestore,
    push_to_firestore,
    stream_all_docs_from_collection,
)
from utils.io_utils import (
    access_secret_version,
    create_short_uuid,
    request_async_delete,
    request_async_get,
    request_async_post,
    run_async_coroutine,
)
from config import PROJECT_NAME, Config
from utils.retry_utils import RETRYABLE_EXCEPTIONS
from utils.vendor_utils import add_vendors_wrapper, get_company_lookup_dict

# Create a logger
agave_utils_logger = logging.getLogger("error_logger")
agave_utils_logger.setLevel(logging.DEBUG)

try:
    # Create a file handler
    handler = logging.FileHandler(
        "/Users/mgrant/STAK/app/stak-backend/api/logs/agave_utils_logs.log"
    )
except Exception as e:
    print(e)
    handler = logging.StreamHandler(sys.stdout)

handler.setLevel(logging.DEBUG)

# Create a logging format
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)

# Add the handlers to the logger
agave_utils_logger.addHandler(handler)


def get_headers(account_token: str | None = None, is_passthrough: bool = False):
    headers = {
        "API-Version": Config.AGAVE_API_VERSION,
        "accept": "application/json",
        "Client-Id": Config.AGAVE_CLIENT_ID,
        "Client-Secret": Config.AGAVE_CLIENT_SECRET,
        "Account-Token": f"{account_token if account_token else Config.AGAVE_ACCOUNT_TOKEN}",
        "Content-Type": "application/json" if not is_passthrough else "text/xml",
        "Include-Source-Data": "true",
    }

    return headers


async def get_all_vendors_from_agave(
    company_id: str, account_token: str | None = None
) -> Dict[str, Dict[str, List[dict] | dict]]:
    if not Config.AGAVE_ACCOUNT_TOKEN and not account_token:
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

    response = requests.get(
        AGAVE_VENDORS_URL, headers=get_headers(account_token=account_token)
    )
    response_extra = requests.post(
        AGAVE_PASSTHROUGH_URL,
        data=data,
        headers=get_headers(account_token=account_token, is_passthrough=True),
    )
    response_message_dict = response.json()
    if response.status_code != 200 or response_extra.status_code != 200:
        if response_message_dict.get("error"):
            message = response_message_dict["error"]
        else:
            message = list(response_message_dict.values())[0]
        raise HTTPException(status_code=response.status_code, detail=message)

    response_dict: Dict[str, List[dict] | dict] = json.loads(response.content)
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


def find_unique_entries(
    response_dict: Dict[str, List[dict] | dict],
    current_vendors_dict: Dict[str, Dict[str, dict]],
) -> Dict[str, List[dict]]:
    """
    Return only the unique values in the first dict by comparing to the second.

    Params:
        response_dict: this is the response dictionary for getting vendors from agave
        current_vendors_dict: the vendor-summary for all vendors currently in teh db
    """
    # Extract the list from 'data' key in the first dictionary
    first_list: List[dict] | list = response_dict.get("data", [])

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
    all_vendors = await stream_all_docs_from_collection(
        project_name=PROJECT_NAME,
        company_id=company_id,
        document_name="quickbooks-desktop-data",
        collection_name="vendors",
    )
    vendors_list = [vendor for vendor in all_vendors.values()]

    # traverse all vendors and pick out all unique names used
    unique_data_ext_names = set(
        data_ext["DataExtName"]
        for item in vendors_list
        if "source_data" in item
        and "data" in item["source_data"]
        and "DataExtRet" in item["source_data"]["data"]
        for data_ext in item["source_data"]["data"]["DataExtRet"]
        if "DataExtName" in data_ext
    )

    company_lookup_dict = await get_company_lookup_dict(
        company_id=company_id, unique_data_ext_names=unique_data_ext_names
    )

    full_xml_parts = []

    for list_id in vendor_list_id:
        for ext_name in unique_data_ext_names:
            key = company_lookup_dict.get(ext_name, [None])[0]
            value = vendor_summary.get(key)
            if value == "" or value is None:
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
            url=AGAVE_PASSTHROUGH_URL,
            payloads=full_xml_parts,
            headers=get_headers(is_passthrough=True),
        )
    )


async def add_vendors_to_qbd(
    new_vendor_summary: dict,
    company_id: str,
    is_update: bool = False,
    initial: int = 10,
    jitter: int = 10,
) -> str | dict | None:
    """
    Create and add/update vendors to QBD via Agave API.

    params:
        vendor_summary: dict
        company_id: str
        id_update: bool - if the vendor should be updated in qbd or added
    """
    # first add via standard api
    try:
        req_body = create_standard_req(new_vendor_summary)
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(2),
            wait=wait_exponential_jitter(initial=initial, jitter=jitter),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(agave_utils_logger, logging.DEBUG),
        ):
            with attempt:
                if is_update:
                    response = requests.put(
                        f"{AGAVE_VENDORS_URL}/{new_vendor_summary.get('agave_uuid')}",
                        headers=get_headers(),
                        json=req_body,
                    )
                else:
                    response = requests.post(
                        AGAVE_VENDORS_URL, headers=get_headers(), json=req_body
                    )

                response_dict = json.loads(response.content)

                if response_dict.get("message") and (
                    "already exists" in response_dict.get("message")
                    or "offline" in response_dict.get("message")
                ):
                    return response_dict

                if response.status_code != 200:
                    raise HTTPException(
                        status_code=response.status_code,
                        detail=f"Error in response from {AGAVE_VENDORS_URL}",
                    )

                list_id, agave_uuid = response_dict.get("source_id"), response_dict.get(
                    "id"
                )

                if list_id:
                    await add_custom_fields(
                        vendor_summary=new_vendor_summary,
                        company_id=company_id,
                        vendor_list_id=[list_id],
                    )
                if agave_uuid:
                    return agave_uuid
                else:
                    return None

    except RetryError as e:
        agave_utils_logger.error(
            f"{e} occured while posting via the add_vendors_to_qbd function."
        )
        traceback.print_exc()
    except Exception as e:
        agave_utils_logger.exception(
            f"An error occured while posting data to qbd via agave in the add_vendors_to_qbd function: {e}"
        )
        traceback.print_exc()


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
        traceback.print_exc()
        return {
            "message_agave_error": "The server disconnected. You may not have Quickbooks running and the Web Connector turned on. Please refresh your browser and try and delete these Vendors again."
        }
    except Exception as e:
        print(e)
        traceback.print_exc()
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
        request_async_get(urls=urls, headers=get_headers(account_token))
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
        traceback.print_exc()


def create_employee_return_dict(employees: Dict) -> list:
    return_dict = {}
    for employee in employees["data"]:
        uuid = create_short_uuid()
        return_dict[uuid] = {
            "name": re.sub(r"{owner}", "", employee.get("full_name")).strip(),
            "agave_uuid": employee.get("id"),
            "uuid": create_short_uuid(),
        }
    return return_dict


def create_customer_return_dict(customers: Dict) -> list:
    return_dict = {}
    for customer in customers["data"]:
        uuid = create_short_uuid()
        return_dict[uuid] = {
            "name": customer.get("name"),
            "agave_uuid": customer.get("id"),
            "sub_level": int(customer["source_data"]["data"].get("Sublevel")),
            "email": customer.get("email"),
            "phone": customer.get("phone"),
            "uuid": uuid,
        }
    return return_dict


async def init_ingest_all_qbd_data(
    company_id: str, account_token: str | None = None
) -> Dict:
    try:
        # Once the account token has been created and saved, ingest all Quickbooks data.
        init_qbd_items_data: Awaitable[ItemResponseData] = ingest_qbd_items(
            account_token=account_token
        )
        init_qbd_customers: Awaitable[Dict[str, List[Dict] | Dict]] = ingest_qbd_data(
            url=AGAVE_CUSTOMERS_URL, account_token=account_token
        )
        init_qbd_vendors: Awaitable[VendorResponseData] = get_all_vendors_from_agave(
            company_id=company_id, account_token=account_token
        )
        init_qbd_employees: Awaitable[Dict[str, List[Dict] | Dict]] = ingest_qbd_data(
            url=AGAVE_EMPLOYEES_URL, account_token=account_token
        )
        items, customers, employees, vendors = await asyncio.gather(
            init_qbd_items_data,
            init_qbd_customers,
            init_qbd_employees,
            init_qbd_vendors,
        )

        # The current vendors should always be zero since this will be happening early
        # but it is not impossible that they have some vendors manually added so run this check

        current_vendors_dict = await get_all_project_details_data(
            project_name=PROJECT_NAME,
            collection_name=company_id,
            document_name="vendors",
            doc_names="vendor-summary",
        )

        new_vendors = find_unique_entries(vendors, current_vendors_dict)

        push_tasks = []
        create_tasks = []
        # save all data to firestore
        if items:
            push_tasks.append(
                asyncio.create_task(
                    push_qbd_items_data_to_firestore(
                        project_name=PROJECT_NAME,
                        collection=company_id,
                        document="quickbooks-desktop-data",
                        items_data=items,
                    )
                )
            )
            # create the cost codes json object from items
            create_tasks.append(
                asyncio.create_task(
                    create_and_push_init_cost_codes(items=items, company_id=company_id)
                )
            )

        if customers:
            push_func = (
                push_qbd_data_to_firestore_batched
                if len(customers["data"]) > BATCH_SIZE_CUTOFF
                else push_qbd_data_to_firestore
            )
            push_tasks.append(
                asyncio.create_task(
                    push_func(
                        project_name=PROJECT_NAME,
                        collection=company_id,
                        document="quickbooks-desktop-data",
                        doc_collection="customers",
                        data=customers,
                    )
                )
            )

        if employees:
            push_func = (
                push_qbd_data_to_firestore_batched
                if len(employees["data"]) > BATCH_SIZE_CUTOFF
                else push_qbd_data_to_firestore
            )
            push_tasks.append(
                asyncio.create_task(
                    push_func(
                        project_name=PROJECT_NAME,
                        collection=company_id,
                        document="quickbooks-desktop-data",
                        doc_collection="employees",
                        data=employees,
                    )
                )
            )
            # TODO create a minimal flat employees dict/object to send to FE
        if new_vendors:
            push_func = (
                push_qbd_data_to_firestore_batched
                if len(new_vendors["data"]) > BATCH_SIZE_CUTOFF
                else push_qbd_data_to_firestore
            )
            push_tasks.append(
                asyncio.create_task(
                    push_func(
                        project_name=PROJECT_NAME,
                        collection=company_id,
                        document="quickbooks-desktop-data",
                        doc_collection="vendors",
                        data=new_vendors,
                    )
                )
            )
            # create the vendor data to return
            unique_data_ext_names = set(
                data_ext["DataExtName"]
                for item in vendors[
                    "data"
                ]  # still take all vendors to create this list
                if "source_data" in item
                and "data" in item["source_data"]
                and "DataExtRet" in item["source_data"]["data"]
                for data_ext in item["source_data"]["data"]["DataExtRet"]
                if "DataExtName" in data_ext
            )
            create_tasks.append(
                asyncio.create_task(
                    add_vendors_wrapper(
                        company_id=company_id,
                        new_vendors_to_add=new_vendors,
                        unique_data_ext_names=unique_data_ext_names,
                    )
                )
            )
        # push everything to the quickbooks-desktop-data document
        _ = await asyncio.gather(*push_tasks)

        init_cost_codes_dict, vendor_data_to_add_to_firestore, update_doc_dict = (
            None,
            None,
            None,
        )
        if create_tasks:
            init_cost_codes_dict, (
                vendor_data_to_add_to_firestore,
                update_doc_dict,
            ) = await asyncio.gather(*create_tasks)

        return_customer_dict = (
            create_customer_return_dict(customers) if customers else None
        )
        return_employee_dict = (
            create_employee_return_dict(employees) if employees else None
        )
        push_tasks = []
        if return_customer_dict:
            push_tasks.append(
                asyncio.create_task(
                    push_to_firestore(
                        project_name=PROJECT_NAME,
                        collection=company_id,
                        document="customers",
                        data=return_customer_dict,
                    ),
                )
            )
        if return_employee_dict:
            push_tasks.append(
                asyncio.create_task(
                    push_to_firestore(
                        project_name=PROJECT_NAME,
                        collection=company_id,
                        document="employees",
                        data=return_customer_dict,
                    ),
                )
            )
        _ = await asyncio.gather(*push_tasks)

        return {
            "message": "Account token and data saved succesfully.",
            "items": init_cost_codes_dict,
            "customers": return_customer_dict,
            "employees": return_employee_dict,
            "agave_response_data": vendor_data_to_add_to_firestore["summaryData"],
            "update_doc_data": update_doc_dict,
        }

    except Exception as e:
        print(e)
        traceback.print_exc()
        return {
            "message": "Account token saved but error ingesting data. Please manually ingest the data."
        }
