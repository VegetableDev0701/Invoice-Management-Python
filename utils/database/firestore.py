import asyncio
from typing import Dict, List
import json
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
from utils.io_utils import chunk_list
from utils.retry_utils import RETRYABLE_EXCEPTIONS
from global_vars.globals_invoice import PROJECT_DETAILS_MATCHING_KEYS
from global_vars.globals_io import (
    BATCH_SIZE_CUTOFF,
    COLLECTION_BATCH_SIZE,
    FIRESTORE_QUERY_BATCH_SIZE,
    INITIAL,
    JITTER,
    RETRY_TIMES,
)

# Create a logger
firestore_io_logger = logging.getLogger("error_logger")
firestore_io_logger.setLevel(logging.DEBUG)

try:
    # Create a file handler
    handler = logging.FileHandler(
        "/Users/mgrant/STAK/app/stak-backend/api/logs/firestore_read_write_error_logs.log"
    )
except Exception as e:
    handler = logging.StreamHandler(sys.stdout)

handler.setLevel(logging.DEBUG)

# Create a logging format
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)

# Add the handlers to the logger
firestore_io_logger.addHandler(handler)


async def get_from_firestore(
    project_name: str,
    collection_name: str,
    document_name: str,
    doc_collection: str | None = None,
    doc_collection_document: str | None = None,
    doc_collection_doc_collection: str | None = None,
    doc_collection_doc_collection_document: str | None = None,
    initial: int = INITIAL,
    jitter: int = JITTER,
):
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(initial=initial, jitter=jitter),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                document_ref = db.collection(collection_name).document(document_name)
                if doc_collection and doc_collection_document:
                    if (
                        doc_collection_doc_collection
                        and doc_collection_doc_collection_document
                    ):
                        document_ref = (
                            document_ref.collection(doc_collection)
                            .document(doc_collection_document)
                            .collection(doc_collection_doc_collection)
                            .document(doc_collection_doc_collection_document)
                        )
                    else:
                        document_ref = document_ref.collection(doc_collection).document(
                            doc_collection_document
                        )
                    doc = await document_ref.get()
                    return doc.to_dict()
                else:
                    doc = await document_ref.get()
                    return doc.to_dict()
    except RetryError as e:
        firestore_io_logger.error(
            f"{e} occured while trying to get data from firestore"
        )
        raise

    except Exception as e:
        firestore_io_logger.exception(f"An error occurred getting data: {e}")
    finally:
        db.close()


async def fetch_document(coll, doc_name):
    """Fetch a document and return its contents along with its collection ID and document name."""
    doc = await coll.document(doc_name).get()
    return coll.id, doc_name, doc.to_dict()


async def fetch_collections_batched(ref, doc_names, batch_size=10):
    collections = ref.collections()
    tasks, results = [], []

    async for collection in collections:
        # Add a task for each collection
        if isinstance(doc_names, list):
            for doc_name in doc_names:
                task = asyncio.create_task(fetch_document(collection, doc_name))
                tasks.append(task)
        else:
            task = asyncio.create_task(fetch_document(collection, doc_names))
            tasks.append(task)

        # If batch size is reached, wait for tasks to complete
        if len(tasks) >= batch_size:
            batch_results = await asyncio.gather(*tasks)
            results.extend(batch_results)
            tasks = []

    # Fetch any remaining tasks
    if tasks:
        batch_results = await asyncio.gather(*tasks)
        results.extend(batch_results)

    return results


async def get_all_project_details_data(
    project_name: str,
    collection_name: str,
    document_name: str,
    doc_names: str | List[str],
):
    """
    Used to collect all the details data. Used to grab all project details, vendor
    details, contracts etc. This will pull all the details for any group needed.
    """
    db = firestore.AsyncClient(project=project_name)
    try:
        ref = db.collection(collection_name).document(document_name)

        results = await fetch_collections_batched(
            ref,
            doc_names=doc_names,
            batch_size=COLLECTION_BATCH_SIZE,  # protects against service unavailble errors from Firestore
        )

        docs = {}
        for coll_id, doc_name, doc_data in results:
            if coll_id not in docs:
                docs[coll_id] = {}
            docs[coll_id][doc_name] = doc_data
        return docs

    except Exception as e:
        firestore_io_logger.exception(
            f"An error occurred getting all project details: {e}"
        )
    finally:
        db.close()


async def fetch_project_document(doc_ref):
    try:
        doc = await doc_ref.get()
        return doc.id, doc.to_dict()
    except:
        raise


async def fetch_project_if_active(
    db: firestore.AsyncClient, company_id: str, project_id: str
):
    try:
        project_collection_ref = (
            db.collection(company_id).document("projects").collection(project_id)
        )
        project_summary_ref = project_collection_ref.document("project-summary")
        project_summary = await project_summary_ref.get()

        if project_summary.exists and project_summary.to_dict().get("isActive", False):
            docs = project_collection_ref.list_documents()

            tasks = [
                asyncio.create_task(fetch_project_document(doc))
                async for doc in docs
                if doc.id != "client-bills"
            ]
            results = await asyncio.gather(*tasks)
            return {project_id: dict(results)}
        return None
    except:
        raise


async def fetch_all_active_projects(
    company_id: str, project_name: str, initial: int = INITIAL, jitter: int = JITTER
):
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(initial=initial, jitter=jitter),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                project_doc_ref = db.collection(company_id).document("projects")
                tasks = []
                async for collection in project_doc_ref.collections():
                    tasks.append(
                        asyncio.create_task(
                            fetch_project_if_active(
                                db=db, company_id=company_id, project_id=collection.id
                            )
                        )
                    )
                project_data_list = await asyncio.gather(*tasks)
                return {k: v for d in project_data_list if d for k, v in d.items()}
    except RetryError as e:
        firestore_io_logger.error(
            f"{e} occured while trying to get data from firestore"
        )
        raise

    except Exception as e:
        firestore_io_logger.exception(f"An error occurred getting data: {e}")
    finally:
        db.close()


async def fetch_vendor_summary(db, company_id: str, vendor_id: str) -> dict:
    try:
        vendor_collection_ref = (
            db.collection(company_id).document("vendors").collection(vendor_id)
        )
        vendor_summary_ref = vendor_collection_ref.document("vendor-summary")
        vendor_summary_doc = await vendor_summary_ref.get()
        return vendor_summary_doc.to_dict()
    except:
        raise


async def fetch_all_vendor_summaries(
    company_id: str, project_name: str, initial: int = INITIAL, jitter: int = JITTER
):
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(initial=initial, jitter=jitter),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                vendor_ref = db.collection(company_id).document("vendors")
                tasks = [
                    fetch_vendor_summary(db, company_id, vendor_id=coll.id)
                    async for coll in vendor_ref.collections()
                ]

                results = await asyncio.gather(*tasks)

                return results

    except RetryError as e:
        firestore_io_logger.error(
            f"{e} occured while trying to get data from firestore"
        )
        raise

    except Exception as e:
        firestore_io_logger.exception(f"An error occurred getting data: {e}")
    finally:
        db.close()


async def stream_all_docs_from_collection(
    project_name: str,
    company_id: str,
    document_name: str,
    collection_name: str,
    coll_doc: str | None = None,
    coll_doc_coll: str | None = None,
):
    db = firestore.AsyncClient(project=project_name)
    try:
        coll_ref = (
            db.collection(company_id)
            .document(document_name)
            .collection(collection_name)
        )
        if coll_doc and coll_doc_coll:
            coll_ref = coll_ref.document(coll_doc).collection(coll_doc_coll)
        result_data = {}
        tasks = [
            asyncio.create_task(fetch_project_document(doc))
            async for doc in coll_ref.list_documents()
            if doc.id != "client-bills"
        ]
        results = await asyncio.gather(*tasks)
        for doc_id, doc_dict in results:
            result_data[doc_id] = doc_dict
        return result_data
    except Exception as e:
        firestore_io_logger.exception(
            f"An error occurred streaming all project data: {e}"
        )
    finally:
        db.close()


async def stream_entire_collection(
    project_name: str,
    collection_name: str,
    document_name: str | None = None,
    doc_collection_name: str | None = None,
    sub_collection_document: str | None = None,
    sub_collection: str | None = None,
) -> dict:
    """
    Get all the base form JSON data used to build the empty forms for
    adding projects, vendors, contracts, budgets etc.
    """
    docs = {}
    db = firestore.AsyncClient(project=project_name)
    try:
        collection_ref = db.collection(collection_name)
        if document_name and doc_collection_name:
            collection_ref = (
                db.collection(collection_name)
                .document(document_name)
                .collection(doc_collection_name)
            )

            if sub_collection and sub_collection_document:
                collection_ref = collection_ref.document(
                    sub_collection_document
                ).collection(sub_collection)

        async for doc in collection_ref.stream():
            doc_dict = doc.to_dict()
            if doc_collection_name == "processed_documents":
                del doc_dict["full_document_text"]
                del doc_dict["entities"]
            docs[doc.id] = doc_dict
        return docs
    except Exception as e:
        firestore_io_logger.exception(
            f"An error occurred streaming entire {document_name}/{doc_collection_name} collection project data: {e}"
        )
    finally:
        db.close()


async def get_all_company_data(project_name: str, collection_name: str):
    """
    Traverse the firestore db for all company data including:
        * Base forms
        * Projects
        * Vendors
        ...Coming soon: contracts, labor, invoices etc.

    Args:
        project_name: str
        collection_name: str
            The collection for that company's data
    """
    db = firestore.AsyncClient(project=project_name)
    try:
        company_ref = db.collection(collection_name)

        base_forms = {"base_forms": {}}
        project_forms = {"projects": {}}
        vendor_forms = {"vendors": {}}
        async for doc in company_ref.list_documents():
            if doc.id == "base-forms":
                async for coll in doc.collections():
                    async for docc in coll.stream():
                        base_forms["base_forms"][docc.id] = docc.to_dict()
            elif doc.id == "projects":
                async for coll in doc.collections():
                    # project_uuid = coll.id.split("::")
                    # project = project_uuid[0]
                    # uuid = project_uuid[1]
                    async for docc in coll.stream():
                        if docc.id == "project-details":
                            project_forms["projects"][coll.id] = docc.to_dict()
            elif doc.id == "vendors":
                async for coll in doc.collections():
                    # vendor_uuid = coll.id.split("::")
                    # vendor = vendor_uuid[0]
                    # uuid = vendor_uuid[1]
                    async for docc in coll.stream():
                        if docc.id == "vendor-details":
                            vendor_forms["vendors"][coll.id] = docc.to_dict()
            else:
                pass
        return json.dumps({**base_forms, **project_forms, **vendor_forms})
    except Exception as e:
        firestore_io_logger.exception(
            f"An error occurred getting all company data: {e}"
        )
    finally:
        db.close()


async def push_to_firestore(
    project_name: str,
    collection: str,
    data: dict | None = None,
    path_to_json: str | None = None,
    document: str | None = None,
    doc_collection: str | None = None,
    doc_collection_document: str | None = None,
    initial: int = INITIAL,
    jitter: int = JITTER,
    overwrite_data: bool = False,
):
    """
    Pushes data to firestore. If a path_to_json is provided, it will load that json data
    and push that to firestore skipping any other data that is provided in the data argument.
    """
    if not path_to_json and not data:
        raise Exception("Must provide either a `path_to_json` OR `data` arguments.")

    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(initial=initial, jitter=jitter),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                document_ref = db.collection(collection).document(document)
                if doc_collection and doc_collection_document:
                    document_ref = document_ref.collection(doc_collection).document(
                        doc_collection_document
                    )
                if path_to_json:
                    with open(path_to_json, "r") as file:
                        firestore_data = json.load(file)
                else:
                    firestore_data = data.copy()
                doc = await document_ref.get()
                if doc.exists and not overwrite_data:
                    await document_ref.update(firestore_data)
                else:
                    await document_ref.set(firestore_data)

    except RetryError as e:
        firestore_io_logger.error(
            f"RETRYERROR: {e} occured while trying to get data from firestore"
        )
        raise

    except Exception as e:
        firestore_io_logger.exception(f"An error occurred getting data: {e}")
    finally:
        db.close()


async def push_to_firestore_batch(
    project_name: str,
    collection: str,
    documents: List[Dict],
    initial: int = 10,
    jitter: int = 5,
):
    db = firestore.AsyncClient(project=project_name)
    count = 0
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(initial=initial, jitter=jitter),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                batch = db.batch()
                for doc_data in documents:
                    doc_ref = db.collection(collection).document(doc_data["document"])
                    if (
                        "doc_collection" in doc_data
                        and "doc_collection_document" in doc_data
                    ):
                        doc_ref = doc_ref.collection(
                            doc_data["doc_collection"]
                        ).document(doc_data["doc_collection_document"])
                    batch.set(doc_ref, doc_data["data"])
                    count += 1
                    if count % 500 == 0:
                        await batch.commit()
                        batch = db.batch()
                await batch.commit()

    except RetryError as e:
        firestore_io_logger.error(
            f"RETRYERROR: {e} occurred while trying to write to Firestore"
        )
        raise

    except Exception as e:
        firestore_io_logger.exception(f"An error occurred writing to Firestore: {e}")
    finally:
        db.close()


async def push_qbd_items_data_to_firestore(
    project_name: str, collection: str, document: str, items_data: dict
):
    db = firestore.AsyncClient(project=project_name)
    try:
        tasks = []
        ref = (
            db.collection(collection)
            .document(document)
            .collection("items")
            .document("items")
        )
        for url, status, data in items_data:
            if status != 200:
                continue
            typ = url.split("type=")[-1]
            type_ref = ref.collection(typ)

            # batching
            if len(data["data"]) > BATCH_SIZE_CUTOFF:
                batch = db.batch()
                count = 0
                for item in data["data"]:
                    doc_ref = type_ref.document(item["id"])
                    batch.set(doc_ref, item)
                    count += 1
                    if count % 500 == 0:
                        await batch.commit()
                        batch = db.batch()
                await batch.commit()
            # not batching
            else:
                for item in data["data"]:
                    doc_ref = type_ref.document(item["id"])
                    tasks.append(asyncio.create_task(doc_ref.set(item)))
                _ = await asyncio.gather(*tasks)

    except Exception as e:
        firestore_io_logger.exception(
            f"An error occurred saving QBD items to Firestore: {e}"
        )
    finally:
        db.close()


async def safe_set(doc_ref, item):
    try:
        await doc_ref.set(item)
    except Exception as e:
        firestore_io_logger.error(f"Error writing document {doc_ref.id}: {e}")
        # Handle or log the error for this specific document


async def push_qbd_data_to_firestore_batched(
    project_name: str,
    collection: str,
    document: str,
    doc_collection: str,
    data: dict,
):
    db = firestore.AsyncClient(project=project_name)
    batch = db.batch()
    count = 0
    try:
        ref = db.collection(collection).document(document).collection(doc_collection)
        for item in data["data"]:
            doc_ref = ref.document(item["id"])
            batch.set(doc_ref, item)
            count += 1
            if count % 500 == 0:
                await batch.commit()
                batch = db.batch()
        await batch.commit()
    except Exception as e:
        firestore_io_logger.exception(f"An error occurred getting data: {e}")
    finally:
        db.close()


async def push_to_firestore_batch(
    project_name: str,
    collection: str,
    documents: List[Dict],
    initial: int = 10,
    jitter: int = 5,
):
    db = firestore.AsyncClient(project=project_name)
    count = 0
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(initial=initial, jitter=jitter),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                batch = db.batch()
                for doc_data in documents:
                    doc_ref = db.collection(collection).document(doc_data["document"])
                    if (
                        "doc_collection" in doc_data
                        and "doc_collection_document" in doc_data
                    ):
                        doc_ref = doc_ref.collection(
                            doc_data["doc_collection"]
                        ).document(doc_data["doc_collection_document"])
                    batch.set(doc_ref, doc_data["data"])
                    count += 1
                    if count % 500 == 0:
                        await batch.commit()
                        batch = db.batch()
                await batch.commit()

    except RetryError as e:
        firestore_io_logger.error(
            f"RETRYERROR: {e} occurred while trying to write to Firestore"
        )
        raise

    except Exception as e:
        firestore_io_logger.exception(f"An error occurred writing to Firestore: {e}")
    finally:
        db.close()


async def push_qbd_items_data_to_firestore(
    project_name: str, collection: str, document: str, items_data: dict
):
    db = firestore.AsyncClient(project=project_name)
    try:
        tasks = []
        ref = (
            db.collection(collection)
            .document(document)
            .collection("items")
            .document("items")
        )
        for url, status, data in items_data:
            if status != 200:
                continue
            typ = url.split("type=")[-1]
            type_ref = ref.collection(typ)

            # batching
            if len(data["data"]) > BATCH_SIZE_CUTOFF:
                batch = db.batch()
                count = 0
                for item in data["data"]:
                    doc_ref = type_ref.document(item["id"])
                    batch.set(doc_ref, item)
                    count += 1
                    if count % 500 == 0:
                        await batch.commit()
                        batch = db.batch()
                await batch.commit()
            # not batching
            else:
                for item in data["data"]:
                    doc_ref = type_ref.document(item["id"])
                    tasks.append(asyncio.create_task(doc_ref.set(item)))
                _ = await asyncio.gather(*tasks)

    except Exception as e:
        firestore_io_logger.exception(
            f"An error occurred saving QBD items to Firestore: {e}"
        )
    finally:
        db.close()


async def safe_set(doc_ref, item):
    try:
        await doc_ref.set(item)
    except Exception as e:
        firestore_io_logger.error(f"Error writing document {doc_ref.id}: {e}")
        # Handle or log the error for this specific document


async def push_qbd_data_to_firestore_batched(
    project_name: str,
    collection: str,
    document: str,
    doc_collection: str,
    data: dict,
):
    db = firestore.AsyncClient(project=project_name)
    batch = db.batch()
    count = 0
    try:
        ref = db.collection(collection).document(document).collection(doc_collection)
        for item in data["data"]:
            doc_ref = ref.document(item["id"])
            batch.set(doc_ref, item)
            count += 1
            if count % 500 == 0:
                await batch.commit()
                batch = db.batch()
        await batch.commit()
    except Exception as e:
        firestore_io_logger.exception(
            f"An error occurred saving QBD items to Firestore: {e}"
        )
    finally:
        db.close()


async def push_qbd_data_to_firestore(
    project_name: str,
    collection: str,
    document: str,
    doc_collection: str,
    data: dict,
):
    db = firestore.AsyncClient(project=project_name)

    try:
        tasks = []
        ref = db.collection(collection).document(document).collection(doc_collection)
        for item in data["data"]:
            doc_ref = ref.document(item["id"])
            tasks.append(asyncio.create_task(safe_set(doc_ref, item)))

        _ = await asyncio.gather(*tasks, return_exceptions=True)

    except Exception as e:
        firestore_io_logger.exception(
            f"An error occurred saving QBD items to Firestore: {e}"
        )
    finally:
        db.close()


async def push_qbd_items_data_to_firestore(
    project_name: str, collection: str, document: str, items_data: dict
):
    db = firestore.AsyncClient(project=project_name)
    try:
        tasks = []
        ref = (
            db.collection(collection)
            .document(document)
            .collection("items")
            .document("items")
        )
        for url, status, data in items_data:
            if status != 200:
                continue
            typ = url.split("type=")[-1]
            type_ref = ref.collection(typ)
            for item in data["data"]:
                doc_ref = type_ref.document(item["id"])
                tasks.append(asyncio.create_task(doc_ref.set(item)))
        _ = await asyncio.gather(*tasks)

    except Exception as e:
        firestore_io_logger.exception(
            f"An error occurred saving QBD items to Firestore: {e}"
        )
    finally:
        db.close()


async def push_qbd_data_to_firestore(
    project_name: str,
    collection: str,
    document: str,
    doc_collection: str,
    data: dict,
):
    db = firestore.AsyncClient(project=project_name)

    try:
        tasks = []
        ref = db.collection(collection).document(document).collection(doc_collection)
        for item in data["data"]:
            doc_ref = ref.document(item["id"])
            tasks.append(asyncio.create_task(doc_ref.set(item)))
        _ = await asyncio.gather(*tasks)

    except Exception as e:
        firestore_io_logger.exception(
            f"An error occurred saving QBD items to Firestore: {e}"
        )
    finally:
        db.close()


# TODO this function is has all fucked up naming convention and needs to be refactored if not rewritten
# dont you just love an angry todo
async def delete_collections_from_firestore(
    project_name: str,
    company_id: str,
    data: List[str],
    document_name: str,
    collection_name: str | None = None,
    doc_collection_name: str | None = None,
    doc_collection_doc_name: str | None = None,
    initial: int = INITIAL,
    jitter: int = JITTER,
) -> None:
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(initial=initial, jitter=jitter),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                # If deleting one specific collection, used for invoices
                if collection_name:
                    collection_ref = (
                        db.collection(company_id)
                        .document(document_name)
                        .collection(collection_name)
                    )

                    async for doc in collection_ref.stream():
                        if doc.id in data:
                            await doc.reference.delete()

                # When deleting multiple collections, used for deleting an entire project, client bill, vendor
                else:
                    collection_ref = db.collection(company_id).document(document_name)
                    # for a nested collection
                    if (
                        doc_collection_name is not None
                        and doc_collection_doc_name is not None
                    ):
                        collection_ref = collection_ref.collection(
                            doc_collection_name
                        ).document(doc_collection_doc_name)
                    tasks = []
                    async for coll in collection_ref.collections():
                        if coll.id in data:
                            tasks.append(
                                [doc.reference.delete() async for doc in coll.stream()]
                            )
                    _ = await asyncio.gather(
                        *[item for sublist in tasks for item in sublist]
                    )

    except RetryError as e:
        firestore_io_logger.error(
            f"{e} occured while trying to delete whole collections from firestore"
        )
        raise
    except Exception as e:
        firestore_io_logger.exception(
            f"Unexpected error occured while trying to delete whole collections from firestore: {e}"
        )
        raise
    finally:
        db.close()


async def delete_summary_data_from_firestore(
    project_name: str,
    company_id: str,
    data: List[str],
    document_name: str,
    sub_document_name: str | None = None,
    initial: int = INITIAL,
    jitter: int = JITTER,
):
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(initial=initial, jitter=jitter),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                ref = db.collection(company_id).document(document_name)
                for id in data:
                    if sub_document_name:
                        await ref.update(
                            {f"{sub_document_name}.{id}": firestore.DELETE_FIELD}
                        )
                    else:
                        await ref.update({f"{id}": firestore.DELETE_FIELD})
    except RetryError as e:
        firestore_io_logger.error(
            f"{e} occured while trying to delete summary data from firestore"
        )
        raise
    except Exception as e:
        firestore_io_logger.exception(
            f"Unexpected error occured while trying to delete summary data from firestore: {e}"
        )
        raise
    finally:
        db.close()


async def delete_project_items_from_firestore(
    project_name: str,
    company_id: str,
    ids: List[str],
    document_name: str,
    project_key: str,
    doc_collection_names: List[str],
    initial: int = INITIAL,
    jitter: int = JITTER,
):
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(initial=initial, jitter=jitter),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                for chunk in chunk_list(
                    doc_collection_names, FIRESTORE_QUERY_BATCH_SIZE
                ):
                    project_ref = (
                        db.collection(company_id)
                        .document(document_name)
                        .collection(project_key)
                        .where("__name__", "in", chunk)
                    )

                    async for doc in project_ref.stream():
                        for id in ids:
                            await doc.reference.update({id: firestore.DELETE_FIELD})

    except RetryError as e:
        firestore_io_logger.error(f"{e} occured while trying to delete project items")
        raise
    except Exception as e:
        firestore_io_logger.exception(
            f"Unexpected error occured while trying to delete project items: {e}"
        )
        raise
    finally:
        db.close()


async def update_invoice_projects_in_firestore(
    project_name: str,
    company_id: str,
    invoices: List[str],
    document_name: str,
    collection_name: str,
    initial: int = INITIAL,
    jitter: int = JITTER,
):
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(initial=initial, jitter=jitter),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                invoices_collection = (
                    db.collection(company_id)
                    .document(document_name)
                    .collection(collection_name)
                )
                invoice_ids = list(invoices.__root__.keys())

                async for doc in invoices_collection.stream():
                    if doc.id in invoice_ids:
                        await doc.reference.update(
                            {"project": dict(invoices.__root__[doc.id])}
                        )

    except RetryError as e:
        firestore_io_logger.error(
            f"{e} occured while trying to update invoice projects"
        )
        raise
    except Exception as e:
        firestore_io_logger.exception(
            f"Unexpected error occured while trying to update invoice projects: {e}"
        )
        raise
    finally:
        db.close()


async def update_processed_invoices_in_firestore(
    project_name: str,
    company_id: str,
    invoice_id: str,
    document_name: str,
    collection_name: str,
    data: dict,
    initial: int = INITIAL,
    jitter: int = JITTER,
) -> None:
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(initial=initial, jitter=jitter),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                invoice_doc_ref = (
                    db.collection(company_id)
                    .document(document_name)
                    .collection(collection_name)
                    .document(invoice_id)
                )
                if data["processedInvoiceData"]["change_order"] is not None:
                    change_order = data["processedInvoiceData"]["change_order"]
                else:
                    change_order = None

                await invoice_doc_ref.update(
                    {
                        "processed": data["isProcessed"],
                        "project": data["project"],
                        "processedData": data["processedInvoiceData"],
                        "change_order": change_order,
                    }
                )
    except RetryError as e:
        firestore_io_logger.error(
            f"{e} occured while trying to update processed invoices"
        )
        raise
    except Exception as e:
        firestore_io_logger.exception(
            f"Unexpected error occured while trying to update processed invoices: {e}"
        )
        raise
    finally:
        db.close()


async def remove_change_order_id_from_invoices_in_firestore(
    project_name: str,
    company_id: str,
    invoice_ids: List[str],
    change_order_id: str,
    document_name: str,
    collection_name: str,
    initial: int = INITIAL,
    jitter: int = JITTER,
) -> None:
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(initial=initial, jitter=jitter),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                for chunk in chunk_list(invoice_ids, FIRESTORE_QUERY_BATCH_SIZE):
                    invoice_doc_ref = (
                        db.collection(company_id)
                        .document(document_name)
                        .collection(collection_name)
                        .where("__name__", "in", chunk)
                    )
                    async for doc in invoice_doc_ref.stream():
                        processed_data = doc.to_dict()["processedData"]

                        # if there are line items, have to search for the invoice there to remove it
                        # if no invoice is found, the dict will not change
                        update_line_items = {}
                        if processed_data["line_items"]:
                            for item_num, item in processed_data["line_items"].items():
                                if (
                                    item["change_order"]
                                    and item["change_order"]["uuid"] == change_order_id
                                ):
                                    item["change_order"] = None
                                    # item["bounding_box"] = None
                                    update_line_items.update({item_num: item})
                                else:
                                    update_line_items.update({item_num: item})
                            processed_data.update(
                                {
                                    "change_order": None,
                                    # "remove_from_change_order": None,
                                    "line_items": update_line_items,
                                }
                            )
                            await doc.reference.update(
                                {"processedData": processed_data}
                            )
                        # if there are no line items, then we must have a change order for whole invoice
                        else:
                            await doc.reference.update(
                                {"change_order": None, "processedData": processed_data}
                            )

    except RetryError as e:
        firestore_io_logger.error(
            f"{e} occured while trying to delete document from DB"
        )
        raise
    except Exception as e:
        firestore_io_logger.exception(
            f"Unexpected error occurred while copying document to DB: {e}"
        )
        raise
    finally:
        db.close()


async def add_gpt_line_items_to_invoice_data_in_firestore(
    project_name: str,
    company_id: str,
    invoice_id: str,
    document_name: str,
    collection_name: str,
    data: dict,
    initial: int = INITIAL,
    jitter: int = JITTER,
) -> None:
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(initial=initial, jitter=jitter),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                invoice_doc = (
                    db.collection(company_id)
                    .document(document_name)
                    .collection(collection_name)
                    .document(invoice_id)
                )

                await invoice_doc.update(
                    {
                        "line_items_gpt": data,
                    }
                )
    except RetryError as e:
        firestore_io_logger.error(
            f"{e} occured while adding gpt line items to firestore. "
        )
        raise
    except Exception as e:
        firestore_io_logger.exception(
            f"Unexpected error occured while adding gpt line items to firestore: {e}"
        )
        raise
    finally:
        db.close()
        
async def add_project_single_contract_in_firestore(
    company_id: str,
    project_id: str,
    uuid: str,
    data: dict,
) -> None: 
    db = firestore.AsyncClient(project=project_id)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(initial=initial, jitter=jitter),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                new_contract = (
                    db.collection(company_id)
                    .document('project')
                    .collection(project_id)
                    .collection('contract')
                    .document(uuid)
                )
                await new_contract.set(data)
    except RetryError as e:
        firestore_io_logger.error(
            f"{e} occured while adding new single contract to firestore. "
        )
        raise
    except Exception as e:
        firestore_io_logger.exception(
            f"Unexpected error occured while adding single contract to firestore. "
        )
        raise
    finally:
        db.close

async def update_approved_invoice_in_firestore(
    project_name: str,
    company_id: str,
    invoice_id: str,
    document_name: str,
    collection_name: str,
    is_approved: bool,
    initial: int = INITIAL,
    jitter: int = JITTER,
) -> None:
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(initial=initial, jitter=jitter),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                invoice_doc = (
                    db.collection(company_id)
                    .document(document_name)
                    .collection(collection_name)
                    .document(invoice_id)
                )

                await invoice_doc.update({"approved": is_approved})

    except RetryError as e:
        firestore_io_logger.error(
            f"{e} occured while trying update invoice approval in firestore. "
        )
        raise
    except Exception as e:
        firestore_io_logger.exception(
            f"Unexpected error occured while trying to update invoice approval in firestore: {e}"
        )
        raise
    finally:
        db.close()


async def push_update_to_firestore(
    project_name: str,
    collection: str,
    data: dict,
    document: str,
    sub_document_name: str | None = None,
    doc_collection: str | None = None,
    doc_collection_document: str | None = None,
    initial: int = INITIAL,
    jitter: int = JITTER,
) -> None:
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(initial=initial, jitter=jitter),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(firestore_io_logger, logging.DEBUG),
        ):
            with attempt:
                document_ref = db.collection(collection).document(document)

                if doc_collection and doc_collection_document:
                    document_ref = document_ref.collection(doc_collection).document(
                        doc_collection_document
                    )

                doc = await document_ref.get()
                if doc.exists:
                    if sub_document_name:
                        for key, value in data.items():
                            await document_ref.update(
                                {f"{sub_document_name}.{key}": value}
                            )
                    else:
                        await document_ref.update(data)
                else:
                    if sub_document_name:
                        for key, value in data.items():
                            await document_ref.set({sub_document_name: {}})
                            await document_ref.update(
                                {f"{sub_document_name}.{key}": value}
                            )
                    else:
                        await document_ref.set(data)

    except RetryError as e:
        firestore_io_logger.error(
            f"{e} occured while trying to make general push to firestore to document: {document} and (if exists) doc_collection: {doc_collection}. "
        )
        raise
    except Exception as e:
        firestore_io_logger.exception(
            f"Unexpected error occured while trying to make general push to firestore to document: {document} and (if exists) doc_collection: {doc_collection}: {e}"
        )
        raise
    finally:
        db.close()


async def update_project_status(
    project_name: str,
    collection: str,
    data: dict,
    item_ids: List[str],
) -> None:
    db = firestore.AsyncClient(project=project_name)
    try:
        for item_id in item_ids:
            document_ref_full_data = (
                db.collection(collection)
                .document("projects")
                .collection(item_id)
                .document("project-details")
            )
            document_ref_summary = (
                db.collection(collection)
                .document("projects")
                .collection(item_id)
                .document("project-summary")
            )
            for key, value in data.items():
                task1 = document_ref_full_data.update({key: value})
                task2 = document_ref_summary.update({key: value})
            _ = await asyncio.gather(task1, task2)
    except Exception as e:
        firestore_io_logger.exception(
            f"An error occurred updating project status {collection}: {e}"
        )
    finally:
        db.close()


async def get_project_docs_from_firestore(
    company_id: str,
    document: str,
    project: str,
    get_only_active_projects: bool = True,
) -> dict:
    docs = {}
    db = firestore.AsyncClient(project=project)
    try:
        collections = db.collection(company_id).document(document).collections()
        async for collection in collections:
            async for doc in collection.stream():
                if doc.id != "project-details":
                    continue
                project = doc.to_dict()
                if get_only_active_projects:
                    if project["isActive"]:
                        project_doc, owner = [], []
                        for main_cat in project["mainCategories"]:
                            for items in main_cat["inputElements"]:
                                if items["addressElements"]:
                                    for addr_el in items["addressElements"]:
                                        for item in addr_el["items"]:
                                            if item["id"] == "project-address":
                                                address = item["value"]
                                            if (
                                                item["id"]
                                                in PROJECT_DETAILS_MATCHING_KEYS
                                            ):
                                                project_doc.append(item["value"])
                                elif items["items"]:
                                    for item in items["items"]:
                                        if item["id"] in PROJECT_DETAILS_MATCHING_KEYS:
                                            project_doc.append(item["value"])
                                        if item["id"] == "client-first-name":
                                            owner.append(item["value"])
                                        if item["id"] == "client-last-name":
                                            owner.append(item["value"])
                                        if item["id"] == "project-name":
                                            project_name = item["value"]

                        docs[collection.id] = {
                            "doc": " ".join(project_doc),
                            "project_name": project_name,
                            "address": address,
                            "address_id": collection.id,
                            "owner": " ".join(owner),
                            "uuid": project["uuid"],
                        }
                else:
                    project_doc, owner = [], []
                    for main_cat in project["mainCategories"]:
                        for items in main_cat["inputElements"]:
                            if items["addressElements"]:
                                for addr_el in items["addressElements"]:
                                    for item in addr_el["items"]:
                                        if item["id"] == "project-address":
                                            address = item["value"]
                                        if item["id"] in PROJECT_DETAILS_MATCHING_KEYS:
                                            project_doc.append(item["value"])
                            elif items["items"]:
                                for item in items["items"]:
                                    if item["id"] in PROJECT_DETAILS_MATCHING_KEYS:
                                        project_doc.append(item["value"])
                                    if item["id"] == "client-first-name":
                                        owner.append(item["value"])
                                    if item["id"] == "client-last-name":
                                        owner.append(item["value"])
                                    if item["id"] == "project-name":
                                        project_name = item["value"]
                    docs[collection.id] = {
                        "doc": " ".join(project_doc),
                        "project_name": project_name,
                        "address": address,
                        "address_id": collection.id,
                        "owner": " ".join(owner),
                        "uuid": project["uuid"],
                    }
        db.close()
        return docs
    except Exception as e:
        firestore_io_logger.exception(
            f"An error occurred getting project {company_id}: {e}"
        )
    finally:
        db.close()
