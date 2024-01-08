import asyncio
from functools import partial
import json
import logging
import pathlib
import re
import os
import shutil
import sys
import tempfile

import cv2
import gcsfs
from google.cloud import storage
import numpy as np
from tenacity import (
    retry,
    retry_if_exception_type,
    wait_exponential,
    wait_exponential_jitter,
    stop_after_attempt,
    AsyncRetrying,
    before_sleep_log,
)

from utils.database.firestore import push_to_firestore
from config import PROJECT_NAME
from global_vars.globals_io import (
    RAW_DOCS_PROCESSED_CONTRACTS_PATH,
    RAW_DOCS_PROCESSED_INVOICE_PATH,
    RAW_DOCS_UNPROCESSED_CONTRACTS_PATH,
    RAW_DOCS_UNPROCESSED_INVOICE_PATH,
    RETRY_TIMES,
    STAK_BASE_FORM_BUCKET,
    STAK_COMPANY_FILES_BUCKET,
    STAK_CUSTOMER_DOCUMENTS_BUCKET,
)


# Create a logger
storage_utils_logger = logging.getLogger("error_logger")
storage_utils_logger.setLevel(logging.DEBUG)

try:
    # Create a file handler
    handler = logging.FileHandler(
        "/Users/mgrant/STAK/app/stak-backend/api/logs/storage_utils.log"
    )
except:
    handler = logging.StreamHandler(sys.stdout)

handler.setLevel(logging.DEBUG)

# Create a logging format
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)

# Add the handlers to the logger
storage_utils_logger.addHandler(handler)


def move_blob(
    storage_client: storage.Client,
    bucket_name: str,
    blob_name: str,
    destination_bucket_name: str,
    destination_blob_name: str,
    isCopy: bool = True,
) -> None:
    """
    Moves a blob from one bucket to another with a new name.

    Args:
        storage_client (google.cloud.storage.client.Client): An initialized storage client.
        bucket_name (str): The name of the source bucket.
        blob_name (str): The name of the source blob.
        destination_bucket_name (str): The name of the destination bucket.
        destination_blob_name (str): The name of the destination blob.

    Returns:
        None

    Raises:
        google.cloud.exceptions.NotFound: If either the source blob or the source bucket are not found.
        google.cloud.exceptions.Conflict: If the destination blob already exists in the destination bucket.
    """

    source_bucket = storage_client.bucket(bucket_name)
    source_blob = source_bucket.blob(blob_name)
    destination_bucket = storage_client.bucket(destination_bucket_name)

    # Optional: set a generation-match precondition to avoid potential race conditions
    # and data corruptions. The request is aborted if the object's
    # generation number does not match your precondition. For a destination
    # object that does not yet exist, set the if_generation_match precondition to 0.
    # If the destination object already exists in your bucket, set instead a
    # generation-match precondition using its generation number.
    # There is also an `if_source_generation_match` parameter, which is not used in this example.
    destination_generation_match_precondition = 0

    _ = source_bucket.copy_blob(
        source_blob,
        destination_bucket,
        destination_blob_name,
        if_generation_match=destination_generation_match_precondition,
    )

    if not isCopy:
        source_bucket.delete_blob(blob_name)


async def move_blob_fs(
    fs: gcsfs.GCSFileSystem,
    source_name: str,
    destination_name: str,
    isCopy: bool = True,
) -> None:
    """
    Moves a blob from one bucket to another with a new name.

    Args:
        storage_client (google.cloud.storage.client.Client): An initialized storage client.
        bucket_name (str): The name of the source bucket.
        blob_name (str): The name of the source blob.
        destination_bucket_name (str): The name of the destination bucket.
        destination_blob_name (str): The name of the destination blob.

    Returns:
        None

    Raises:
        google.cloud.exceptions.NotFound: If either the source blob or the source bucket are not found.
        google.cloud.exceptions.Conflict: If the destination blob already exists in the destination bucket.
    """

    if isCopy:
        await asyncio.to_thread(fs.copy, source_name, destination_name)
    else:
        await asyncio.to_thread(fs.mv, source_name, destination_name)


async def save_updated_cost_codes_to_gcs(company_id: str, data: dict, bucket: str):
    """
    Saves data to a location in GCS.
    """
    bucket = await get_storage_bucket(bucket)
    file_name = f"{company_id}/cost-codes.json"

    blob = bucket.blob(file_name)
    await upload_blob_from_str_retry(blob, data)


async def get_sub_dirs(
    prefix: str | None = None,
    bucket_name: str = STAK_CUSTOMER_DOCUMENTS_BUCKET,
) -> set:
    bucket = await get_storage_bucket(bucket_name)
    blobs = [blob for blob in bucket.list_blobs(prefix=prefix)]
    return set([x.name.split("/")[-2] for x in blobs])


def get_all_invoice_filenames(
    bucket_obj: storage.Client(), company_id: str
) -> list[str]:
    """
    List all filenames currently saved in GCP.

    Parameters:
    -------
    bucket_obj: storage.Client()
        Bucket obj
    company_id: str
        The id or name for the company.

    Returns: list
    -------
    List of current filenames
    """

    unprocessed_files_list = [
        re.sub(r"::[^:]*::", "", x.name).split("/")[-1]
        for x in bucket_obj.list_blobs(
            prefix=f"{company_id}/{RAW_DOCS_UNPROCESSED_INVOICE_PATH}/"
        )
    ]
    processed_files_list = [
        re.sub(r"::[^:]*::", "", x.name).split("/")[-1]
        for x in bucket_obj.list_blobs(
            prefix=f"{company_id}/{RAW_DOCS_PROCESSED_INVOICE_PATH}/"
        )
    ]

    return [*unprocessed_files_list, *processed_files_list]


def get_all_contract_filenames(
    bucket_obj: storage.Client(), company_id: str, project_id: str
) -> list[str]:
    """
    List all filenames currently saved in GCP.

    Parameters:
    -------
    bucket_obj: storage.Client()
        Bucket obj
    company_id: str
        The id or name for the company.
    project_id: str
        The unique id for a project

    Returns: list
    -------
    List of current filenames
    """

    unprocessed_files_list = [
        os.path.splitext(re.sub(r"::[^:]*::", "", x.name).split("/")[-1])[0]
        for x in bucket_obj.list_blobs(
            prefix=f"{company_id}/projects/{project_id}/{RAW_DOCS_UNPROCESSED_CONTRACTS_PATH}"
        )
    ]
    processed_files_list = [
        os.path.splitext(re.sub(r"::[^:]*::", "", x.name).split("/")[-1])[0]
        for x in bucket_obj.list_blobs(
            prefix=f"{company_id}/projects/{project_id}/{RAW_DOCS_PROCESSED_CONTRACTS_PATH}"
        )
    ]

    return [*unprocessed_files_list, *processed_files_list]


async def get_storage_bucket(
    bucket: str, initial: int = 5, jitter: int = 5
) -> storage.Client():
    """
    Return a bucket object

    Parameters:
    -------
    bucket: str
        The name of the bucket to return.

    Returns:
    -------
    The storage client object.
    """

    storage_client = storage.Client()
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(initial=initial, jitter=jitter),
            retry=retry_if_exception_type(Exception),
            reraise=True,
            before_sleep=before_sleep_log(storage_utils_logger, logging.DEBUG),
        ):
            with attempt:
                return storage_client.get_bucket(bucket)

    except Exception as e:
        storage_utils_logger.exception(f"An error occurred getting data: {e}")


async def upload_blob_from_file_retry(
    blob, file_path, content_type: str | None = None, initial: int = 5, jitter: int = 5
) -> None:
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(RETRY_TIMES),  # Retry up to 3 times
        wait=wait_exponential_jitter(initial=initial, jitter=jitter),
        retry=retry_if_exception_type(Exception),  # Retry on all exceptions
        reraise=True,
        before_sleep=before_sleep_log(storage_utils_logger, logging.DEBUG),
    ):
        try:
            with attempt:
                loop = asyncio.get_event_loop()
                upload_func = partial(
                    blob.upload_from_filename, file_path, content_type=content_type
                )
                await loop.run_in_executor(None, upload_func)
        except Exception as e:
            storage_utils_logger.exception(f"An error occurred uploading blob: {e}")


async def upload_blob_from_str_retry(
    blob, data: dict, initial: int = 5, jitter: int = 5
) -> None:
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(RETRY_TIMES),  # Retry up to 3 times
        wait=wait_exponential_jitter(initial=initial, jitter=jitter),
        retry=retry_if_exception_type(Exception),  # Retry on all exceptions
        reraise=True,
        before_sleep=before_sleep_log(storage_utils_logger, logging.DEBUG),
    ):
        try:
            with attempt:
                loop = asyncio.get_event_loop()
                upload_func = partial(
                    blob.upload_from_string,
                    json.dumps(data),
                    content_type="application/json",
                )
                await loop.run_in_executor(None, upload_func)
        except Exception as e:
            storage_utils_logger.exception(f"An error occurred uploading blob: {e}")


async def download_blob_with_retry(
    blob, file_path: str, initial: int = 5, jitter: int = 5
) -> None:
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(RETRY_TIMES),  # Retry up to 3 times
        wait=wait_exponential_jitter(initial=initial, jitter=jitter),
        retry=retry_if_exception_type(Exception),  # Retry on all exceptions
        reraise=True,
        before_sleep=before_sleep_log(storage_utils_logger, logging.DEBUG),
    ):
        try:
            with attempt:
                loop = asyncio.get_event_loop()
                download_func = partial(blob.download_to_filename, file_path)
                await loop.run_in_executor(None, download_func)
        except Exception as e:
            storage_utils_logger.exception(f"An error occurred downloading blob: {e}")


@retry(
    stop=stop_after_attempt(RETRY_TIMES),  # Retry up to 3 times
    wait=wait_exponential(multiplier=1, max=10),  # Exponential backoff
    retry=retry_if_exception_type(Exception),  # Retry on all exceptions
)
def get_signed_url(blob, expiration, credentials):
    return blob.generate_signed_url(
        expiration=expiration,
        version="v4",
        service_account_email=credentials.service_account_email,
        access_token=credentials.token,
    )


async def save_cv2_image(
    hex_string: str, temp_file: str, destination_prefix: str, destination_filename: str
) -> None:
    """

    Parameters
    ----------
    hex_string: str
        The "byte string" in hex format from the database
    """
    bucket = await get_storage_bucket(STAK_CUSTOMER_DOCUMENTS_BUCKET)
    blob = bucket.blob(f"{destination_prefix}/{destination_filename}")
    imgarr = np.frombuffer(bytes.fromhex(hex_string), np.uint8)
    img_np = cv2.imdecode(imgarr, cv2.IMREAD_COLOR)
    loop = asyncio.get_event_loop()
    write_img_func = partial(
        cv2.imwrite, temp_file, img_np, [cv2.IMWRITE_JPEG_QUALITY, 30]
    )
    await loop.run_in_executor(None, write_img_func)
    await upload_blob_from_file_retry(blob, temp_file)


async def save_doc_dict(doc_dict: dict, destination: str):
    bucket = await get_storage_bucket(STAK_CUSTOMER_DOCUMENTS_BUCKET)
    blob = bucket.blob(destination)
    await upload_blob_from_str_retry(blob, data=doc_dict)


async def download_and_onboard_new_company_files(company_id: str) -> None:
    base_form_bucket = await get_storage_bucket(STAK_BASE_FORM_BUCKET)
    cost_code_bucket = await get_storage_bucket(STAK_COMPANY_FILES_BUCKET)

    tasks = []
    base_form_blobs = base_form_bucket.list_blobs()
    cost_code_blob = cost_code_bucket.list_blobs(prefix=f"cost-codes/{company_id}/")

    base_kwargs = {
        "project_name": PROJECT_NAME,
        "collection": company_id,
    }

    # Load all the base form data for the new company
    for blob in [x for x in base_form_blobs if re.search(r"json$", x.name)]:
        temp_dir = tempfile.mkdtemp()  # Create a temporary directory
        temp_file_path = pathlib.Path(temp_dir) / "temp.json"

        with open(temp_file_path, "wb") as temp_file:
            await download_blob_with_retry(blob, temp_file.name)
            kwargs = base_kwargs.copy()
            name = blob.name.split("/")[-1].split(".")[0]
            kwargs.update(
                {
                    "document": "base-forms",
                    "doc_collection": "forms",
                    "doc_collection_document": name,
                }
            )
            kwargs.update({"path_to_json": temp_file.name})
            task = asyncio.create_task(push_to_firestore(**kwargs))
            task.add_done_callback(lambda future, path=temp_dir: shutil.rmtree(path))
            tasks.append(task)

    # load the specific company's cost codes if they exist, otherwise load a base empty cost code form
    cost_code_blob_list = [x for x in cost_code_blob if re.search(r"json$", x.name)]
    if cost_code_blob_list:
        for blob in cost_code_blob_list:
            temp_dir = tempfile.mkdtemp()  # Create a temporary directory
            temp_file_path = pathlib.Path(temp_dir) / "temp.json"
            with open(temp_file_path, "wb") as temp_file:
                await download_blob_with_retry(blob, temp_file.name)
                kwargs = base_kwargs.copy()
                kwargs.update(
                    {"document": "cost-codes", "path_to_json": temp_file.name}
                )
                task = asyncio.create_task(push_to_firestore(**kwargs))
                task.add_done_callback(
                    lambda future, path=temp_dir: shutil.rmtree(path)
                )
                tasks.append(task)
    else:
        temp_dir = tempfile.mkdtemp()  # Create a temporary directory
        temp_file_path = pathlib.Path(temp_dir) / "temp.json"
        with open(temp_file_path, "w+") as temp_file:
            empty_cost_codes = {"format": "Custom", "updated": False, "divisions": []}
            json.dump(empty_cost_codes, temp_file)
            kwargs = base_kwargs.copy()
            kwargs.update({"document": "cost-codes", "path_to_json": temp_file.name})
            task = asyncio.create_task(push_to_firestore(**kwargs))
            task.add_done_callback(lambda future, path=temp_dir: shutil.rmtree(path))
            tasks.append(task)
    _ = await asyncio.gather(*tasks)
