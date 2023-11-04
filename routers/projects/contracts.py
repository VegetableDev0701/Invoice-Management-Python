import asyncio
import datetime
import os
from typing import Dict, List, Union
import re

import aiofiles
from google.cloud import storage
import google
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    BackgroundTasks,
    Query,
    UploadFile,
    File,
)

from utils.database.firestore import push_update_to_firestore

from utils.contract_helpers import delete_contracts_wrapper
from config import Config, PROJECT_NAME, CUSTOMER_DOCUMENT_BUCKET
from utils import io_utils, storage_utils, auth, contract_helpers
from data_processing_pipeline import gcp_docai_utils as docai_async
from validation import io_validation
from global_vars.globals_io import (
    OCR_PROCESSOR_ID,
    GCS_OUTPUT_BUCKET,
    SCOPES,
)

credentials, project = google.auth.default(scopes=SCOPES)
credentials.refresh(google.auth.transport.requests.Request())
client = storage.Client(project=project, credentials=credentials)
bucket = client.get_bucket(CUSTOMER_DOCUMENT_BUCKET)

router = APIRouter()


@router.post("/{company_id}/upload-contracts", status_code=200)
async def create_files(
    company_id: str,
    project_id: str | None,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(description="Uploading Contracts"),
    #current_user=Depends(auth.get_current_user),
) -> Dict[str, str]:
    """
    Endpoint for uploading multiple files.

    Args:
        company_id (str): The ID of the company the files belong to.
        project_id (str): The ID for the project
        files (List[UploadFile]): An array of file objects to upload. Defaults to an empty array.

    Raises:
        HTTPException: If the filenames of the uploaded files already exist in storage,
        or if the document type of any file is not 'application/pdf'.

    Returns:
        dict: A dictionary containing a message indicating the files were successfully uploaded.
    """
    #auth.check_user_data(company_id=company_id, current_user=current_user)
    bucket = storage_utils.get_storage_bucket("stak-customer-documents")

    # Check for duplicate files
    current_uploads, repeats = await io_utils.calculate_file_hash(files)
    files = [file for file in files if file.filename not in repeats]

    duplicates = await io_validation.check_for_duplicates_by_hash(
        new_files_hashes=current_uploads,
        project_name=PROJECT_NAME,
        company_id=company_id,
        document_name="documents",
    )
    duplicates_names = None
    if duplicates:
        # Remove any `'` from any duplicates otherwise will affect listing those
        # names on the frontend due to error in JSON parsing
        duplicates_names = [x.replace("'", "") for x in duplicates.values()]
        if len(duplicates) == len(files):
            raise HTTPException(
                status_code=409,
                detail=f"All files were already found in storage: {duplicates_names}",
                # detail=f"The following filenames already exist in storage. Are you sure you meant to upload this set: {duplicates}",
                headers={"X-Header-Error": "Duplicate Files"},
            )
        else:
            files = [
                (contract_id, file)
                for contract_id, file in zip(
                    [io_utils.create_short_uuid() for _ in range(len(files))], files
                )
                if file.filename not in duplicates.values()
            ]
            unique_hashes = {
                key: value
                for key, value in current_uploads.items()
                if key not in duplicates.keys()
            }
            upload_hashes = {
                uuid: {"hash": hash, "filename": filename}
                for uuid, file in files
                for hash, filename in unique_hashes.items()
                if file.filename == filename
            }
            await push_update_to_firestore(
                project_name=PROJECT_NAME,
                collection=company_id,
                data=upload_hashes,
                document="documents",
            )
    else:
        files = [
            (contract_id, file)
            for contract_id, file in zip(
                [io_utils.create_short_uuid() for x in range(len(files))], files
            )
        ]
        upload_hashes = {
            uuid: {"hash": hash, "filename": filename}
            for uuid, file in files
            for hash, filename in current_uploads.items()
            if file.filename == filename
        }
        await push_update_to_firestore(
            project_name=PROJECT_NAME,
            collection=company_id,
            data=upload_hashes,
            document="documents",
        )

    i = 0
    tasks = []
    for contract_id, file in files:
        if (
            not re.search(r"doc|docx$", file.filename.split(".")[-1])
            and file.content_type != "application/pdf"
        ):
            raise HTTPException(422, "Invalid document type")

        filename = f"{os.path.splitext(file.filename)[0]}::{contract_id}::.pdf"

        bucket_prefix = f"{company_id}/projects/{project_id}/contracts/raw-documents/unprocessed/{i}"
        while (
            len(list(bucket.list_blobs(prefix=f"{bucket_prefix}/")))
            >= Config.BATCH_LIMIT
        ):
            i += 1
            bucket_prefix = f"{company_id}/projects/{project_id}/contracts/raw-documents/unprocessed/{i}"
        # use asyncio.gather here to speed up the conversion of docx -> pdf
        if contract_helpers.check_if_word_doc(file.filename):
            async with aiofiles.tempfile.NamedTemporaryFile("wb") as out_file:
                try:
                    coroutine = contract_helpers.convert_word_to_pdf(
                        in_file=file,
                        out_file=out_file,
                        bucket_prefix=bucket_prefix,
                        filename=filename,
                    )
                    tasks.append(asyncio.create_task(coroutine))
                except HTTPException as e:
                    raise HTTPException(
                        status_code=422,
                        detail=f"Error in conversion of word document to pdf.",
                        headers={"X-Header-Error": "Conversion Error"},
                    )
        else:
            async with aiofiles.tempfile.NamedTemporaryFile("wb") as out_file:
                content = await file.read()
                await out_file.write(content)
                blob = bucket.blob(f"{bucket_prefix}/{filename}")
                blob.upload_from_filename(out_file.name, content_type=file.content_type)

    await asyncio.gather(*tasks)
    await push_update_to_firestore(
        project_name="stak-app",
        collection=company_id,
        data={"is_processing_docs": True},
        document="logging",
    )

    background_tasks.add_task(
        docai_async.batch_process_contracts,
        gcp_project_id=PROJECT_NAME,
        location="us",
        processor_id=OCR_PROCESSOR_ID,
        gcs_output_bucket=GCS_OUTPUT_BUCKET,
        gcs_output_uri_prefix=f"{company_id}/docai/contracts/raw-processed/",
        company_id=company_id,
        bucket_name="stak-customer-documents",
        project_id=project_id,
    )

    return {
        "message": f"Files successfully uploaded. Duplicate files: {duplicates_names}",
    }


@router.get("/{company_id}/contract/generate-signed-url")
async def generate_signed_url(
    company_id: str,
    project_id: str,
    contract_id: str,
    filenames: List[str] = Query(None),
    #current_user=Depends(auth.get_current_user),
) -> Dict[str, Union[List, str]]:
    #auth.check_user_data(company_id=company_id, current_user=current_user)

    expiration = datetime.timedelta(hours=1)
    expiration_datetime = datetime.datetime.utcnow() + expiration
    expiration_timestamp = int(expiration_datetime.timestamp())

    signed_urls = []
    for filename in filenames:
        blob_path = f"{company_id}/projects/{project_id}/contracts/processed-documents/{contract_id}/{filename}"
        blob = bucket.get_blob(blob_path)
        try:
            signed_urls.append(
                blob.generate_signed_url(
                    expiration=expiration,
                    version="v4",
                    service_account_email=credentials.service_account_email,
                    access_token=credentials.token,
                )
            )
        except:
            return {"message": "Error generating the signed url."}

    return {"signed_urls": signed_urls, "expiration": expiration_timestamp}


@router.delete("/{company_id}/delete-contracts")
async def delete_invoices(
    company_id: str,
    project_id: str,
    data: List[str],
    background_tasks: BackgroundTasks,
    #current_user=Depends(auth.get_current_user),
) -> Dict[str, str]:
    #auth.check_user_data(company_id=company_id, current_user=current_user)

    await push_update_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data={"is_deleting_docs": True},
        document="logging",
    )

    background_tasks.add_task(
        delete_contracts_wrapper,
        data=data,
        company_id=company_id,
        project_id=project_id,
    )

    return {"message": f"{len(data)} contracts set for deletion."}
