import asyncio
import logging
import sys

from google.cloud import firestore
from tenacity import (
    retry_if_exception_type,
    wait_exponential_jitter,
    stop_after_attempt,
    AsyncRetrying,
    RetryError,
    before_sleep_log,
)

from config import PROJECT_NAME
from global_vars.globals_io import INITIAL, JITTER, RETRY_TIMES
from utils import io_utils, storage_utils
from utils.database.firestore import push_to_firestore
from utils.retry_utils import RETRYABLE_EXCEPTIONS

# Create a logger
onboard_logger = logging.getLogger("error_logger")
onboard_logger.setLevel(logging.DEBUG)

try:
    handler = logging.FileHandler(
        "/Users/mgrant/STAK/app/stak-backend/api/logs/onbaording_logs.log"
    )
except Exception as e:
    print(e)
    handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)

# Create a logging format
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)

# Add the handlers to the logger
onboard_logger.addHandler(handler)


async def check_user_email(
    user_email: str, initial: int = INITIAL, jitter: int = JITTER
) -> bool:
    db = firestore.AsyncClient(project=PROJECT_NAME)
    domain = user_email.split("@")[-1]
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(initial=initial, jitter=jitter),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(onboard_logger, logging.DEBUG),
        ):
            with attempt:
                # First check the domain in the organizations collection
                if await organization_domain_exists(db, domain):
                    return True

                # If no domain, check for the user's email in the clients subcollection
                if await client_email_exists(db, user_email):
                    return True

                # If both checks fail, return False
                return False

    except RetryError as e:
        onboard_logger.error(
            f"{e} occured while trying to delete whole collections from firestore"
        )
        raise
    except Exception as e:
        onboard_logger.exception(
            f"Unexpected error occured while trying to delete whole collections from firestore: {e}"
        )
        raise
    finally:
        db.close()


async def organization_domain_exists(db: firestore.AsyncClient, domain: str) -> bool:
    query_ref = db.collection("organizations").where("domain", "==", domain)
    async for doc in query_ref.stream():
        if doc.id:
            return True
    return False


async def client_email_exists(db: firestore.AsyncClient, user_email: str) -> bool:
    org_ref = db.collection("organizations")
    async for org_doc in org_ref.list_documents():
        query_ref = org_doc.collection("clients").where("email", "==", user_email)
        async for client_doc in query_ref.stream():
            if client_doc.id:
                return True
    return False


async def onboard_new_user(
    domain: str, user_email: str, initial: int = INITIAL, jitter: int = JITTER
):
    db = firestore.AsyncClient(project=PROJECT_NAME)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(initial=initial, jitter=jitter),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(onboard_logger, logging.DEBUG),
        ):
            with attempt:
                query_ref = db.collection("organizations").where("domain", "==", domain)
                docs = query_ref.stream()
                company_id = ""
                async for doc in docs:
                    company_id = doc.id
                    doc_dict = doc.to_dict()
                    company_name = doc_dict.get("company_name")
                    if company_name:
                        business_address = doc_dict.get("business_address")
                        business_city = doc_dict.get("business_city")
                        business_state = doc_dict.get("business_state")
                        business_zip = doc_dict.get("business_zip")
                    else:
                        business_address = None
                        business_city = None
                        business_state = None
                        business_zip = None

                new_user_id = io_utils.create_short_uuid()

                tasks = []
                # This checks if the company already exists and if not run these tasks
                if company_name is None:
                    user_data = {
                        "company_id": company_id,
                        "user_email": user_email,
                        "user_id": new_user_id,
                        "company_name": company_name,
                        "user_name": None,
                        "business_address": business_address,
                        "business_city": business_city,
                        "business_state": business_state,
                        "business_zip": business_zip,
                    }
                    # add new user to organizations collection

                    tasks.append(
                        asyncio.create_task(
                            push_to_firestore(
                                project_name=PROJECT_NAME,
                                collection="organizations",
                                document=company_id,
                                doc_collection="users",
                                doc_collection_document=new_user_id,
                                data=user_data,
                            )
                        )
                    )
                    # add new user to users collection

                    tasks.append(
                        asyncio.create_task(
                            push_to_firestore(
                                project_name=PROJECT_NAME,
                                collection="users",
                                document=new_user_id,
                                data=user_data,
                            )
                        )
                    )
                    # upload all json base form data to companies collection

                    tasks.append(
                        asyncio.create_task(
                            storage_utils.download_and_onboard_new_company_files(
                                company_id=company_id
                            )
                        )
                    )
                # If the company does exist already and this is just a new user for that company
                # assign that company Id to the user and add them to their organization as well as to the users
                # collection.
                else:
                    user_data = {
                        "company_id": company_id,
                        "user_email": user_email,
                        "user_id": new_user_id,
                        "company_name": company_name,
                        "user_name": None,
                        "business_address": business_address,
                        "business_city": business_city,
                        "business_state": business_state,
                        "business_zip": business_zip,
                    }
                    # add new user to organization users collection

                    tasks.append(
                        asyncio.create_task(
                            push_to_firestore(
                                project_name=PROJECT_NAME,
                                collection="organizations",
                                document=company_id,
                                doc_collection="users",
                                doc_collection_document=new_user_id,
                                data=user_data,
                            )
                        )
                    )
                    # add new user to users collection

                    tasks.append(
                        asyncio.create_task(
                            push_to_firestore(
                                project_name=PROJECT_NAME,
                                collection="users",
                                document=new_user_id,
                                data=user_data,
                            )
                        )
                    )
                await asyncio.gather(*tasks)

                onboard_form_ref = (
                    db.collection(company_id)
                    .document("base-forms")
                    .collection("forms")
                    .document("onboard-new-user")
                )

                doc = await onboard_form_ref.get()

                return {
                    "user_data": user_data,
                    "new_company": not company_id,
                    "onboard_form_data": doc.to_dict(),
                }

    except RetryError as e:
        onboard_logger.error(
            f"{e} occured while trying to delete whole collections from firestore"
        )
        raise
    except Exception as e:
        onboard_logger.exception(
            f"Unexpected error occured while trying to delete whole collections from firestore: {e}"
        )
        raise
    finally:
        db.close()
