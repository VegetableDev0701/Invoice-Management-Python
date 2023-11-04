from typing import List
import logging
import sys
import re

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

from global_vars.globals_io import RETRY_TIMES

# Create a logger
co_utils_logger = logging.getLogger("error_logger")
co_utils_logger.setLevel(logging.DEBUG)

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
co_utils_logger.addHandler(handler)


async def update_invoice_in_change_order_in_firestore(
    project_name: str,
    collection: str,
    invoice_ids: List[str],
    document: str,
    change_order_id: str,
    doc_collection: str,
    doc_collection_document: str,
) -> None:
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(co_utils_logger, logging.DEBUG),
        ):
            with attempt:
                co_summary_ref = (
                    db.collection(collection)
                    .document(document)
                    .collection(doc_collection)
                    .document(doc_collection_document)
                )

                doc = await co_summary_ref.get()
                if doc.exists:
                    content = doc.to_dict()[f"{change_order_id}"]["content"]
                    content_items_to_delete = []
                    for content_item in content.keys():
                        for id_to_delete in invoice_ids:
                            if re.search(id_to_delete, content_item):
                                content_items_to_delete.append(content_item)
                    for item in content_items_to_delete:
                        del content[item]
                    await co_summary_ref.update({f"{change_order_id}.content": content})
                else:
                    return {
                        "message": f"Change order id {change_order_id} doesn't exist."
                    }

    except RetryError as e:
        co_utils_logger.error(
            f"{e} occured while trying to add/remove invoice to change order. "
        )
        raise
    except Exception as e:
        co_utils_logger.exception(
            f"Unexpected error occured while trying to add/remove invoice to change order.: {e}"
        )
        raise
    finally:
        db.close()
