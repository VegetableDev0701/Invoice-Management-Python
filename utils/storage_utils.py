import asyncio
from functools import partial
import json
import pathlib
import re
import os
import shutil
import tempfile

import cv2
import gcsfs
from google.cloud import storage
import numpy as np

from utils.database.firestore import push_to_firestore
from config import PROJECT_NAME
from global_vars import globals_io


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


def get_sub_dirs(
    storage_client: storage.Client,
    prefix: str | None = None,
    bucket_name: str = "stak-customer-documents",
) -> set:
    bucket = storage_client.get_bucket(bucket_name)
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
            prefix=f"{company_id}/{globals_io.RAW_DOCS_UNPROCESSED_INVOICE_PATH}/"
        )
    ]
    processed_files_list = [
        re.sub(r"::[^:]*::", "", x.name).split("/")[-1]
        for x in bucket_obj.list_blobs(
            prefix=f"{company_id}/{globals_io.RAW_DOCS_PROCESSED_INVOICE_PATH}/"
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
            prefix=f"{company_id}/projects/{project_id}/{globals_io.RAW_DOCS_UNPROCESSED_CONTRACTS_PATH}"
        )
    ]
    processed_files_list = [
        os.path.splitext(re.sub(r"::[^:]*::", "", x.name).split("/")[-1])[0]
        for x in bucket_obj.list_blobs(
            prefix=f"{company_id}/projects/{project_id}/{globals_io.RAW_DOCS_PROCESSED_CONTRACTS_PATH}"
        )
    ]

    return [*unprocessed_files_list, *processed_files_list]


def get_storage_bucket(bucket: str) -> storage.Client():
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
    return storage_client.get_bucket(bucket)


def save_cv2_image(
    hex_string: str, temp_file: str, destination_prefix: str, destination_filename: str
) -> None:
    """

    Parameters
    ----------
    hex_string: str
        The "byte string" in hex format from the database
    company_id: str
        Image size (width, height)
    filename: str
    """
    bucket = get_storage_bucket("stak-customer-documents")
    blob = bucket.blob(f"{destination_prefix}/{destination_filename}")
    imgarr = np.frombuffer(bytes.fromhex(hex_string), np.uint8)
    img_np = cv2.imdecode(imgarr, cv2.IMREAD_COLOR)
    cv2.imwrite(temp_file, img_np, [cv2.IMWRITE_JPEG_QUALITY, 30])
    blob.upload_from_filename(temp_file)


def save_doc_dict(doc_dict: dict, destination: str):
    bucket = get_storage_bucket("stak-customer-documents")
    blob = bucket.blob(destination)
    blob.upload_from_string(json.dumps(doc_dict), content_type="application/json")


async def save_cv2_image_async(
    hex_string: str, temp_file: str, destination_prefix: str, destination_filename: str
) -> None:
    """

    Parameters
    ----------
    hex_string: str
        The "byte string" in hex format from the database
    """
    bucket = get_storage_bucket("stak-customer-documents")
    blob = bucket.blob(f"{destination_prefix}/{destination_filename}")
    imgarr = np.frombuffer(bytes.fromhex(hex_string), np.uint8)
    img_np = cv2.imdecode(imgarr, cv2.IMREAD_COLOR)
    loop = asyncio.get_event_loop()
    write_img_func = partial(
        cv2.imwrite, temp_file, img_np, [cv2.IMWRITE_JPEG_QUALITY, 30]
    )
    await loop.run_in_executor(None, write_img_func)

    upload_func = partial(blob.upload_from_filename, temp_file)
    await loop.run_in_executor(None, upload_func)


async def save_doc_dict_async(doc_dict: dict, destination: str):
    bucket = get_storage_bucket("stak-customer-documents")
    blob = bucket.blob(destination)

    loop = asyncio.get_event_loop()
    upload_func = partial(
        blob.upload_from_string, json.dumps(doc_dict), content_type="application/json"
    )
    await loop.run_in_executor(None, upload_func)


async def download_and_onboard_new_company_files(company_id: str):
    storage_client = storage.Client()
    bucket = storage_client.get_bucket("stak-company-files")

    tasks = []
    blobs = bucket.list_blobs(prefix="data/")

    base_kwargs = {
        "project_name": PROJECT_NAME,
        "collection": company_id,
    }

    for blob in [x for x in blobs if re.search(r"json$", x.name)]:

        temp_dir = tempfile.mkdtemp()  # Create a temporary directory
        temp_file_path = pathlib.Path(temp_dir) / "temp.json"

        with open(temp_file_path, "wb") as temp_file:
            blob.download_to_filename(temp_file.name)
            kwargs = base_kwargs.copy()
            if "cost-codes_updated.json" in blob.name:
                kwargs.update({"document": "cost-codes"})
            else:
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

    await asyncio.gather(*tasks)