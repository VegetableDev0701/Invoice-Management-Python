import itertools
from typing import List
import logging
import sys

from google.cloud import firestore
import asyncio
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
from global_vars.globals_io import INITIAL, JITTER, RETRY_TIMES
from utils.database.firestore import (
    delete_project_items_from_firestore,
    delete_collections_from_firestore,
)
from utils.database.invoice_utils import delete_invoices_from_storage
from config import PROJECT_NAME

# Create a logger
client_bill_utils_logger = logging.getLogger("error_logger")
client_bill_utils_logger.setLevel(logging.DEBUG)

try:
    # Create a file handler
    handler = logging.FileHandler(
        "/Users/mgrant/STAK/app/stak-backend/api/logs/firestore_read_write_error_logs.log"
    )
except Exception as e:
    print(e)
    handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)

# Create a logging format
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)

# Add the handlers to the logger
client_bill_utils_logger.addHandler(handler)


async def delete_client_bill_background(
    company_id: str, project_id: str, data: List[str]
):
    invoice_ids = await get_invoice_ids_from_client_bills(
        company_id=company_id, project_id=project_id, client_bill_ids=data
    )

    task1 = delete_project_items_from_firestore(
        project_name=PROJECT_NAME,
        company_id=company_id,
        ids=data,
        document_name="projects",
        project_key=project_id,
        doc_collection_names=["client-bills-summary"],
    )

    task2 = delete_collections_from_firestore(
        project_name=PROJECT_NAME,
        company_id=company_id,
        data=data,
        document_name="projects",
        collection_name=None,
        doc_collection_name=project_id,
        doc_collection_doc_name="client-bills",
    )

    task3 = delete_invoices_from_storage(company_id=company_id, data=invoice_ids)
    try:
        await asyncio.gather(task1, task2, task3)
    except Exception as e:
        client_bill_utils_logger.exception(
            f"Unexpected error occurred while trying to delete client bills: {e}"
        )

    if len(data) == 1:
        return {"message": f"Successfully deleted {len(data)} client bill."}
    else:
        return {"message": f"Successfully deleted {len(data)} client bills."}


async def get_invoice_ids_from_client_bills(
    company_id: str,
    project_id: str,
    client_bill_ids: List[str],
    initial: int = INITIAL,
    jitter: int = JITTER,
) -> List[str]:
    db = firestore.AsyncClient(project=PROJECT_NAME)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(initial=initial, jitter=jitter),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(client_bill_utils_logger, logging.DEBUG),
        ):
            with attempt:
                client_bill_ref = (
                    db.collection(company_id)
                    .document("projects")
                    .collection(project_id)
                    .document("client-bills")
                )
                invoices: List[str] = []
                async for client_bill in client_bill_ref.collections():
                    if client_bill.id in client_bill_ids:
                        invoice_data = (
                            await client_bill_ref.collection(client_bill.id)
                            .document("invoices")
                            .get()
                        )
                        if invoice_data.exists:
                            invoices.append([*invoice_data.to_dict().keys()])
                db.close()
                return [*itertools.chain.from_iterable(invoices)]
    except RetryError as e:
        client_bill_utils_logger.error(
            f"{e} occured while trying to get client bill invoice ids from DB"
        )
        raise
    except Exception as e:
        client_bill_utils_logger.exception(
            f"Unexpected error occurred while trying to get client bill invoice ids from DB: {e}"
        )
        raise
    finally:
        db.close()
