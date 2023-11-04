import asyncio
import itertools
import logging
import traceback

import gcsfs
from google.cloud import firestore, storage
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from starlette.websockets import WebSocketState

from utils.storage_utils import get_sub_dirs
from utils import auth
from global_vars.globals_io import (
    RAW_DOCS_UNPROCESSED_INVOICE_PATH,
    MESSAGE_STREAM_DELAY,
)
from config import PROJECT_NAME

logging.basicConfig(level=logging.INFO)

client = storage.Client(project="stak-app")
bucket = client.get_bucket("stak-customer-documents")

router = APIRouter()


fs = gcsfs.GCSFileSystem()


@router.websocket("/{company_id}/listen-invoice-updates")
async def listen_to_firestore_invoice_ws(
    websocket: WebSocket,
    company_id: str,
    token: str,
):
    # Authenticate the user
    #current_user = await auth.get_current_user(auth0=f"Bearer {token}")

    # Check the user data
    #auth.check_user_data(company_id=company_id, current_user=current_user)

    db = firestore.AsyncClient(project=PROJECT_NAME)
    fs = gcsfs.GCSFileSystem()

    try:
        await websocket.accept()

        collection_ref = (
            db.collection(company_id)
            .document("documents")
            .collection("processed_documents")
        )
        logging_ref = db.collection(company_id).document("logging")
        initial_docs = {doc.id: doc.to_dict() async for doc in collection_ref.stream()}

        while True:
            # check websocket connection
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json({"event": "heartbeat", "data": "ping"})
                response = await websocket.receive_json()
                if response["data"] != "pong":
                    print("Heartbeat failed.")
                    break
            else:
                print("Server thinks the WebSocket is not connected.")
                break

            logging_doc = await logging_ref.get()
            current_docs = {
                doc.id: doc.to_dict() async for doc in collection_ref.stream()
            }

            new_docs = {
                doc_id: doc_data
                for doc_id, doc_data in current_docs.items()
                if doc_id not in initial_docs
            }

            if logging_doc.to_dict()["is_scanning_docs"]:
                await websocket.send_json(
                    {"event": "scanning_docs", "data": "Scanning documents."}
                )

            new_updated_docs = {}
            if len(list(new_docs.keys())) > 0:
                for doc_id, doc_data in new_docs.items():
                    initial_docs[doc_id] = doc_data

                    del doc_data["full_document_text"]
                    del doc_data["entities"]
                    new_updated_docs[doc_id] = doc_data
                await websocket.send_json(
                    {"event": "new_document", "data": new_updated_docs}
                )

            try:
                invoice_sub_dirs = get_sub_dirs(
                    client, prefix=f"{company_id}/{RAW_DOCS_UNPROCESSED_INVOICE_PATH}"
                )
                numFilesLeft = len(
                    list(
                        itertools.chain.from_iterable(
                            [
                                fs.ls(
                                    f"stak-customer-documents/{company_id}/raw-documents/unprocessed/invoice/{sub_dir}"
                                )
                                for sub_dir in invoice_sub_dirs
                            ]
                        )
                    )
                )
            except FileNotFoundError:
                numFilesLeft = 0

            if numFilesLeft == 0:  # or not logging_doc.to_dict()["is_processing_docs"]:
                # Make sure all documents get sent to the front end on completion

                current_docs = {
                    doc.id: doc.to_dict() async for doc in collection_ref.stream()
                }

                new_docs = {
                    doc_id: doc_data
                    for doc_id, doc_data in current_docs.items()
                    if doc_id not in initial_docs
                }

                new_updated_docs = {}
                # make a final check to see if any files were left over and send them to the front end
                if len(list(new_docs.keys())) > 0:
                    for doc_id, doc_data in new_docs.items():
                        initial_docs[doc_id] = doc_data

                        del doc_data["full_document_text"]
                        del doc_data["entities"]
                        new_updated_docs[doc_id] = doc_data

                await websocket.send_json(
                    {"event": "done_processing", "data": new_updated_docs}
                )
                break  # this should send the last file or files and then stop the websocket
            await asyncio.sleep(MESSAGE_STREAM_DELAY)

    except WebSocketDisconnect:
        await websocket.close()
        print("WebSocket closed.")

    except Exception as e:
        print(f"WebSocket connection failed: {e}")
        traceback.print_exc()

    finally:
        db.close()
        if fs.session:
            await fs.session.close()
        await websocket.close()


@router.websocket("/{company_id}/listen-contract-updates")
async def listen_to_firestore_contract(
    websocket: WebSocket,
    company_id: str,
    token: str,
    PROJECT_NAME: str,
):
    # Authenticate the user
    #current_user = await auth.get_current_user(auth0=f"Bearer {token}")

    # Check the user data
    #auth.check_user_data(company_id=company_id, current_user=current_user)

    db = firestore.AsyncClient(project=PROJECT_NAME)
    fs = gcsfs.GCSFileSystem()

    try:
        await websocket.accept()

        document_ref = (
            db.collection(company_id)
            .document("projects")
            .collection(PROJECT_NAME)
            .document("contracts")
        )
        logging_ref = db.collection(company_id).document("logging")
        docs = await document_ref.get()
        try:
            initial_docs = {key: value for key, value in docs.to_dict().items()}
        except AttributeError:
            initial_docs = {}

        # Listen for new docs
        while True:
            # check websocket connection
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json({"event": "heartbeat", "data": "ping"})
                response = await websocket.receive_json()
                if response["data"] != "pong":
                    print("Heartbeat failed.")
                    break
            else:
                print("Server thinks the WebSocket is not connected.")
                break

            logging_doc = await logging_ref.get()
            try:
                docs = await document_ref.get()
                current_docs = {key: value for key, value in docs.to_dict().items()}

                new_docs = {
                    doc_id: doc_data
                    for doc_id, doc_data in current_docs.items()
                    if doc_id not in initial_docs
                }

            except AttributeError as e:
                current_docs = {}
                new_docs = {}

            if logging_doc.to_dict()["is_scanning_docs"]:
                await websocket.send_json(
                    {"event": "scanning_docs", "data": "Scanning documents."}
                )

            new_updated_docs = {}
            if len(list(new_docs.keys())) > 0:
                for doc_id, doc_data in new_docs.items():
                    initial_docs[doc_id] = doc_data
                    new_updated_docs[doc_id] = doc_data

                await websocket.send_json(
                    {"event": "new_document", "data": new_updated_docs}
                )

            try:
                contract_sub_dirs = get_sub_dirs(
                    client,
                    prefix=f"{company_id}/projects/{PROJECT_NAME}/contracts/{RAW_DOCS_UNPROCESSED_INVOICE_PATH}",
                )

                numFilesLeft = len(
                    list(
                        itertools.chain.from_iterable(
                            [
                                fs.ls(
                                    f"stak-customer-documents/{company_id}/projects/{PROJECT_NAME}/contracts/raw-documents/unprocessed/{sub_dir}"
                                )
                                for sub_dir in contract_sub_dirs
                            ]
                        )
                    )
                )
            except FileNotFoundError:
                numFilesLeft = 0
            if numFilesLeft == 0 and not logging_doc.to_dict()["is_processing_docs"]:
                # I haven't had the same issue with invoices, where they don't all show up
                # after getting processed with contracts, but will leave this here, in case that
                # issue comes up again

                # docs = await document_ref.get()
                # current_docs = {key: value for key, value in docs.to_dict().items()}

                # new_docs = {
                #     doc_id: doc_data
                #     for doc_id, doc_data in current_docs.items()
                #     if doc_id not in initial_docs
                # }
                await websocket.send_json(
                    {"event": "done_processing", "data": "End of stream"}
                )
                break
            await asyncio.sleep(MESSAGE_STREAM_DELAY)

    except WebSocketDisconnect:
        await websocket.close()
        print("WebSocket closed.")

    except Exception as e:
        print(f"WebSocket connection failed: {e}")
        traceback.print_exc()

    finally:
        db.close()
        if fs.session:
            await fs.session.close()
        await websocket.close()


@router.websocket("/{company_id}/listen-delete-invoices")
async def listen_to_firestore_invoices(
    websocket: WebSocket,
    company_id: str,
    token: str,
):
    # Authenticate the user
    #current_user = await auth.get_current_user(auth0=f"Bearer {token}")

    # Check the user data
    #auth.check_user_data(company_id=company_id, current_user=current_user)

    db = firestore.AsyncClient(project=PROJECT_NAME)

    try:
        await websocket.accept()
        logging_ref = db.collection(company_id).document("logging")

        # Listen on the firestore document logging for updates to the background process
        while True:
            # check websocket connection
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json({"event": "heartbeat", "data": "ping"})
                response = await websocket.receive_json()
                if response["data"] != "pong":
                    print("Heartbeat failed.")
                    break
            else:
                print("Server thinks the WebSocket is not connected.")
                break

            logging_doc = await logging_ref.get()

            if logging_doc.to_dict()["is_deleting_docs"]:
                await websocket.send_json(
                    {"event": "deleting_invoices", "data": "Deleting Invoices"}
                )
            else:
                await websocket.send_json(
                    {"event": "done_processing", "data": "End of stream"}
                )
                break

            await asyncio.sleep(MESSAGE_STREAM_DELAY)

    except WebSocketDisconnect:
        await websocket.close()
        print("WebSocket closed.")

    except Exception as e:
        print(f"WebSocket connection failed: {e}")
        traceback.print_exc()

    finally:
        db.close()
        await websocket.close()


@router.websocket("/{company_id}/listen-delete-client-bill")
async def listen_to_firestore_client_bill(
    websocket: WebSocket,
    company_id: str,
    token: str,
):
    # Authenticate the user
    #current_user = await auth.get_current_user(auth0=f"Bearer {token}")

    # Check the user data
    #auth.check_user_data(company_id=company_id, current_user=current_user)

    db = firestore.AsyncClient(project=PROJECT_NAME)

    try:
        await websocket.accept()

        logging_ref = db.collection(company_id).document("logging")

        # Listen on the firestore document logging for updates to the background process
        while True:
            # check websocket connection
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json({"event": "heartbeat", "data": "ping"})
                response = await websocket.receive_json()
                if response["data"] != "pong":
                    print("Heartbeat failed.")
                    break
            else:
                print("Server thinks the WebSocket is not connected.")
                break

            logging_doc = await logging_ref.get()

            if logging_doc.to_dict()["is_deleting_docs"]:
                await websocket.send_json(
                    {"event": "deleting_client_bill", "data": "Deleting Client Bills"}
                )
            else:
                await websocket.send_json(
                    {"event": "dont_processing", "data": "End of stream"}
                )
                break

            await asyncio.sleep(MESSAGE_STREAM_DELAY)

    except WebSocketDisconnect:
        await websocket.close()
        print("WebSocket closed.")

    except Exception as e:
        print(f"WebSocket connection failed: {e}")
        traceback.print_exc()

    finally:
        db.close()
        await websocket.close()


@router.websocket("/{company_id}/listen-delete-contract")
async def listen_to_firestore_client_bill(
    websocket: WebSocket,
    company_id: str,
    token: str,
):
    # Authenticate the user
    #current_user = await auth.get_current_user(auth0=f"Bearer {token}")

    # Check the user data
    #auth.check_user_data(company_id=company_id, current_user=current_user)

    db = firestore.AsyncClient(project=PROJECT_NAME)

    try:
        await websocket.accept()

        logging_ref = db.collection(company_id).document("logging")

        # Listen on the firestore document logging for updates to the background process
        while True:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.send_json({"event": "heartbeat", "data": "ping"})
                response = await websocket.receive_json()
                if response["data"] != "pong":
                    print("Heartbeat failed.")
                    break
            else:
                print("Server thinks the WebSocket is not connected.")
                break

            logging_doc = await logging_ref.get()

            if logging_doc.to_dict()["is_deleting_docs"]:
                await websocket.send_json(
                    {"event": "deleting_client_bill", "data": "Deleting Client Bills"}
                )
            else:
                await websocket.send_json(
                    {"event": "dont_processing", "data": "End of stream"}
                )
                break

            await asyncio.sleep(MESSAGE_STREAM_DELAY)

    except WebSocketDisconnect:
        await websocket.close()
        print("WebSocket closed.")

    except Exception as e:
        print(f"WebSocket connection failed: {e}")
        traceback.print_exc()

    finally:
        db.close()
        await websocket.close()
