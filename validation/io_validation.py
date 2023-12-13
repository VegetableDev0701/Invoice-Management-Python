import re
from typing import Dict, Union, List

from google.cloud import firestore

# TODO add logging here


def check_for_duplicates_by_filename(
    prev_files: List[str], current_files: List[str], include_extension: bool = True
) -> Union[List[str], None]:
    """
    Checks for duplicate files between two lists of file names.

    Parameters:
        prev_files (List[str]):
            A list of strings representing file names in the previous version.
        current_files (List[str]):
            A list of strings representing file names in the current version.

    Returns:
        Union[List[str], None]:
            A list of file names that are duplicated between the two lists, or None if there are no duplicates.
    """
    if include_extension:
        intersection = set(prev_files).intersection(current_files)
    else:
        intersection = set([f.split(".")[0] for f in prev_files]).intersection(
            [f.split(".")[0] for f in current_files]
        )
    if len(intersection) > 0:
        return list(intersection)
    return None


async def check_for_duplicates_by_hash(
    new_files_hashes: Dict[str, str],
    project_name: str,
    company_id: str,
    document_name: str,
):
    """
    Check the md5 hash for previously uplaoded files and new files currently
    being uploaded.

    new_files_hashes: dict
        A dictionary of hte form {hash: filename} for newly uploaded files

    Returns:
        None or a subset of the new_files_hashes dictionary for those files that are duplicates
    """
    db = firestore.AsyncClient(project=project_name)
    try:
        doc_hashes_ref = db.collection(company_id).document(document_name)
        doc_hashes = await doc_hashes_ref.get()

        if not doc_hashes.exists:
            await doc_hashes_ref.set({})
            existing_hashes = []
        else:
            existing_hashes = [value["hash"] for value in doc_hashes.to_dict().values()]

        hash_intersection = [
            *set(existing_hashes).intersection(set(new_files_hashes.keys()))
        ]

        if len(hash_intersection) == 0:
            return None
        else:
            return {
                key: value
                for key, value in new_files_hashes.items()
                if key in hash_intersection
            }
    finally:
        db.close()


def validate_phone_number(phone_number: str, required: str | None) -> bool:
    """
    Check for a valid 10 digit phone number.
    """
    valid_phone_regex = r"^\d{10}$"
    if required:
        if re.match(valid_phone_regex, phone_number):
            return True
        else:
            return False
    else:
        if phone_number == "" or phone_number is None:
            return True
        else:
            if re.match(valid_phone_regex, phone_number):
                return True
            else:
                return False


def validate_url(url: str, required: str | None) -> bool:
    """
    Validates URLs
    """
    valid_url_regex = (
        r"^((https?|ftp|smtp):\/\/)?(www.)?[a-z0-9]+\.[a-z]+(\/[a-zA-Z0-9#]+\/?)*$"
    )
    if required:
        if re.match(valid_url_regex, url):
            return True
        else:
            return False
    else:
        if url == "" or url is None:
            return True
        else:
            if re.match(valid_url_regex, url):
                return True
            else:
                return False


def validate_email(email: str, required: str | None) -> bool:
    """
    Validates emails.
    """
    valid_email_regex = r'^(([^<>()[\]\\.,;:\s@"]+(\.[^<>()[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$'
    if required:
        if re.match(valid_email_regex, email.lower()):
            return True
        else:
            return False
    else:
        if email == "" or email is None:
            return True
        else:
            if re.match(valid_email_regex, email.lower()):
                return True
            else:
                return False


def validate_tax_number(tax_number: str, required: str | None) -> bool:
    """
    Validates the tax number (EIN) to be ##-####### form.
    """
    valid_tax_number_regex = r"^\d{2}-\d{7}$"
    if required:
        if re.match(valid_tax_number_regex, tax_number):
            return True
        else:
            return False
    else:
        if tax_number == "" or tax_number is None:
            return True
        else:
            if re.match(valid_tax_number_regex, tax_number):
                return True
            else:
                return False


def traverse_data_model(data):
    """
    Walks throught the pydantic data model finding email and phone numbers and
    checking to make sure they are valid.
    """
    validate_fields = {}
    for key, value in data:
        if key == "mainCategories":
            for category in value:
                for items in category.inputElements:
                    if items.name == "addressFields":
                        continue
                    for item in items.items:
                        if item.validFunc == "email":
                            validate_fields[item.id] = validate_email(
                                item.value, item.required
                            )
                        if item.validFunc == "phone":
                            validate_fields[item.id] = validate_phone_number(
                                item.value, item.required
                            )
                        if item.validFunc == "tax-number":
                            validate_fields[item.id] = validate_tax_number(
                                item.value, item.required
                            )

    return validate_fields
