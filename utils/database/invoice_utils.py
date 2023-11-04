from typing import Dict, List
import logging
import sys
import re
import asyncio
from typing import List

from fastapi import HTTPException
from google.cloud import storage, firestore
from tenacity import (
    retry_if_exception_type,
    wait_exponential_jitter,
    stop_after_attempt,
    AsyncRetrying,
    RetryError,
    before_sleep_log,
)

from utils.data_models.change_orders import InvoiceProcessedData
from utils.database.firestore import (
    delete_collections_from_firestore,
    push_update_to_firestore,
)
from utils.io_utils import delete_document_hash_from_firestore
from utils.retry_utils import RETRYABLE_EXCEPTIONS
from config import PROJECT_NAME, CUSTOMER_DOCUMENT_BUCKET
from global_vars.globals_io import RETRY_TIMES

logger_invoices = logging.getLogger("error_logger")
logger_invoices.setLevel(logging.DEBUG)

# Create a file handler
# handler = logging.FileHandler(
#     "/Users/mgrant/STAK/app/stak-backend/api/logs/invoices.log"
# )
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)

# Create a logging format
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)

# Add the handlers to the logger
logger_invoices.addHandler(handler)

client = storage.Client(project=PROJECT_NAME)
bucket = client.get_bucket(CUSTOMER_DOCUMENT_BUCKET)


async def delete_invoice_wrapper(company_id: str, data: List[str]) -> None:
    task1 = delete_invoices_from_firestore(company_id=company_id, data=data)
    task2 = delete_invoices_from_storage(company_id=company_id, data=data)

    await asyncio.gather(task1, task2)


async def delete_invoices_from_firestore(company_id: str, data: List[str]) -> None:
    try:
        task1 = delete_collections_from_firestore(
            project_name=PROJECT_NAME,
            company_id=company_id,
            data=data,
            document_name="documents",
            collection_name="processed_documents",
        )
        task2 = delete_document_hash_from_firestore(
            uuids=data, project_name=PROJECT_NAME, company_id=company_id
        )
        await asyncio.gather(task1, task2)

    except Exception as e:
        logger_invoices.exception(f"Error while deleting documents from Firestore: {e}")
        await push_update_to_firestore(
            project_name=PROJECT_NAME,
            collection=company_id,
            data={"is_deleting_docs": False},
            document="logging",
        )
        raise HTTPException(
            status_code=500, detail="Error while deleting documents from Firestore."
        )


async def delete_invoices_from_storage(company_id: str, data: List[str]) -> None:
    """
    Utililty function to delete invoices. To be run as a background task.

    Params:
        company_id: str
        data: List of invoice ids to delete
    """

    bucket = client.get_bucket(CUSTOMER_DOCUMENT_BUCKET)
    blobs_to_delete = [
        x.name
        for x in client.list_blobs(CUSTOMER_DOCUMENT_BUCKET, prefix=company_id)
        for doc_id in data
        if re.search(doc_id, x.name)
    ]

    try:
        not_found_blobs = bucket.delete_blobs(blobs_to_delete)
        if not_found_blobs:
            logger_invoices.warning(
                f"Blobs not found, couldn't be deleted: {not_found_blobs}"
            )

    except Exception as e:
        logger_invoices.error(
            f"Error while deleting blobs from Google Cloud Storage: {e}"
        )
        await push_update_to_firestore(
            project_name=PROJECT_NAME,
            collection=company_id,
            data={"is_deleting_docs": False},
            document="logging",
        )
        raise HTTPException(
            status_code=500,
            detail="Error while deleting blobs from Google Cloud Storage.",
        )
    await push_update_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data={"is_deleting_docs": False},
        document="logging",
    )


async def update_invoice_processed_data(
    project_name: str,
    company_id: str,
    document_name: str,
    collection_name: str,
    data: InvoiceProcessedData,
) -> None:
    db = firestore.AsyncClient(project=project_name)
    update_processed_data = data.dict()["__root__"]
    invoice_ids = [*update_processed_data.keys()]

    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(logger_invoices, logging.DEBUG),
        ):
            with attempt:
                invoice_ref = (
                    db.collection(company_id)
                    .document(document_name)
                    .collection(collection_name)
                    .where("__name__", "in", invoice_ids)
                )
            tasks = []
            async for doc in invoice_ref.stream():
                coroutine = doc.reference.update(
                    {"processedData": update_processed_data[doc.id]["processedData"]}
                )
                tasks.append(asyncio.create_task(coroutine))
            await asyncio.gather(*tasks)

    except RetryError as e:
        logger_invoices.error(f"{e} occured while trying to update processedData. ")
        raise
    except Exception as e:
        logger_invoices.exception(
            f"Unexpected error occured while trying to update processedData: {e}; for invoices {invoice_ids}"
        )
        raise
    finally:
        db.close()
