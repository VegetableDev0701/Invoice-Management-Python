import asyncio
import datetime
from typing import Dict, List, Union
import aiofiles
import logging
import sys

import google
from google.cloud import storage

from fastapi import (
    APIRouter,
    Depends,
    Query,
    HTTPException,
    BackgroundTasks,
    UploadFile,
    File,
)
from config import PROJECT_NAME
from utils.database.firestore import (
    stream_entire_collection,
    get_project_docs_from_firestore,
    push_update_to_firestore,
    push_to_firestore,
    update_invoice_projects_in_firestore,
    update_processed_invoices_in_firestore,
    update_approved_invoice_in_firestore,
    add_gpt_line_items_to_invoice_data_in_firestore,
    remove_change_order_id_from_invoices_in_firestore,
)
from utils.database.projects.change_order_utils import (
    update_invoice_in_change_order_in_firestore,
)
from utils.database.invoice_utils import (
    delete_invoice_wrapper,
)
from config import PROJECT_NAME, Config, CUSTOMER_DOCUMENT_BUCKET
from utils import io_utils, storage_utils, auth
from utils.data_models.invoices import (
    InvoiceProjects,
    ProcessedInvoiceData,
    GPTLineItems,
    InvoiceItemForSingle
)
from data_processing_pipeline import gcp_docai_utils as docai_async
from validation import io_validation
from global_vars.globals_io import (
    RAW_DOCS_UNPROCESSED_INVOICE_PATH,
    INVOICE_PROCESSOR_ID,
    GCS_OUTPUT_BUCKET,
    DOC_TYPE_INVOICE,
    SCOPES,
)

logger_invoices = logging.getLogger("error_logger")
logger_invoices.setLevel(logging.DEBUG)

try:
    # Create a file handler
    handler = logging.FileHandler(
        "/Users/mgrant/STAK/app/stak-backend/api/logs/invoices.log"
    )
except Exception as e:
    print(e)
    handler = logging.StreamHandler(sys.stdout)

handler.setLevel(logging.DEBUG)

# Create a logging format
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)

# Add the handlers to the logger
logger_invoices.addHandler(handler)

credentials, project = google.auth.default(scopes=SCOPES)
credentials.refresh(google.auth.transport.requests.Request())

# define a background tasks dict in the global scope
background_tasks_dict = {}
DOC_TYPE = DOC_TYPE_INVOICE
TESTING = False

router = APIRouter()


@router.get("/{company_id}/get-all-invoices")
async def get_all_invoices(
    company_id: str, current_user=Depends(auth.get_current_user)
) -> dict:
    auth.check_user_data(company_id=company_id, current_user=current_user)

    invoices = await stream_entire_collection(
        project_name=PROJECT_NAME,
        collection_name=company_id,
        document_name="documents",
        doc_collection_name="processed_documents",
    )

    return invoices

@router.post("/{company_id}/add-single-invoice")
async def add_single_invoice(
    company_id: str,
    data: InvoiceItemForSingle,
    current_user=Depends(auth.get_current_user)
) -> dict:
    
    auth.check_user_data(company_id=company_id, current_user=current_user)

    await push_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data=data,
        document="documents",
        doc_collection=data.invoice_id,
        doc_collection_document="processed_documents"
    )

    return {
        "message": "Successfully added new Invoice",
    }


@router.get("/{company_id}/invoice/generate-signed-url")
async def generate_signed_url(
    company_id: str,
    doc_id: str,
    filenames: List[str] = Query(None),
    current_user=Depends(auth.get_current_user),
) -> Dict[str, Union[List, str]]:
    auth.check_user_data(company_id=company_id, current_user=current_user)

    expiration = datetime.timedelta(hours=1)
    expiration_datetime = datetime.datetime.utcnow() + expiration
    expiration_timestamp = int(expiration_datetime.timestamp())

    bucket = await storage_utils.get_storage_bucket(CUSTOMER_DOCUMENT_BUCKET)

    signed_urls = []
    for filename in filenames:
        blob_path = f"{company_id}/processed-documents/{doc_id}/{filename}"
        blob = bucket.get_blob(blob_path)

        try:
            signed_url = storage_utils.get_signed_url(blob, expiration, credentials)
            signed_urls.append(signed_url)
        except Exception as e:
            print(e)
            return {"message": f"Error generating the signed url: {e}"}

    return {"signed_urls": signed_urls, "expiration": expiration_timestamp}


@router.post("/{company_id}/upload-files", status_code=200)
async def create_files(
    company_id: str,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(description="Uploading Invoices"),
    current_user=Depends(auth.get_current_user),
) -> Dict[str, str]:
    """
    Endpoint for uploading multiple files.

    Args:
        company_id (str): The ID of the company the files belong to.
        files (List[UploadFile]): An array of file objects to upload. Defaults to an empty array.

    Raises:
        HTTPException: If the filenames of the uploaded files already exist in storage,
        or if the document type of any file is not 'application/pdf'.

    Returns:
        dict: A dictionary containing a message indicating the files were successfully uploaded.
    """
    auth.check_user_data(company_id=company_id, current_user=current_user)
    bucket = await storage_utils.get_storage_bucket(CUSTOMER_DOCUMENT_BUCKET)

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
    if TESTING:
        pass
    else:
        # Check if all files were found to be duplicates using the md5 hash
        if duplicates:
            # Remove any `'` from any duplicates otherwise will affect listing those
            # names on the frontend due to error in JSON parsing
            duplicates_names = [x.replace("'", "") for x in duplicates.values()]
            if len(duplicates.keys()) == len(files):
                raise HTTPException(
                    status_code=409,
                    detail=f"All files were already found in storage: {duplicates_names}",
                    headers={"X-Header-Error": "Duplicate Files"},
                )
            else:
                # If only some of the files were found to be duplicates keep processing the ones that are not duplicates
                # also attach a uuid to each invoice
                files = [
                    (invoice_id, file)
                    for invoice_id, file in zip(
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
                (invoice_id, file)
                for invoice_id, file in zip(
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

    upload_tasks = []
    i = 0
    for invoice_id, file in files:
        if file.content_type != "application/pdf":
            raise HTTPException(422, "Invalid document type")
        filename = f"{file.filename.split('.pdf')[:-1][0]}::{invoice_id}::.{file.content_type.split('/')[-1]}"
        # TODO
        # If having spaces in files becomes a problem will add this code back
        # filename = db_utils.format_filename(filename)
        bucket_prefix = (
            f"{company_id}/{RAW_DOCS_UNPROCESSED_INVOICE_PATH}/{DOC_TYPE}/{i}"
        )

        # docai only process 200 documents at a time so batch all uploads into buckets of size 200 or less
        while (
            len(list(bucket.list_blobs(prefix=f"{bucket_prefix}/")))
            >= Config.BATCH_LIMIT
        ):
            i += 1
            bucket_prefix = (
                f"{company_id}/{RAW_DOCS_UNPROCESSED_INVOICE_PATH}/{DOC_TYPE}/{i}"
            )

        async with aiofiles.tempfile.NamedTemporaryFile("wb") as out_file:
            print(out_file.name)
            content = await file.read()
            await out_file.write(content)
            blob = bucket.blob(f"{bucket_prefix}/{filename}")
            _ = await storage_utils.upload_blob_from_file_retry(
                blob=blob,
                file_path=out_file.name,
                content_type=file.content_type,
            )

    # Begin processing all documents
    await push_update_to_firestore(
        project_name="stak-app",
        collection=company_id,
        data={"is_processing_docs": True},
        document="logging",
    )

    project_docs = await get_project_docs_from_firestore(
        project=PROJECT_NAME,
        company_id=company_id,
        document="projects",
        get_only_active_projects=True,
    )

    background_tasks.add_task(
        docai_async.batch_process_invoices,
        doc_type="invoice",
        gcp_project_id=PROJECT_NAME,
        location="us",
        processor_id=INVOICE_PROCESSOR_ID,
        gcs_output_bucket=GCS_OUTPUT_BUCKET,
        gcs_output_uri_prefix=f"{company_id}/docai/raw-processed/",
        company_id=company_id,
        bucket_name="stak-customer-documents",
        project_docs=project_docs,
    )

    return {
        "message": f"Files successfully uploaded. Duplicate files: {duplicates_names}",
    }


@router.delete("/{company_id}/delete-invoices")
async def delete_invoices_endpoint(
    company_id: str,
    data: List[str],
    background_tasks: BackgroundTasks,
    current_user=Depends(auth.get_current_user),
):
    auth.check_user_data(company_id=company_id, current_user=current_user)

    await push_update_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data={"is_deleting_docs": True},
        document="logging",
    )
    # because there are many individual files in storage, this process can take awhile
    # so setting it as a background process
    background_tasks.add_task(delete_invoice_wrapper, company_id=company_id, data=data)

    return {"message": f"{len(data)} invoices set for deletion."}


@router.patch("/{company_id}/update-invoice-projects")
async def update_invoice_project(
    company_id: str,
    invoices: InvoiceProjects,
    current_user=Depends(auth.get_current_user),
):
    auth.check_user_data(company_id=company_id, current_user=current_user)

    await update_invoice_projects_in_firestore(
        project_name=PROJECT_NAME,
        company_id=company_id,
        invoices=invoices,
        document_name="documents",
        collection_name="processed_documents",
    )

    return {
        "message": f"Succesfully updated {len(list(invoices.__root__.keys()))} invoices."
    }


@router.patch("/{company_id}/update-processed-invoice")
async def update_invoice_data(
    company_id: str,
    data: ProcessedInvoiceData,
    current_user=Depends(auth.get_current_user),
) -> dict:
    auth.check_user_data(company_id=company_id, current_user=current_user)

    await update_processed_invoices_in_firestore(
        project_name=PROJECT_NAME,
        company_id=company_id,
        document_name="documents",
        collection_name="processed_documents",
        invoice_id=data.invoiceId,
        data=data.dict(),
    )

    # Run this code twice, once to add to a change order, and once to remove from a change order
    # if the item was switched from one change order to the other.
    # if data.processedInvoiceData.change_order is not None:
    #     await update_invoice_in_change_order_in_firestore(
    #         project_name=PROJECT_NAME,
    #         collection=company_id,
    #         document="projects",
    #         doc_collection=data.project.uuid,
    #         doc_collection_document="change-orders-summary",
    #         sub_document_name=data.processedInvoiceData.change_order.uuid,
    #         data={"invoices": [data.invoiceId]},
    #         isAdd=True,
    #     )
    # if data.processedInvoiceData.remove_from_change_order is not None:
    #     await update_invoice_in_change_order_in_firestore(
    #         project_name=PROJECT_NAME,
    #         collection=company_id,
    #         document="projects",
    #         doc_collection=data.project.uuid,
    #         doc_collection_document="change-orders-summary",
    #         sub_document_name=data.processedInvoiceData.remove_from_change_order,
    #         data={"invoices": [data.invoiceId]},
    #         isAdd=False,
    #     )

    return {"message": "Processed invoice data saved successfully."}


@router.patch("/{company_id}/remove-invoices-from-change-order")
async def remove_invoices_from_change_order(
    company_id: str,
    project_id: str,
    invoice_change_orders: Dict[str, List[str]],
    current_user=Depends(auth.get_current_user),
) -> dict:
    auth.check_user_data(company_id=company_id, current_user=current_user)

    tasks = []
    for change_order_id, invoice_ids in invoice_change_orders.items():
        coroutine = remove_change_order_id_from_invoices_in_firestore(
            project_name=PROJECT_NAME,
            company_id=company_id,
            invoice_ids=invoice_ids,
            change_order_id=change_order_id,
            document_name="documents",
            collection_name="processed_documents",
        )
        tasks.append(asyncio.create_task(coroutine))
        coroutine = update_invoice_in_change_order_in_firestore(
            project_name=PROJECT_NAME,
            collection=company_id,
            document="projects",
            doc_collection=project_id,
            doc_collection_document="change-orders-summary",
            change_order_id=change_order_id,
            invoice_ids=invoice_ids,
        )
        tasks.append(asyncio.create_task(coroutine))
    await asyncio.gather(*tasks)

    return {"message": "Successfully removed all invoices from change order."}


@router.patch("/{company_id}/add-gpt-line_items")
async def add_gpt_line_items(
    company_id: str,
    invoice_id: str,
    data: GPTLineItems,
    current_user=Depends(auth.get_current_user),
) -> dict:
    auth.check_user_data(company_id=company_id, current_user=current_user)

    new_dict = {}
    for key in data.__root__.keys():
        new_dict[key] = data.__root__[key].dict()

    await add_gpt_line_items_to_invoice_data_in_firestore(
        project_name=PROJECT_NAME,
        company_id=company_id,
        document_name="documents",
        collection_name="processed_documents",
        invoice_id=invoice_id,
        data=new_dict,
    )

    return {"message": "Successfully saved GPT Line Items."}


@router.patch("/{company_id}/approve-invoice")
async def approve_invoice(
    company_id: str,
    invoice_id: str,
    is_approved: bool,
    current_user=Depends(auth.get_current_user),
) -> dict:
    auth.check_user_data(company_id=company_id, current_user=current_user)

    await update_approved_invoice_in_firestore(
        project_name=PROJECT_NAME,
        company_id=company_id,
        document_name="documents",
        collection_name="processed_documents",
        invoice_id=invoice_id,
        is_approved=is_approved,
    )
    if is_approved:
        return {"message": "Invoice approved successfully."}
    else:
        return {"message": "Invoice approval removed."}


# May use this again in the future so keep it for now
# @router.post("/{company_id}/cancel-upload")
# async def cancel_task(
#     company_id: str, task_id: str, current_user=Depends(auth.get_current_user)
# ):
#     #auth.check_user_data(company_id=company_id, current_user=current_user)
#     print(background_tasks_dict)
#     background_tasks = background_tasks_dict[task_id]
#     if background_tasks:
#         # Cancel all tasks in the background_tasks instance
#         background_tasks.cancel()
#         return {"message": f"Task {task_id} canceled"}
#     return JSONResponse(status_code=404, content={"message": "Task not found"})


# @router.post("/{company_id}/retry-upload")
# async def retry_upload(
#     company_id: str,
#     task_id: str,
#     background_tasks: BackgroundTasks,
#     #current_user=Depends(auth.get_current_user),
# ):
#     #auth.check_user_data(company_id=company_id, current_user=current_user)

#     existing_task = background_tasks_dict[task_id]
#     if existing_task:
#         return JSONResponse(
#             status_code=400, content={"message": "Task is still running"}
#         )
#     else:
#         project_docs = await get_project_docs_from_firestore(
#             company_id=company_id, get_only_active_projects=True
#         )
#         background_tasks.add_task(
#             docai_async.batch_process_documents_parallel_wrapper,
#             doc_type="invoice",
#             gcp_project_id=PROJECT_ID,
#             location="us",
#             processor_id=INVOICE_PROCESSOR_ID,
#             gcs_output_bucket=GCS_OUTPUT_BUCKET,
#             gcs_output_uri_prefix=f"{company_id}/docai/raw-processed/",
#             company_id=company_id,
#             bucket_name="stak-customer-documents",
#             project_docs=project_docs,
#         )
