import asyncio
from fastapi import HTTPException
from config import PROJECT_NAME
from global_vars.globals_io import QBD_INIT_ITEM_TYPE
from utils.data_models.budgets import CostCodes
from utils.data_models.qbd import ItemResponseData, ItemResponseDataData
from utils.database.firestore import push_to_firestore
from utils.database.projects.utils import (
    extract_string,
    format_name_for_id,
    get_data_by_recursive_level,
)
from utils.storage_utils import save_updated_cost_codes_to_gcs


def convert_qbd_to_cost_code(
    items: ItemResponseDataData,
) -> CostCodes:
    data = items.get("data")
    budget = {"format": "", "currency": "USD", "updated": True, "divisions": []}
    level_list = {}

    if not isinstance(data, list):
        raise

    index = 0
    all_sublevels = set()

    for item in data:
        all_sublevels.add(item.get("source_data", {}).get("data", {}).get("Sublevel"))
        if (
            (not item["source_data"]["data"].get("ParentRef"))
            and item["source_data"]["data"]["Sublevel"] == "0"
            and extract_string(item["name"], is_extract_number=True)[1]
        ):
            budget["divisions"].append(
                {
                    "agave_uuid": item["id"],
                    "name": item["name"][item["name"].index(" ") + 1 :],
                    "number": extract_string(item["name"], is_extract_number=True)[0],
                    "subItems": [],
                }
            )
            level_list[item["source_id"]] = [index]
            index += 1

    data = [item for item in data if item["source_data"]["data"]["Sublevel"] != "0"]

    # Get the deepest level to assign the inputType: toggleInput to that level only
    deepest_level = max([int(x) for x in all_sublevels])
    current_level = 1
    while data:
        for item in filter(
            lambda x: x["source_data"]["data"]["Sublevel"] == str(current_level), data
        ):
            cost_code = (
                extract_string(item["name"], is_extract_number=True)[0]
                if extract_string(item["name"], is_extract_number=True)[1]
                else None
            )

            parent_id = item["source_data"]["data"]["ParentRef"]["ListID"]
            parent_level = level_list.get(parent_id)

            if parent_level is None:
                continue

            result = get_data_by_recursive_level(budget["divisions"], parent_level)

            if not result:
                continue

            if not result.get("subItems"):
                result["subItems"] = []

            if result.get("isCurrency"):
                result["isCurrency"] = False
                result["value"] = "0.00"

            level_list[item["source_id"]] = [*parent_level, len(result["subItems"])]

            result["subItems"] = [
                *result["subItems"],
                {
                    "agave_uuid": item["id"],
                    "name": extract_string(item["name"], is_extract_number=False),
                    "number": cost_code,
                    "subItems": [],
                    "isCurrency": True,
                    "type": "text",
                    "inputType": "toggleInput"
                    if current_level == deepest_level
                    else "",
                    "id": cost_code
                    if cost_code is not None
                    else format_name_for_id(
                        extract_string(item["name"], is_extract_number=False)
                    ),
                    "value": "",
                },
            ]

        data = [
            item
            for item in data
            if item["source_data"]["data"]["Sublevel"] != str(current_level)
        ]
        current_level += 1

    return budget


async def create_and_push_init_cost_codes(
    items: ItemResponseData, company_id: str
) -> CostCodes:
    for url, status, data in items:
        item_type = url.split("type=")[-1]
        if item_type != QBD_INIT_ITEM_TYPE:
            continue
        # create cost codes
        if status != 200:
            raise HTTPException(
                status_code=status,
                detail="The Service Item type from Quickbooks was not synced properly.",
            )

        init_cost_codes_dict = convert_qbd_to_cost_code(items=data)

        task1 = push_to_firestore(
            project_name=PROJECT_NAME,
            collection=company_id,
            document="cost-codes",
            data=init_cost_codes_dict,
            overwrite_data=True,
        )
        task2 = save_updated_cost_codes_to_gcs(
            company_id=company_id,
            data=init_cost_codes_dict,
            bucket="stak-customer-cost-codes",
        )
    _ = await asyncio.gather(task1, task2)

    return init_cost_codes_dict
