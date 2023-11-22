import logging
import sys
from typing import Any, Dict
import asyncio

from google.cloud import firestore
from tenacity import (
    retry_if_exception_type,
    wait_exponential_jitter,
    stop_after_attempt,
    AsyncRetrying,
    RetryError,
    before_sleep_log,
)

from utils.data_models.projects import AddClientBillData
from utils.data_models.budgets import UpdateCostCode
from utils.database import db_utils
from utils.database.firestore import stream_entire_collection
from utils.retry_utils import RETRYABLE_EXCEPTIONS
from global_vars.globals_invoice import PROJECT_DETAILS_MATCHING_KEYS
from global_vars.globals_io import RETRY_TIMES
from config import PROJECT_NAME

# Create a logger
logger_project_utils = logging.getLogger("error_logger")
logger_project_utils.setLevel(logging.DEBUG)

# Create a file handler
# handler = logging.FileHandler(
#     "/Users/mgrant/STAK/app/stak-backend/api/logs/add_client_bill.log"
# )
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)

# Create a logging format
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)

# Add the handlers to the logger
logger_project_utils.addHandler(handler)


async def get_all_projects_data(
    project_name: str,
    collection_name: str,
    document_name: str = "projects",
    sub_document_name: str = "project-details",
) -> dict:
    """
    Get the entire project details dictionary for each project.
    """
    db = firestore.AsyncClient(project=project_name)
    try:
        document_ref = db.collection(collection_name).document(document_name)
        docs = {}

        async for collection in document_ref:
            doc = await collection.document(sub_document_name).get()
            docs[collection.id] = doc.to_dict()
        return docs
    except Exception as e:
        logger_project_utils.exception(
            f"An error occured in `get_all_projects_data` function: {e}"
        )
    finally:
        db.close()


async def get_project_docs_from_firestore(
    company_id: str, document: str = "projects", project: str = PROJECT_NAME
) -> dict:
    """
    This was used to collect project information used to build the project
    matching algorithm.
    """
    docs = {}
    db = firestore.AsyncClient(project=project)
    try:
        collections = db.collection(company_id).document(document).collections()
        async for collection in collections:
            async for doc in collection.stream():
                project = doc.to_dict()
                project_doc = []
                if project["isActive"]:
                    owner = []
                    for main_cat in project["mainCategories"]:
                        for items in main_cat["inputElements"]:
                            for item in items["items"]:
                                if item["id"] in PROJECT_DETAILS_MATCHING_KEYS:
                                    project_doc.append(item["value"])
                                if item["id"] == "project-address":
                                    address = item["value"]
                                if item["id"] == "client's-last-name":
                                    owner.append(item["value"])
            docs[collection.id] = {
                "doc": " ".join(project_doc),
                "address": address,
                "address_id": collection.id,
                "owner": " ".join(owner),
                "uuid": project["uuid"],
            }

        return docs
    except Exception as e:
        logger_project_utils.exception(
            f"An error occured in `get_project_docs_from_firestore` function: {e}"
        )
    finally:
        db.close()


async def get_project_object(
    project_name: str, company_id: str, document_name: str, project_id: str
) -> Dict[str, Any]:
    """
    Given a project Id, retrieves the project object for that project.
    """
    db = firestore.AsyncClient(project=project_name)
    try:
        project_summary_ref = db.collection(company_id).document(document_name)
        doc = await project_summary_ref.get()
        doc = doc.to_dict()
        project = doc["allProjects"][project_id]
        project_obj = {
            "name": project["projectName"],
            "address": project["address"],
            "uuid": project["uuid"],
        }

        return project_obj
    except Exception as e:
        logger_project_utils.exception(
            f"An error occured in `get_project_object` function: {e}"
        )
    finally:
        db.close()


async def get_project_collection_name_by_id(
    project_name: str, company_id: str, project_id: str, document_name: str = "projects"
) -> str:
    db = firestore.AsyncClient(project=project_name)
    try:
        projects_ref = db.collection(company_id).document(document_name)

        async for coll in projects_ref.collections():
            if project_id in coll.id:
                return coll.id

    except Exception as e:
        logger_project_utils.exception(
            f"An error occured in `get_project_collection_by_id` function: {e}"
        )
    finally:
        db.close()


async def get_labor_row_ids_by_labor_id(
    project_name: str,
    company_id: str,
    project_key: str,
    labor_id: str,
    document_name: str,
    doc_collection_name: str,
) -> list:
    db = firestore.AsyncClient(project=project_name)
    try:
        project_collection_doc_ref = (
            db.collection(company_id)
            .document(document_name)
            .collection(project_key)
            .document(doc_collection_name)
        )

        doc = await project_collection_doc_ref.get()
        keys = []
        for key, value in doc.to_dict().items():
            if value["laborUUID"] == labor_id:
                keys.append(key)

        return keys
    except Exception as e:
        logger_project_utils.exception(
            f"An error occured in `get_labor_row_ids_by_labor_id` function: {e}"
        )
    finally:
        db.close()


def create_new_cost_code_budget_item(number: str, name: str) -> dict:
    try:
        return {
            "number": float(number),
            "value": "",
            "label": name,
            "isCurrency": True,
            "required": False,
            "type": "text",
            "id": format(float(number), ".4f"),
            "inputType": "toggleInput",
        }
    except ValueError as e:
        logger_project_utils.exception(
            f"An error occured in `create_new_cost_code_budget_item`: {e}; {number}"
        )


def create_new_subdivision_budget_item(number: str, name: str) -> dict:
    return {"number": float(number), "items": [], "name": name}


def create_new_division_budget_item(number: str, name: str) -> dict:
    return {"number": float(number), "subdivisions": [], "name": name}

def get_data_by_recursive_level(full_data, level):
    if len(level) == 0:
        return None
    level_data = full_data[level[0]]
    for i in range(1, len(level)):
        index = level[i]
        if not level_data.get('subItems') or len(level_data['subItems']) <= index:
            print('[getDataByRecursiveLevel]: No data')
            return None
        level_data = level_data['subItems'][index]
    return level_data


async def update_all_project_budgets(
    project_name: str, collection: str, document: str, data: list[UpdateCostCode]
) -> None:
    """
    Updates the budgets for all projects of a given company.

    This function performs several operations in a Firestore transaction.
    These operations include adding division items, subdivision items, and cost code items to the budgets.
    After each operation, the modified sections are sorted based on the 'number' field.

    Args:
        project_name (str): The GCP project name.
        collection (str): The ID of the company for which all project budgets are to be updated.
        document (str): Name of the projects document.
        data (dict): A dictionary containing the new budget items to be added.
            It should include the following keys: 'addDivisions', 'addSubDivisions', and 'addCostCodes'.
            The values associated with these keys are lists of dictionaries.
            Each dictionary represents a new budget item and should have 'number' and 'name' fields.

    Returns:
        None

    Note:
        This function uses Firestore transactions to ensure data consistency.
    """
    db = firestore.AsyncClient(project=project_name)
    try:
        transaction = db.transaction()
        projects_ref = db.collection(collection).document(document)

        @firestore.async_transactional
        async def update_budget(transaction, project_budget_ref):
            budget_snapshot = await project_budget_ref.get(transaction=transaction)
            budget = budget_snapshot.to_dict()

            if budget is None:
                return
            
            for action in data:
                try:
                    if action.type == "Create":
                        if len(action.recursiveLevel) == 0 :
                            new_division_item = {
                                "name": action.name,
                                "number": float(action.number),
                                "subItems": []
                            }
                            budget["divisions"].append(new_division_item)
                            sorted_divisions = sorted(
                                budget["divisions"], key=lambda x: x["number"]
                            )
                            budget["divisions"] = sorted_divisions
                        else :
                            parent_item = get_data_by_recursive_level(budget["divisions"], action.recursiveLevel)
                            new_cost_code = {
                                "number": float(action.number),
                                "name": action.name,
                                "value": "0.00",
                                "id": str(action.number),
                                "required": False,
                                "isCurrency": True,
                                "inputType": "toggleInput",
                                "subItems": []
                            }
                            if not parent_item.get("subItems") or len(parent_item["subItems"]) == 0:
                                if parent_item.get("isCurrency"):
                                    parent_item["isCurrency"] = False
                                    parent_item["value"] = "0.00"
                                parent_item["subItems"] = []
                            parent_item["subItems"].append(new_cost_code)
                            sorted_item = sorted(
                                parent_item["subItems"], key=lambda x: x["number"]
                            )
                            parent_item["subItems"] = sorted_item
                    elif action.type == "Delete" :
                        if len(action.recursiveLevel) == 0:
                            print("Invalid action type")
                            break
                        if len(action.recursiveLevel) == 1:
                            budget["division"].pop(action.recursiveLevel[0])
                        else:
                            parent_level = action.recursiveLevel[:-1]
                            parent_item = get_data_by_recursive_level(budget["divisions"], parent_level)
                            if parent_item.get("subItems"):
                                parent_item["subItems"].pop(action.recursiveLevel[-1])
                            if len(parent_level) != 1 and not parent_item.get("subItems"):
                                parent_item["isCurrency"] = True
                                parent_item["value"] = "0.00"
                    elif action.type == "Update":
                        if len(action.recursiveLevel) == 0:
                            print("Invalid action type")
                            break
                        item = get_data_by_recursive_level(budget["divisions"], action.recursiveLevel)
                        item["name"] = action.name
                        item["number"] = float(action.number)
                except IndexError as error:
                    logger_project_utils.error(
                        f"An indexerror occured when trying to update all project budgets: {error}; The action is: {action}"
                    )
            # Update the budget in the transaction
            transaction.update(project_budget_ref, budget)

        async for coll in projects_ref.collections():
            coll.id
            project_budget_ref = projects_ref.collection(coll.id).document("budget")

            # Execute the transaction function
            await update_budget(transaction, project_budget_ref)
    except Exception as e:
        logger_project_utils.exception(
            f"An error occurred while `update_all_project_budgets`: {e}"
        )
    finally:
        db.close()


async def add_new_client_bill(
    project_name: str,
    collection: str,
    project_id: str,
    client_bill_id: str,
    data: AddClientBillData,
):
    """
    Asynchronously add a new client bill to the Firestore database.

    This function fetches invoices and labor documents by their ids from the Firestore and copies them to the client bill collection. It also creates or updates the bill summary document in the client bill collection.

    Args:
        project_name (str): The name of the Firestore project.
        collection (str): The name of the Firestore collection where the client bill is stored.
        project_id (str): The ID of the project where the bill is associated.
        client_bill_id (str): The ID of the new client bill.
        data (dict): A dictionary containing the following keys:
            - 'invoiceIds': A list of ids of the invoices to be included in the client bill.
            - 'laborIds': A list of ids of the labor documents to be included in the client bill.
            - 'billSummary': A dictionary containing the summary of the client bill.

    Returns:
        None

    Raises:
        RetryError: If an error occurs while copying the invoices or labor documents to the client bill collection and the number of retry attempts exceeds the limit set by AsyncRetrying.
    """
    db = firestore.AsyncClient(project=project_name)
    tasks = []
    try:
        invoice_ids = data.invoiceIds
        labor_ids = data.laborIds
        bill_summary = data.clientBillSummary
        bill_work_description = data.clientBillObj

        # source refs
        invoice_source_ref = (
            db.collection(collection)
            .document("documents")
            .collection("processed_documents")
        )
        project_ref = (
            db.collection(collection).document("projects").collection(project_id)
        )
        # destination ref
        client_bill_ref = (
            db.collection(collection)
            .document("projects")
            .collection(project_id)
            .document("client-bills")
            .collection(client_bill_id)
        )

        client_bill_summary_ref = (
            db.collection(collection)
            .document("projects")
            .collection(project_id)
            .document("client-bills-summary")
        )
        # move all invoices
        if len(invoice_ids) > 0:
            async for doc in invoice_source_ref.where(
                "__name__", "in", invoice_ids
            ).stream():
                invoice_doc = await client_bill_ref.document("invoices").get()
                await copy_doc_to_db(
                    destination_snapshot=invoice_doc,
                    destination_ref=client_bill_ref,
                    source_ref=invoice_source_ref,
                    destination_document="invoices",
                    doc_id=doc.id,
                    doc=doc.to_dict(),
                )
                # tasks.append(asyncio.create_task(coroutine_inv))

        async for doc in project_ref.where(
            "__name__", "in", ["labor", "labor-summary"]
        ).stream():
            for labor_id, labor_doc in doc.to_dict().items():
                if labor_id in labor_ids:
                    if doc.id == "labor":
                        await copy_doc_to_db(
                            destination_snapshot=await client_bill_ref.document(
                                "labor"
                            ).get(),
                            destination_ref=client_bill_ref,
                            source_ref=project_ref.document("labor"),
                            destination_document="labor",
                            doc_id=labor_id,
                            doc=labor_doc,
                        )
                        # tasks.append(asyncio.create_task(coroutine_labor))
                    else:
                        await copy_doc_to_db(
                            destination_snapshot=await client_bill_ref.document(
                                "labor-summary"
                            ).get(),
                            destination_ref=client_bill_ref,
                            source_ref=project_ref.document("labor-summary"),
                            destination_document="labor-summary",
                            doc_id=labor_id,
                            doc=labor_doc,
                        )
                        # tasks.append(asyncio.create_task(coroutine_labor_summary))
        coroutine_bill_summary = copy_doc_to_db(
            destination_snapshot=await client_bill_summary_ref.get(),
            destination_ref=client_bill_summary_ref,
            source_ref=None,
            destination_document=None,
            doc_id=client_bill_id,
            doc=bill_summary.dict(),
        )
        tasks.append(asyncio.create_task(coroutine_bill_summary))

        coroutine_bill_work_description = copy_doc_to_db(
            destination_snapshot=await client_bill_ref.document(
                "bill-work-description"
            ).get(),
            destination_ref=client_bill_ref,
            source_ref=None,
            destination_document="bill-work-description",
            doc_id=None,
            doc=bill_work_description.dict(),
        )
        tasks.append(asyncio.create_task(coroutine_bill_work_description))

        await asyncio.gather(*tasks)
    except Exception as e:
        logger_project_utils.exception(f"Error adding new client bill: {e}")
        return {"message": "Error adding new client bill."}
    finally:
        db.close()


async def add_client_bill_actuals(
    project_name: str, collection: str, project_id: str, client_bill_id: str, data: dict
):
    db = firestore.AsyncClient(project=project_name)
    try:
        client_bill_ref = (
            db.collection(collection)
            .document("projects")
            .collection(project_id)
            .document("client-bills")
            .collection(client_bill_id)
        )
        # There should only be one current actuals for each bill so we can just
        # always set() it.
        await client_bill_ref.document("current-actuals").set(data.dict())

    except Exception as e:
        logger_project_utils.exception(f"Error adding new client bill: {e}")
        return {"message": "Error adding new client bill."}
    finally:
        db.close()

async def update_client_bill_details(
    project_name: str, collection: str, project_id: str, client_bill_id: str, data: dict
):
    db = firestore.AsyncClient(project=project_name)

    invoices = data.invoices
    labor = data.labor
    laborSummary = data.laborSummary
    bill_summary = data.clientBillSummary
    bill_work_description = data.clientBillObj
    try: 
        client_bill_ref = (
            db.collection(collection)
            .document("projects")
            .collection(project_id)
            .document("client-bills")
            .collection(client_bill_id)
        )

        if invoices is not None:
            invoices_dict = invoices.dict()
            await client_bill_ref.document("invoices").set(invoices_dict["__root__"])
        if labor is not None:
            labor_dict = labor.dict()
            await client_bill_ref.document("labor").set(labor_dict["__root__"])
        if laborSummary is not None:
            laborSummary_dict = {f"{item.uuid}": item.dict() for index, item in enumerate(laborSummary)}
            await client_bill_ref.document("labor-summary").set(laborSummary_dict)
        if bill_work_description is not None:
            await client_bill_ref.document("bill-work-description").set(bill_work_description.dict())

        client_bill_summary_ref = (
            db.collection(collection)
            .document("projects")
            .collection(project_id)
            .document("client-bills-summary")
        )
        doc = await client_bill_summary_ref.get()
        client_bill_summary_data = doc.to_dict()

        client_bill_summary_data[client_bill_id] = bill_summary.dict()

        await client_bill_summary_ref.set(client_bill_summary_data)
        return {"status" : "success"}
        
    except Exception as e:
        logger_project_utils.exception(f"Error updating client bill: {e}")
        return {"message": "Error updating client bill."}
    finally:   
        db.close()

async def copy_doc_to_db(
    destination_snapshot: firestore.DocumentSnapshot | None,
    destination_ref: firestore.AsyncCollectionReference,
    source_ref: firestore.AsyncDocumentReference | None,
    destination_document: str,
    doc_id: str | None,
    doc: dict,
):
    """
    Copy a document to a destination in a Firestore database.

    This function tries to copy a document to a specified location in the Firestore database.
    If the destination document already exists, it updates the document; otherwise, it sets a new document.
    It uses AsyncRetrying to retry the operation in case of ValueError or RuntimeError,
    stopping after 2 attempts and applying an exponential jitter wait between retries.

    Args:
        destination_snapshot (firestore.DocumentSnapshot | None): A Firestore DocumentSnapshot instance
            representing the current state of the destination document.
        destination_ref (firestore.AsyncDocumentReference): A Firestore AsyncDocumentReference to the destination collection.
        source_ref (firestore.AsyncDocumentReference): A Firestore AsyncDocumentReference to the source collection.
        destination_document (str): The name of the document in the destination collection.
        doc_id (str): The ID of the document to be copied.
        doc (dict): A dictionary representing the document to be copied.
        retry_times = 5 (int): number of times to retry the operation, default set to 5

    Raises:
        RetryError: If both attempts fail with either a ValueError or RuntimeError.

    Note:
        Exceptions are logged but not propagated. Implement appropriate logging in the RetryError exception handler.
    """
    try:
        if doc_id:
            copy_doc = {doc_id: doc}
        else:
            copy_doc = doc
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(logger_project_utils, logging.DEBUG),
        ):
            with attempt:
                if destination_snapshot and destination_snapshot.exists:
                    if destination_document:
                        await destination_ref.document(destination_document).update(
                            copy_doc
                        )
                    else:
                        await destination_ref.update(copy_doc)
                else:
                    if destination_document:
                        await destination_ref.document(destination_document).set(
                            copy_doc
                        )
                    else:
                        await destination_ref.set(copy_doc)
                # Check if copy was successfull
                if destination_document:
                    copied_doc = await destination_ref.document(
                        destination_document
                    ).get()
                else:
                    copied_doc = await destination_ref.get()
                if doc_id:
                    if copied_doc.to_dict()[doc_id] != copy_doc[doc_id]:
                        logger_project_utils.error(
                            f"Data inconsistency detected for document {destination_document} after copy."
                        )
                        raise ValueError(
                            "Copied document data does not match source data."
                        )
                else:
                    if copied_doc.to_dict() != copy_doc:
                        logger_project_utils.error(
                            f"Data inconsistency detected for document {destination_document} after copy."
                        )
                        raise ValueError(
                            "Copied document data does not match source data."
                        )
        if source_ref and doc_id:
            await delete_doc_from_db(source_ref=source_ref, doc_id=doc_id)

    except RetryError as e:
        logger_project_utils.error(
            f"Max retry attempts reached while copying document to DB: {e}"
        )
        raise
    except Exception as e:
        logger_project_utils.exception(
            f"Unexpected error occurred while copying document to DB: {e}"
        )
        raise


async def delete_doc_from_db(
    source_ref: firestore.AsyncCollectionReference,
    doc_id: str,
) -> None:
    """
    Delete a document from a Firestore database.

    This function tries to delete a document from a specified location in the Firestore database.
    It uses AsyncRetrying to retry the operation in case of ValueError, RuntimeError or a Firestore error,
    stopping after 2 attempts and applying an exponential jitter wait between retries.

    Args:
        source_snapshot (firestore.DocumentSnapshot | None): A Firestore DocumentSnapshot instance
            representing the current state of the source document.
        source_ref (firestore.AsyncDocumentReference): A Firestore AsyncDocumentReference to the source collection.
        source_document (str): The name of the document in the source collection.
        doc_id (str or None): The ID of the document to be deleted.
        retry_times = 5 (int): Number of times to retry on failure.

    Raises:
        RetryError: If both attempts fail with either a ValueError, RuntimeError or a Firestore error.
    """
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(logger_project_utils, logging.DEBUG),
        ):
            with attempt:
                try:
                    source_doc = source_ref.document(doc_id)
                    if (await source_doc.get()).exists:
                        await source_doc.delete()
                    else:
                        logger_project_utils.info(
                            f"Document {doc_id} not found in source, skipping delete operation."
                        )
                except AttributeError as e:
                    await source_ref.update({doc_id: firestore.DELETE_FIELD})
    except RetryError as e:
        logger_project_utils.error(
            f"{e} occured while trying to delete document from DB"
        )
        raise
    except Exception as e:
        logger_project_utils.exception(
            f"Unexpected error occurred while copying document to DB: {e}"
        )
        raise


async def get_client_bill_current_actuals_from_firestore(
    project_name: str,
    collection: str,
    project_id: str,
    client_bill_id: str,
) -> dict | None:
    db = firestore.AsyncClient(project=project_name)
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(logger_project_utils, logging.DEBUG),
        ):
            with attempt:
                client_bill_actuals_ref = (
                    db.collection(collection)
                    .document("projects")
                    .collection(project_id)
                    .document("client-bills")
                    .collection(client_bill_id)
                    .document("current-actuals")
                )
                current_actuals = await client_bill_actuals_ref.get()
                return current_actuals.to_dict()

    except RetryError as e:
        logger_project_utils.error(
            f"{e} occured while trying to GET client bill. Client bill ({client_bill_id})"
        )
        raise
    except Exception as e:
        logger_project_utils.exception(
            f"Unexpected error occurred while trying to GET client bill ({client_bill_id}): {e}"
        )
        raise
    finally:
        db.close()


async def get_client_bill_from_firestore(
    project_name: str,
    collection: str,
    project_id: str,
    client_bill_id: str,
) -> dict | None:
    try:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(RETRY_TIMES),
            wait=wait_exponential_jitter(),
            retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
            reraise=True,
            before_sleep=before_sleep_log(logger_project_utils, logging.DEBUG),
        ):
            with attempt:
                client_bill_data = await stream_entire_collection(
                    project_name,
                    collection_name=collection,
                    document_name="projects",
                    doc_collection_name=project_id,
                    sub_collection_document="client-bills",
                    sub_collection=client_bill_id,
                )

        return {client_bill_id: client_bill_data}

    except RetryError as e:
        logger_project_utils.error(
            f"{e} occured while trying to GET client bill. Client bill ({client_bill_id})"
        )
        raise
    except Exception as e:
        logger_project_utils.exception(
            f"Unexpected error occurred while trying to GET client bill ({client_bill_id}): {e}"
        )
        raise
