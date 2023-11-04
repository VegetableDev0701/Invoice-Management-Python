import base64
import io
import os
from functools import partial
import asyncio
import logging
import sys
import re
from typing import List

import aiofiles
from google.oauth2 import service_account
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.auth.exceptions import GoogleAuthError
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.cloud import storage
from fastapi import HTTPException
from PIL import Image


from utils.io_utils import delete_document_hash_from_firestore
from utils import storage_utils
from utils.database.firestore import (
    push_update_to_firestore,
    delete_project_items_from_firestore,
)
from config import CUSTOMER_DOCUMENT_BUCKET, PROJECT_NAME

client = storage.Client(project=PROJECT_NAME)
bucket = client.get_bucket(CUSTOMER_DOCUMENT_BUCKET)

upload_contract_logger = logging.getLogger("error_logger")
upload_contract_logger.setLevel(logging.DEBUG)

# Create a file handler
# handler = logging.FileHandler(
#     "/Users/mgrant/STAK/app/stak-backend/api/logs/upload_contract.log"
# )
handler = logging.StreamHandler(sys.stdout)

handler.setLevel(logging.DEBUG)

# Create a logging format
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)

# Add the handlers to the logger
upload_contract_logger.addHandler(handler)


def check_if_word_doc(file_name):
    return "doc" in os.path.splitext(os.path.basename(file_name))[-1]


def get_google_drive_creds():
    """
    Utility function to grab the creds from the GCS service account.
    """
    SCOPES = ["https://www.googleapis.com/auth/drive"]
    creds = None
    try:
        creds = service_account.Credentials.from_service_account_file(
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"], scopes=SCOPES
        )
    except KeyError:
        print("Environment variable 'GOOGLE_APPLICATION_CREDENTIALS' not set.")
        return False
    except FileNotFoundError:
        print(f"No file found at path: {os.environ['GOOGLE_APPLICATION_CREDENTIALS']}")
        return False
    except GoogleAuthError as error:
        print(f"Google authentication failed: {error}")
        return False
    except Exception as e:
        print(f"Failed to obtain credentials: {e}")
        return False
    return creds


async def convert_word_to_pdf(
    in_file: str,
    out_file: aiofiles.tempfile.AsyncBufferedIOBase,
    bucket_prefix: str,
    filename: str,
) -> None:
    """
    Converts a given file to PDF format using Google Drive API.

    This function reads the contents of the input file (docx), writes it to a temporary file,
    and then uses the Google Drive API to convert it to PDF. The output file
    is saved with the provided output filename. If any error occurs during the conversion,
    it logs the error and returns False. If the conversion is successful, it logs a success
    message and returns True.

    Args:
        in_file (str): The input file to be converted to PDF.
        output_file (aiofiles.tempfile.AsyncBufferedIOBase): The async temp outfile.

    Returns:
        bool: True if the conversion is successful, False otherwise.
    """
    output_file_name = f"{out_file.name}.pdf"
    creds = get_google_drive_creds()
    # Initialize the Drive v3 service
    try:
        service = build("drive", "v3", credentials=creds)
    except Exception as e:
        upload_contract_logger.exception(f"Failed to build service: {e}")
        # return False

    # Try to upload the .docx file to Google Drive
    file_id = None
    try:
        file_metadata = {
            "name": out_file.name.split("/")[-1],
            "mimeType": "application/vnd.google-apps.document",
        }
        async with aiofiles.tempfile.NamedTemporaryFile("wb") as temp_file:
            contents = await in_file.read()
            await temp_file.write(contents)
            media = MediaFileUpload(
                temp_file.name,
                mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                resumable=True,
            )
        file = (
            service.files()
            .create(body=file_metadata, media_body=media, fields="id")
            .execute()
        )
        file_id = file.get("id")
    except HttpError as error:
        upload_contract_logger.error(f"An HTTP error occured: {error}")
        # return False
    except Exception as e:
        upload_contract_logger.exception(f"Failed to upload file: {e}")
        # return False

    # Try to convert the .docx file into a PDF file
    if file_id is not None:
        try:
            request = service.files().export_media(
                fileId=file_id, mimeType="application/pdf"
            )
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while done is False:
                _, done = downloader.next_chunk()

            # Write the PDF file to disk
            with open(output_file_name, "wb") as f:
                f.write(fh.getvalue())
        except HttpError as error:
            upload_contract_logger.error(f"An HTTP error occured: {error}")
        except Exception as e:
            upload_contract_logger.exception(f"Failed to convert file to PDF: {e}")

        # Delete the .docx file from Google Drive
        try:
            service.files().delete(fileId=file_id).execute()
        except HttpError as error:
            upload_contract_logger.error(f"An HTTP error occured: {error}")
        except Exception as e:
            upload_contract_logger.exception(f"Failed to delete file: {e}")

    blob = bucket.blob(f"{bucket_prefix}/{filename}")
    blob.upload_from_filename(out_file.name + ".pdf", content_type="application/pdf")
    # return True


async def delete_contracts_wrapper(data: List[str], company_id: str, project_id: str):
    """
    Wrapper to be run as a background task:

    Args:
        data: a list of unique contract ids.
    """
    task1 = delete_project_items_from_firestore(
        project_name=PROJECT_NAME,
        company_id=company_id,
        ids=data,
        document_name="projects",
        project_key=project_id,
        doc_collection_names=["contracts"],
    )
    task2 = delete_document_hash_from_firestore(
        uuids=data, project_name=PROJECT_NAME, company_id=company_id
    )
    task3 = delete_contracts_from_storage(
        company_id=company_id, project_id=project_id, data=data
    )
    await asyncio.gather(task1, task2, task3)


async def delete_contracts_from_storage(
    company_id: str, project_id: str, data: List[str]
):
    bucket = client.get_bucket(CUSTOMER_DOCUMENT_BUCKET)
    blobs_to_delete = [
        x.name
        for x in client.list_blobs(
            CUSTOMER_DOCUMENT_BUCKET,
            prefix=f"{company_id}/projects/{project_id}/contracts",
        )
        for doc_id in data
        if re.search(doc_id, x.name)
    ]
    try:
        not_found_blobs = bucket.delete_blobs(blobs_to_delete)
        if not_found_blobs:
            upload_contract_logger.warning(
                f"Blobs not found, couldn't be deleted: {not_found_blobs}"
            )
    except Exception as e:
        upload_contract_logger.error(
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


async def save_contract_img(
    img_str: str, temp_filename: str, destination_prefix: str, destination_filename: str
) -> None:
    """
    Saves a base64-encoded image to a specified Google Cloud Storage bucket.

    This function decodes the base64 string to obtain the image, saves it to a temporary file,
    and then uploads it to the specified location in the Google Cloud Storage bucket.

    Args:
        img_str (str): The base64-encoded image string.
        temp_filename (str): The filename for the temporary file where the image will be saved before upload.
        destination_prefix (str): The destination prefix in the bucket where the image will be saved.
        destination_filename (str): The filename for the image in the destination.

    Returns:
        None
    """
    loop = asyncio.get_event_loop()

    image_bytes = base64.b64decode(img_str)
    image_io = io.BytesIO(image_bytes)
    image = Image.open(image_io)

    write_img_func = partial(image.save, temp_filename, format="JPEG", quality=10)
    await loop.run_in_executor(None, write_img_func)

    bucket = storage_utils.get_storage_bucket(CUSTOMER_DOCUMENT_BUCKET)
    blob = bucket.blob(f"{destination_prefix}/{destination_filename}")

    upload_func = partial(blob.upload_from_filename, temp_filename)
    await loop.run_in_executor(None, upload_func)
