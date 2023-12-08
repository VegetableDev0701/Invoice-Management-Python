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
from utils.data_models.projects import SummaryLabor
from utils.database.db_utils import set_target_value
from utils.retry_utils import RETRYABLE_EXCEPTIONS

from global_vars.globals_io import RETRY_TIMES

# Create a logger
firestore_labor_logger = logging.getLogger("error_logger")
firestore_labor_logger.setLevel(logging.DEBUG)

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
firestore_labor_logger.addHandler(handler)


async def remove_change_order_from_labor_data(
    labor_to_update: SummaryLabor,
    project_name: str,
    company_id: str,
    project_id: str,
):
    db = firestore.AsyncClient(project=project_name)

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_labor_logger, logging.DEBUG),
        ):
            with attempt:
                labor_ref = (
                    db.collection(company_id)
                    .document("projects")
                    .collection(project_id)
                    .document("labor")
                )
                labor_summary_ref = (
                    db.collection(company_id)
                    .document("projects")
                    .collection(project_id)
                    .document("labor-summary")
                )

                labor_summary_doc = await labor_summary_ref.get()
                labor_form_data_doc = await labor_ref.get()

                if labor_summary_doc.exists:
                    labor_summary_doc.reference.update(labor_to_update)

                if labor_form_data_doc.exists:
                    for labor_id, labor_summary_dict in labor_to_update.items():
                        labor_doc_dict = labor_form_data_doc.to_dict()
                        single_labor = labor_doc_dict[labor_id]
                        input_elements = single_labor["mainCategories"][1][
                            "inputElements"
                        ]
                        for key, value in labor_summary_dict.items():
                            if key == "line_items":
                                for item_id in value.keys():
                                    item_number = item_id.split("_")[-1]
                                    target_id = f"{item_number}-change-order"
                                    set_target_value(
                                        target_id=target_id,
                                        input_elements=input_elements,
                                        set_value=None,
                                    )

                        single_labor["mainCategories"][1][
                            "inputElements"
                        ] = input_elements
                        await labor_form_data_doc.reference.update(
                            {labor_id: single_labor}
                        )

    except RetryError as e:
        firestore_labor_logger.error(
            f"{e} occured while trying to delete change order data from labor data in firestore."
        )
        raise

    except Exception as e:
        firestore_labor_logger.exception(
            f"Unexpected error occured while trying to delete change order data from labor data in firestore: {e}"
        )
        raise

    finally:
        db.close()


def _update_target_value(target_id, input_elements, set_value):
    for element in input_elements:
        if is_input_element_with_items(element):
            found_item = next(
                (item for item in element["items"] if item["id"] == target_id), None
            )
            if found_item:
                found_item["value"] = set_value
                return True
        if is_input_element_with_address_elements(element):
            for address_element in element["addressElements"]:
                found_item = next(
                    (
                        item
                        for item in address_element["items"]
                        if item["id"] == target_id
                    ),
                    None,
                )
                if found_item:
                    found_item["value"] = set_value
                    return True
    return False
