import base64
import json
from typing import Dict, List
import uuid
import hashlib
import os
import requests

from google.cloud import firestore, secretmanager
from fastapi import HTTPException, UploadFile
import shortuuid

from config import Config


def create_short_uuid(length: int = 16) -> str:
    """
    Creates a short unique identifier to the length
    specified in the parameters

    Parameters:
    -------
    length: int
        The total length of the short uuid.

    Returns:
    -------
    The string uuid.
    """
    u = uuid.uuid4()
    return shortuuid.encode(u)[:length]


def get_uuid_from_filename(filename: str) -> str:
    """
    Grabs the uuid from the filename.

    Parameters:
    -------
    filename: str
        The filename with the uuid

    Returns:
    -------
    The string uuid
    """
    return filename.split("::")[-2]


async def calculate_file_hash(files: List[UploadFile]) -> Dict[str, str]:
    """
    Calculate the MD5 hash of the files being uploaded.
    """
    results = {}
    hashes = []
    repeat_filenames = []
    for file in files:
        md5_hash = hashlib.md5()
        for byte_block in iter(lambda: file.file.read(4096), b""):
            md5_hash.update(byte_block)
        file.file.seek(0)
        hash = base64.b64encode(md5_hash.digest()).decode()
        if hash in hashes:
            repeat_filenames.append(file.filename)
            continue
        else:
            hashes.append(hash)
            results[hash] = file.filename
    return results, repeat_filenames


async def delete_document_hash_from_firestore(
    uuids: List[str], project_name: str, company_id: str
):
    db = firestore.AsyncClient(project=project_name)
    try:
        document_hash_ref = db.collection(company_id).document("documents")
        doc = await document_hash_ref.get()
        if doc.exists:
            for field in uuids:
                await doc.reference.update({field: firestore.DELETE_FIELD})
        else:
            print(f"No such document: {doc.id}")
    except Exception as e:
        print(e)
    finally:
        db.close()


def create_secret(secret_id, value):
    """
    Creates a secret from the agave account token retrieved for a particular user and
    software.
    """
    # Initialize the Secret Manager client.
    client = secretmanager.SecretManagerServiceClient()

    # Create the Secret.
    parent = f"projects/{os.getenv('GOOGLE_CLOUD_PROJECT')}"
    secret = client.create_secret(
        request={
            "parent": parent,
            "secret_id": secret_id,
            "secret": {"replication": {"automatic": {}}},
        }
    )
    # Add the version with the payload (your token)
    payload = value.encode("UTF-8")
    client.add_secret_version(
        request={"parent": secret.name, "payload": {"data": payload}}
    )


async def access_secret_version(secret_id: str, version_id: str = "latest"):
    """
    Access secrets from google secret manager.
    """
    client = secretmanager.SecretManagerServiceAsyncClient()
    name = f"projects/{os.getenv('GOOGLE_CLOUD_PROJECT')}/secrets/{secret_id}/versions/{version_id}"
    response = await client.access_secret_version(name=name)
    payload = response.payload.data.decode("UTF-8")
    return payload


async def create_secret_id(company_id: str) -> str:
    """
    Create the secret id custom for the specific company and company file.
    """
    headers = {
        "API-Version": Config.AGAVE_API_VERSION,
        "Client-Id": Config.AGAVE_CLIENT_ID,
        "accept": "application/json",
        "Client-Secret": Config.AGAVE_CLIENT_SECRET,
        "Account-Token": Config.AGAVE_ACCOUNT_TOKEN,
        "Content-Type": "application/json",
        "Include-Source-Data": "true",
    }
    response = requests.get(Config.AGAVE_LINK_CONNECTION_URL, headers=headers)

    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail=response.text,
        )
    else:
        data = json.loads(response.content)

    ein = data["properties"]["company_ein"].replace("-", "")
    # TODO make the software dynamically assigned
    return f"AGAVE_{company_id.upper()}_QBD_{ein}_ACCOUNT_TOKEN"
