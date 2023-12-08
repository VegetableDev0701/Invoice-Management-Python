import os
import json
import traceback

os.environ["TOKENIZERS_PARALLELISM"] = "false"

import asyncio
import re
import tempfile

import gcsfs
from google.cloud import documentai_v1 as documentai
from google.cloud import storage

from data_processing_pipeline.batch_process import (
    process_batch_process,
)
from config import Config, ProjectPredConfig
from data_processing_pipeline.matching_algorithm_utils import (
    get_data_for_predictions,
    make_project_prediction,
    get_vendor_name,
    match_predicted_vendor,
)
from utils import io_utils, contract_helpers, model_utils
from utils.documents.create_documents import create_document_object
from utils.storage_utils import (
    get_sub_dirs,
    move_blob_fs,
    save_cv2_image,
    save_doc_dict,
)
from utils.database.firestore import push_to_firestore, push_update_to_firestore
from utils.database.projects.utils import get_project_object
from config import PROJECT_NAME
from global_vars import globals_io
from global_vars.prompts import Prompts

storage_client = storage.Client()


# TODO implement logging in this function
async def batch_process_invoices(
    doc_type: str,
    gcp_project_id: str,
    project_docs: str,
    location: str,
    processor_id: str,
    gcs_output_bucket: str,
    gcs_output_uri_prefix: str,
    company_id: str,
    bucket_name: str,
    project_id: str | None = None,
    is_async: bool = True,
):
    storage_client = storage.Client()
    sub_dirs = get_sub_dirs(
        storage_client,
        prefix=f"{company_id}/{globals_io.RAW_DOCS_UNPROCESSED_INVOICE_PATH}",
    )
    fs = gcsfs.GCSFileSystem()
    gcs_input_prefix = f"gs://stak-customer-documents/{company_id}/raw-documents/unprocessed/{doc_type}"

    (
        address_choices,
        owner_choices,
        model,
        doc_emb,
    ) = get_data_for_predictions(project_docs)

    pred_config = ProjectPredConfig(address_choices, owner_choices, model, doc_emb)

    async def process_async(metadata):
        tasks = []
        for process in metadata.individual_process_statuses:
            task = asyncio.ensure_future(
                process_and_move_invoices(
                    process,
                    project_docs=project_docs,
                    pred_config=pred_config,
                    bucket=bucket_name,
                    fs=fs,
                    project_id=project_id,
                    company_id=company_id,
                    is_testing=False,
                )
            )
            tasks.append(task)

        await asyncio.gather(*tasks)

    for i in sub_dirs:
        metadata = None
        await push_update_to_firestore(
            project_name=PROJECT_NAME,
            collection=company_id,
            data={"is_scanning_docs": True},
            document="logging",
        )
        gcs_input_uri = f"{gcs_input_prefix}/{i}/"
        metadata = await process_batch_process(
            gcp_project_id,
            location,
            processor_id,
            gcs_input_uri,
            gcs_output_bucket,
            gcs_output_uri_prefix,
            is_async=is_async,
        )
        if metadata:
            await push_update_to_firestore(
                project_name=PROJECT_NAME,
                collection=company_id,
                data={"is_scanning_docs": False},
                document="logging",
            )
        await process_async(metadata)


async def batch_process_contracts(
    gcp_project_id: str,
    location: str,
    processor_id: str,
    gcs_output_bucket: str,
    gcs_output_uri_prefix: str,
    company_id: str,
    project_id: str,
    bucket_name: str,
    is_async: bool = True,
):
    storage_client = storage.Client()
    sub_dirs = get_sub_dirs(
        storage_client,
        prefix=f"{company_id}/projects/{project_id}/contracts/raw-documents/unprocessed",
    )
    fs = gcsfs.GCSFileSystem()

    gcs_input_prefix = f"gs://stak-customer-documents/{company_id}/projects/{project_id}/contracts/raw-documents/unprocessed"

    async def process_async(metadata):
        tasks = []
        for process in metadata.individual_process_statuses:
            task = asyncio.ensure_future(
                process_and_move_contracts(
                    process,
                    bucket=bucket_name,
                    fs=fs,
                    company_id=company_id,
                    project_id=project_id,
                )
            )
            tasks.append(task)

        await asyncio.gather(*tasks)

    # start = time.time()
    for i in sub_dirs:
        metadata = None
        await push_update_to_firestore(
            project_name=PROJECT_NAME,
            collection=company_id,
            data={"is_scanning_docs": True},
            document="logging",
        )
        gcs_input_uri = f"{gcs_input_prefix}/{i}/"
        metadata = await process_batch_process(
            gcp_project_id,
            location,
            processor_id,
            gcs_input_uri,
            gcs_output_bucket,
            gcs_output_uri_prefix,
            is_async=is_async,
        )
        if metadata:
            await push_update_to_firestore(
                project_name=PROJECT_NAME,
                collection=company_id,
                data={"is_scanning_docs": False},
                document="logging",
            )

        await process_async(metadata)


async def process_and_move_invoices(
    process,
    project_docs: dict,
    pred_config: ProjectPredConfig,
    bucket: str,
    fs: gcsfs.GCSFileSystem,
    company_id: str,
    project_id: str | None = None,
    project_id_for_testing: str | None = None,
    is_testing: bool | None = None,
):
    matches = re.match(r"gs://(.*?)/(.*)", process.output_gcs_destination)
    if not matches:
        print(
            "Could not parse output GCS destination:",
            process.output_gcs_destination,
        )
        return

    _, output_prefix = matches.groups()

    output_prefix = output_prefix + "/"
    filename = process.input_gcs_source.split("/")[-1]
    filename_prefix = filename.split(".pdf")[0]
    doc_dict_filename = "DOC_DICT_" + filename_prefix + ".json"
    img_filename = filename_prefix + ".jpg"
    pdf_prefix = process.input_gcs_source.split(f"{bucket}/")[-1]
    uuid = io_utils.get_uuid_from_filename(filename)
    output_blobs = fs.ls(f"{bucket}/{output_prefix}")

    for blob in output_blobs:
        # Document AI should only output JSON files to GCS
        if ".json" not in blob:
            print(f"Skipping non-supported file: {blob}")
            continue

        with fs.open(blob, "rb") as f:
            document = documentai.Document.from_json((f.read()))

        doc_dict, img_hex_list = await create_document_object(document, doc_id=uuid)

        # Check if there are any projects at all, if not `project_docs = {}`
        if project_docs:
            project_prediction_results = await make_project_prediction(
                doc_dict,
                project_docs,
                match_customer_patterns_list=Config.MATCH_CUSTOMER_REGEX,
                address_choices=pred_config.address_choices,
                owner_choices=pred_config.owner_choices,
                model=pred_config.model,
                doc_emb=pred_config.doc_emb,
            )
        else:
            project_prediction_results = {
                "name": None,
                "value": None,
                "score": None,
                "top_scores": None,
                "uuid": None,
            }

        # Having project_id included was a legacy idea where the user could choose which project
        # the invoice was being uploaded for. This was deprecated and the user cannot choose which project
        # an invoice is being uploaded for. This became too complicated, so the else clause will actually
        # never get hit...but still too afraid to delete this code :)
        if not project_id:
            doc_dict["predicted_project"] = project_prediction_results
            doc_dict["project"] = {
                "name": None,
                "address": None,
                "uuid": None,
            }
        else:
            doc_dict["predicted_project"] = {
                "name": None,
                "value": None,
                "score": None,
                "top_scores": None,
                "uuid": None,
            }
            doc_dict["project"] = await get_project_object(
                project_name=PROJECT_NAME,
                company_id=company_id,
                document_name="project-summary",
                project_id=project_id,
            )

        if is_testing and project_id_for_testing:
            destination_prefix = (
                f"{company_id}/processed-documents/test/{project_id_for_testing}/{uuid}"
            )
            # destination_prefix = f"{company_id}/processed-documents/{uuid}"
        else:
            # destination_prefix = f"{company_id}/processed-documents/{project_prediction_results['address_id']}/current/{uuid}"
            destination_prefix = f"{company_id}/processed-documents/{uuid}"

        doc_dict["gcs_uri"] = f"{destination_prefix}/{filename}"

        # This gets updated if this invoice becomes part of a change order and when it gets attached to client bill
        doc_dict["client_bill_id"] = None
        doc_dict["is_attached_to_bill"] = False

        doc_img_path_list, tasks = [], []
        for i, img_hex in enumerate(img_hex_list):
            doc_img_path_list.append(f"DOC_IMG_PAGE_{i+1}_{img_filename}")
            with tempfile.NamedTemporaryFile(suffix=".jpg") as temp_file:
                coroutine = save_cv2_image(
                    img_hex,
                    temp_file.name,
                    destination_prefix,
                    f"DOC_IMG_PAGE_{i+1}_{img_filename}",
                )
                tasks.append(asyncio.create_task(coroutine))
        await asyncio.gather(*tasks)
        doc_dict["gcs_img_uri"] = doc_img_path_list

        full_text = doc_dict["full_document_text"].replace("\n", " ").strip()
        pred_vendor_name_dict = await get_vendor_name(doc_dict, full_text)
        try:
            matched_vendor_name = await match_predicted_vendor(
                company_id=company_id, pred_vendor_name_dict=pred_vendor_name_dict
            )
        except Exception as e:
            print(traceback.print_exc())

        doc_dict["predicted_supplier_name"] = matched_vendor_name

        task1 = save_doc_dict(
            doc_dict, destination=f"{destination_prefix}/{doc_dict_filename}"
        )

        task2 = push_to_firestore(
            project_name=PROJECT_NAME,
            collection=company_id,
            data=doc_dict,
            document="documents",
            doc_collection="processed_documents",
            doc_collection_document=doc_dict["doc_id"],
        )
        await asyncio.gather(task1, task2)

        if is_testing:
            source_name1 = (blob,)
            destination_name1 = (
                f"{bucket}/{destination_prefix}/FULL_DOCAI_OUTPUT_{blob.split('/')[-1]}"
            )
            source_name2 = f"{bucket}/{pdf_prefix}"
            destination_name2 = f"{bucket}/{destination_prefix}/{filename}"

            files_to_move_or_copy = [
                (
                    source_name1,
                    destination_name1,
                    False,
                ),
                (source_name2, destination_name2, False),
            ]
        else:
            source_name1 = (blob,)
            destination_name1 = (
                f"{bucket}/{destination_prefix}/FULL_DOCAI_OUTPUT_{blob.split('/')[-1]}"
            )
            source_name2 = f"{bucket}/{pdf_prefix}"
            destination_name2 = f"{bucket}/{destination_prefix}/{filename}"

            files_to_move_or_copy = [
                # (source_name1, destination_name1, True),
                (
                    source_name1,
                    destination_name1,
                    False,
                ),
                (source_name2, destination_name2, False),
            ]
        tasks = []
        for source_name, destination_name, isCopy in files_to_move_or_copy:
            coroutine = move_blob_fs(
                fs,
                source_name=source_name,
                destination_name=destination_name,
                isCopy=isCopy,
            )
            tasks.append(asyncio.create_task(coroutine))
        await asyncio.gather(*tasks)
    await push_update_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data={"is_processing_docs": False},
        document="logging",
    )


async def process_and_move_contracts(
    process,
    bucket: str,
    fs: gcsfs.GCSFileSystem,
    company_id: str,
    project_id: str,
):
    matches = re.match(r"gs://(.*?)/(.*)", process.output_gcs_destination)
    if not matches:
        print(
            "Could not parse output GCS destination:",
            process.output_gcs_destination,
        )
        return
    _, output_prefix = matches.groups()

    output_prefix = output_prefix + "/"
    filename = process.input_gcs_source.split("/")[-1]
    filename_prefix = filename.split(".pdf")[0]
    doc_dict_filename = "DOC_DICT_" + filename_prefix + ".json"
    img_filename = filename_prefix + ".jpg"
    pdf_prefix = process.input_gcs_source.split(f"{bucket}/")[-1]
    uuid = io_utils.get_uuid_from_filename(filename)
    output_blobs = fs.ls(f"stak-customer-documents/{output_prefix}")
    destination_prefix = (
        f"{company_id}/projects/{project_id}/contracts/processed-documents/{uuid}"
    )

    doc_dict = {}

    for blob in output_blobs:
        with fs.open(blob, "rb") as json_file:
            response = json.load(json_file)
        full_text = response["text"]
        doc_dict["gcs_uri"] = f"{destination_prefix}/{filename}"
        images = []
        for i, page in enumerate(response["pages"]):
            images.append(page["image"]["content"])
        #             del page["image"]["content"]

        doc_img_path_list, tasks = [], []
        for i, image_str in enumerate(images):
            doc_img_path_list.append(f"DOC_IMG_PAGE_{i+1}_{img_filename}")
            with tempfile.NamedTemporaryFile(suffix=".jpg") as temp_file:
                coroutine = contract_helpers.save_contract_img(
                    image_str,
                    temp_file.name,
                    destination_prefix,
                    f"DOC_IMG_PAGE_{i+1}_{img_filename}",
                )
                tasks.append(asyncio.create_task(coroutine))
        await asyncio.gather(*tasks)
        doc_dict["gcs_img_uri"] = doc_img_path_list
        doc_dict["uuid"] = uuid

        # Process the text
        end_index = int(
            response["pages"][0]["paragraphs"][-1]["layout"]["textAnchor"][
                "textSegments"
            ][0]["endIndex"]
        )
        text = full_text[:end_index]
        prompt = Prompts(text)

        gpt_response = await model_utils.get_completion_gpt35(
            prompt.contract_prompt, max_tokens=250, job_type="parsing_contract"
        )

        summary_data: dict = json.loads(gpt_response)

        task1 = match_predicted_vendor(
            company_id=company_id, pred_vendor_name_dict=summary_data
        )
        task2 = get_project_object(
            PROJECT_NAME, company_id, "project-summary", project_id
        )
        summary_data, project_obj = await asyncio.gather(task1, task2)

        summary_data["projectName"] = project_obj["name"]

        doc_dict["summaryData"] = summary_data

        # push to db
        task1 = save_doc_dict(
            doc_dict, destination=f"{destination_prefix}/{doc_dict_filename}"
        )

        task2 = push_update_to_firestore(
            project_name=PROJECT_NAME,
            collection=company_id,
            data={uuid: doc_dict},
            document="projects",
            doc_collection=project_id,
            doc_collection_document="contracts",
        )

        task3 = push_update_to_firestore(
            project_name=PROJECT_NAME,
            collection=company_id,
            data={uuid: summary_data},
            document="projects",
            doc_collection=project_id,
            doc_collection_document="contracts-summary",
        )

        await asyncio.gather(task1, task2, task3)

        # move files
        source_name1 = (blob,)
        destination_name1 = (
            f"{bucket}/{destination_prefix}/FULL_DOCAI_OUTPUT_{blob.split('/')[-1]}"
        )
        source_name2 = f"{bucket}/{pdf_prefix}"
        destination_name2 = f"{bucket}/{destination_prefix}/{filename}"

        files_to_move_or_copy = [
            (
                source_name1,
                destination_name1,
                False,
            ),
            (source_name2, destination_name2, False),
        ]
        tasks = []
        for source_name, destination_name, isCopy in files_to_move_or_copy:
            coroutine = move_blob_fs(
                fs,
                source_name=source_name,
                destination_name=destination_name,
                isCopy=isCopy,
            )
            tasks.append(asyncio.create_task(coroutine))
        await asyncio.gather(*tasks)
    await push_update_to_firestore(
        project_name=PROJECT_NAME,
        collection=company_id,
        data={"is_processing_docs": False},
        document="logging",
    )
