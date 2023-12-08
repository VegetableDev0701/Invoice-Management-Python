from typing import Any, Dict
import logging
import sys

from google.cloud import firestore
from tenacity import (
    retry_if_exception_type,
    wait_exponential_jitter,
    stop_after_attempt,
    AsyncRetrying,
    RetryError,
    before_sleep_log,
)

from utils.retry_utils import RETRYABLE_EXCEPTIONS
from config import PROJECT_NAME
from global_vars.globals_io import RETRY_TIMES
from config import PROJECT_NAME

# Create a logger
ar_invoice_logger = logging.getLogger("error_logger")
ar_invoice_logger.setLevel(logging.DEBUG)

# Create a file handler
# handler = logging.FileHandler(
#     "/Users/mgrant/STAK/app/stak-backend/api/logs/firestore_read_write_error_logs.log"
# )

handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)

# Create a logging format
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)

# Add the handlers to the logger
ar_invoice_logger.addHandler(handler)


async def get_agave_customer_id(
    company_id: str, customer_name: str, customer_email: str
):
    db = firestore.AsyncClient(project=PROJECT_NAME)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(ar_invoice_logger, logging.DEBUG),
        ):
            with attempt:
                qbd_customer_ref = (
                    db.collection(company_id)
                    .document("quickbooks-desktop-data")
                    .collection("customers")
                    .document("customers")
                )
                doc = await qbd_customer_ref.get()
                if not doc.exists:
                    return None
                customers = doc.to_dict()["data"]
                for customer in customers:
                    if (
                        customer["name"] == customer_name
                        or customer["email"] == customer_email
                    ):
                        return customer["id"]
                return None
    except RetryError as e:
        ar_invoice_logger.error(
            f"{e} occured while trying to get Agave customer ID for AR Invoice."
        )
        raise
    except Exception as e:
        ar_invoice_logger.exception(
            f"Unexpected error occurred while trying to get Agave customer ID for AR Invoice: {e}"
        )
        raise
    finally:
        db.close()


async def build_ar_invoice_request_data(
    company_id: str, project_id: str, client_bill_id: str
):
    db = firestore.AsyncClient(project=PROJECT_NAME)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(ar_invoice_logger, logging.DEBUG),
        ):
            with attempt:
                qbd_ref = (
                    db.collection(company_id)
                    .document("quickbooks-desktop-data")
                    .collection("items")
                    .document("items")
                )
                work_description_ref = (
                    db.collection(company_id)
                    .document("projects")
                    .collection(project_id)
                    .document("client-bills")
                    .collection(client_bill_id)
                    .document("bill-work-description")
                )
                current_actuals_ref = (
                    db.collection(company_id)
                    .document("projects")
                    .collection(project_id)
                    .document("client-bills")
                    .collection(client_bill_id)
                    .document("current-actuals")
                )
                # client_bill_summary_ref = (
                #     db.collection(company_id)
                #     .document("projects")
                #     .collection(project_id)
                #     .document("client-bills-summary")
                # )
                change_order_summary_ref = (
                    db.collection(company_id)
                    .document("projects")
                    .collection(project_id)
                    .document("change-orders-summary")
                )

                qbd_doc = await qbd_ref.get()
                if not qbd_doc.exists:
                    return None
                items = qbd_doc.to_dict()["data"]

                work_description_doc = await work_description_ref.get()
                if not work_description_doc.exists:
                    return None
                work_description = work_description_doc.to_dict()

                # client_bill_summary_doc = await client_bill_summary_ref.get()
                # if not client_bill_summary_doc.exists:
                #     return None
                # client_bill_summary = client_bill_summary_doc.to_dict()[client_bill_id]

                current_actuals_doc = await current_actuals_ref.get()
                if not current_actuals_doc.exists:
                    return None

                change_order_summary_doc = await change_order_summary_ref.get()
                if not change_order_summary_doc.exists:
                    change_order_summary = None
                else:
                    change_order_summary = change_order_summary_doc.to_dict()

                # arbirtray code codes for profit, liability and taxes
                keys = ["0.1100", "0.1200", "0.1300", "0.1400"]
                current_actuals = current_actuals_doc.to_dict()

                # budgeted
                subtotals = {
                    "budgeted": {
                        key: current_actuals["currentActuals"][key]
                        for key in keys
                        if key in current_actuals["currentActuals"]
                    }
                }
                subtotals["changeOrders"] = {}

                for change_order_id in current_actuals[
                    "currentActualsChangeOrders"
                ].keys():
                    if change_order_id == "profitTaxesLiability":
                        continue

                    subtotals["changeOrders"].update(
                        {
                            change_order_id: {
                                key: current_actuals["currentActualsChangeOrders"][
                                    change_order_id
                                ][key]
                                for key in keys
                                if key
                                in current_actuals["currentActualsChangeOrders"][
                                    change_order_id
                                ]
                            }
                        }
                    )

                line_items = build_ar_line_items(
                    items,
                    work_description,
                    # client_bill_summary,
                    subtotals,
                    change_order_summary,
                )

                return line_items

    except RetryError as e:
        ar_invoice_logger.error(
            f"{e} occured while trying to get Agave customer ID for AR Invoice."
        )
        raise
    except Exception as e:
        ar_invoice_logger.exception(
            f"Unexpected error occurred while trying to get Agave customer ID for AR Invoice: {e}"
        )
        raise
    finally:
        db.close()


def format_cost_code(cost_code, decimal_places=4):
    try:
        num = float(cost_code)
        formatted_num = f"{num:.{decimal_places}f}"
        return formatted_num
    except ValueError:
        return cost_code


def build_ar_line_items(
    items: dict,
    work_description: dict,
    # client_bill_summary: dict,
    subtotals: Dict[str, Any],
    change_order_summary: Dict[str, str | Dict[str, str]] | None,
):
    # TODO fix this funky function, add better typing above
    labor = work_description["actuals"]["laborFee"]
    invoices = work_description["actuals"]["invoice"]
    change_orders = work_description["actualsChangeOrders"]
    line_items = []

    # this has all cost codes, data from QBD
    item_dict = {item["name"]: item for item in items}

    # loop through all labor fee items
    labor_items = []
    for labor_fee in labor.values():
        for cost_code in labor_fee:
            cost_code = format_cost_code(cost_code)
            if cost_code in item_dict:
                item = item_dict[cost_code]
                row_data = labor_fee[str(float(cost_code))]
                if row_data["vendor"] == "HACHI Truck":
                    vendor = row_data["vendor"]
                else:
                    vendor = f"{row_data['vendor']}'s Hours"
                labor_items.append(
                    {
                        "item_id": item["id"],
                        "income_account_id": item["income_account_id"],
                        "amount": row_data["totalAmt"].replace(",", ""),
                        "description": row_data["description"],
                        "quantity": row_data["qtyAmt"],
                        "type": "Subcontractor Costs",
                        "source_data": {
                            "Other1": vendor[:29],
                            "SalesTaxCodeRef": {
                                "ListID": "80000001-1689886183",
                                "FullName": "Tax",
                            },
                        },
                        "_cost_code": float(cost_code),
                    }
                )
    sorted_labor_items = sorted(labor_items, key=lambda x: x["_cost_code"])
    for item in sorted_labor_items:
        del item["_cost_code"]
        line_items.append(item)

    # empty line
    line_items.append({"description": ""})

    ###
    # loop through all AP invoice items
    invoice_items = []
    for invoice in invoices.values():
        for cost_code in invoice:
            cost_code = format_cost_code(cost_code)
            if cost_code in item_dict:
                item = item_dict[cost_code]
                row_data = invoice[str(float(cost_code))]
                invoice_items.append(
                    {
                        "item_id": item["id"],
                        "income_account_id": item["income_account_id"],
                        "amount": row_data["totalAmt"].replace(",", ""),
                        "description": row_data["description"],
                        "quantity": row_data["qtyAmt"],
                        "type": "Subcontractor Costs",
                        "source_data": {
                            "Other1": row_data["vendor"][:29],
                            "SalesTaxCodeRef": {
                                "ListID": "80000001-1689886183",
                                "FullName": "Tax",
                            },
                        },
                    }
                )
    sorted_invoice_items = sorted(
        invoice_items, key=lambda x: x["source_data"]["Other1"]
    )
    line_items.extend(sorted_invoice_items)

    # TODO get the subtotal id from the user add subtotal and an empty line
    line_items.append(
        {
            "description": "Budgeted Items Subtotal",
            "item_id": "363d038f-ab99-57a1-8214-bcc19871dd8e",
        }
    )
    line_items.append({"description": ""})

    # add in the profit, liablity and bo tax fees for budgeted items
    profit_taxes_items = []
    for cost_code in subtotals["budgeted"].keys():
        if subtotals["budgeted"][cost_code]["description"] == "Sales Tax":
            continue
        if cost_code in item_dict:
            item = item_dict[cost_code]
            row_data = subtotals["budgeted"][cost_code]
            profit_taxes_items.append(
                {
                    "item_id": item["id"],
                    "income_account_id": item["income_account_id"],
                    "amount": row_data["totalAmt"].replace(",", ""),
                    "description": row_data["description"],
                    "quantity": row_data["qtyAmt"],
                    "source_data": {
                        "SalesTaxCodeRef": {
                            "ListID": "80000001-1689886183",
                            "FullName": "Tax",
                        }
                    },
                    "_cost_code": float(cost_code),
                }
            )
    sorted_profit_taxes_items = sorted(
        profit_taxes_items, key=lambda x: x["_cost_code"]
    )
    for item in sorted_profit_taxes_items:
        del item["_cost_code"]
        line_items.append(item)

    line_items.append(
        {
            "description": "Budgeted Profit, Liability and Taxes Subtotal",
            "item_id": "363d038f-ab99-57a1-8214-bcc19871dd8e",
        }
    )

    # first check if there are any change orders
    if change_orders:
        # loop through change order items
        grouped_change_orders = []
        for change_order_id, change_order in change_orders.items():
            change_order_name = change_order_summary[change_order_id]["name"]
            change_order_description = change_order_summary[change_order_id][
                "workDescription"
            ]
            single_change_order = []
            single_change_order.append({"description": ""})
            single_change_order.append(
                {"description": f"{change_order_name} - {change_order_description}"}
            )
            change_order_items = []
            for invoice in change_order.values():
                for cost_code in invoice:
                    cost_code = format_cost_code(cost_code)
                    if cost_code in item_dict:
                        item = item_dict[cost_code]
                        row_data = invoice[str(float(cost_code))]
                        change_order_items.append(
                            {
                                "item_id": item["id"],
                                "income_account_id": item["income_account_id"],
                                "amount": row_data["totalAmt"].replace(",", ""),
                                "description": row_data["description"],
                                "quantity": row_data["qtyAmt"],
                                "type": "Subcontractor Costs",
                                "source_data": {
                                    "Other1": row_data["vendor"][:29],
                                    "SalesTaxCodeRef": {
                                        "ListID": "80000001-1689886183",
                                        "FullName": "Tax",
                                    },
                                },
                            }
                        )
            sorted_change_order_items = sorted(
                change_order_items, key=lambda x: x["source_data"]["Other1"]
            )
            single_change_order.extend(sorted_change_order_items)
            # add subtotal here on single change order
            single_change_order_profit_taxes_items = []
            for cost_code in subtotals["changeOrders"][change_order_id].keys():
                if (
                    subtotals["changeOrders"][change_order_id][cost_code]["description"]
                    == "Sales Tax"
                ):
                    continue
                if cost_code in item_dict:
                    cost_code = format_cost_code(cost_code)
                    item = item_dict[cost_code]
                    row_data = subtotals["changeOrders"][change_order_id][
                        str(float(cost_code))
                    ]
                    single_change_order_profit_taxes_items.append(
                        {
                            "item_id": item["id"],
                            "income_account_id": item["income_account_id"],
                            "amount": row_data["totalAmt"].replace(",", ""),
                            "description": row_data["description"],
                            "quantity": row_data["qtyAmt"],
                            "source_data": {
                                "SalesTaxCodeRef": {
                                    "ListID": "80000001-1689886183",
                                    "FullName": "Tax",
                                }
                            },
                            "_cost_code": float(cost_code),
                        }
                    )
            sorted_single_change_order_profit_taxes_items = sorted(
                single_change_order_profit_taxes_items, key=lambda x: x["_cost_code"]
            )
            for item in sorted_single_change_order_profit_taxes_items:
                del item["_cost_code"]
                single_change_order.append(item)
            single_change_order.append(
                {
                    "description": f"{change_order_name} Subtotal",
                    "item_id": "363d038f-ab99-57a1-8214-bcc19871dd8e",
                }
            )
            single_change_order.append({"description": ""})

            grouped_change_orders.append((change_order_name, single_change_order))
        sorted_grouped_change_orders = sorted(grouped_change_orders, key=lambda x: x[0])

        for _, group in sorted_grouped_change_orders:
            line_items.extend(group)

        # # TODO This is the total subtotal, we need each change order subtotal and their individual profit and taxes
        # line_items.append(
        #     {
        #         "description": "Change Order(s) Subtotal",
        #         "item_id": "363d038f-ab99-57a1-8214-bcc19871dd8e",
        #     }
        # )

        # line_items.append({"description": ""})

        # for cost_code in subtotals["changeOrders"].keys():
        #     if subtotals["changeOrders"][cost_code]["description"] == "Sales Tax":
        #         continue
        #     if cost_code in item_dict:
        #         item = item_dict[cost_code]
        #         row_data = subtotals["changeOrders"][cost_code]
        #         line_items.append(
        #             {
        #                 "item_id": item["id"],
        #                 "income_account_id": item["income_account_id"],
        #                 "amount": row_data["totalAmt"].replace(",", ""),
        #                 "description": row_data["description"],
        #                 "quantity": row_data["qtyAmt"],
        #                 "source_data": {
        #                     "SalesTaxCodeRef": {
        #                         "ListID": "80000001-1689886183",
        #                         "FullName": "Tax",
        #                     }
        #                 },
        #             }
        #         )
        # line_items.append(
        #     {
        #         "description": "Change Order(s) Profit, Liability and Taxes Subtotal",
        #         "item_id": "363d038f-ab99-57a1-8214-bcc19871dd8e",
        #     }
        # )

    return line_items
