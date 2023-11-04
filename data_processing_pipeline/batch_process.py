import asyncio
import traceback

from google.api_core.client_options import ClientOptions
from google.api_core.exceptions import InternalServerError, RetryError
from google.cloud import documentai_v1 as documentai


async def process_batch_process(
    project_id: str,
    location: str,
    processor_id: str,
    gcs_input_uri: str,
    gcs_output_bucket: str,
    gcs_output_uri_prefix: str,
    is_async: bool,
    timeout: int | None = 400,
):
    """
    Processes documents in a batch using the Document AI API.

    Parameters:
    - `project_id` (`str`): the Google Cloud project ID
    - `location` (`str`): the location of the processor, e.g. `us` or `eu`
    - `processor_id` (`str`): the processor ID
    - `gcs_input_uri` (`str`): the Google Cloud Storage URI of the input documents
    - `input_mime_type` (`str`): the MIME type of the input documents
    - `gcs_output_bucket` (`str`): the name of the Google Cloud Storage bucket to store the output documents
    - `gcs_output_uri_prefix` (`str`): the prefix for the Google Cloud Storage URI of the output documents

    Returns:
    - `metadata` (`BatchProcessMetadata`): metadata about the batch process operation
    """
    opts = ClientOptions(api_endpoint=f"{location}-documentai.googleapis.com")
    client = documentai.DocumentProcessorServiceClient(client_options=opts)

    gcs_prefix = documentai.GcsPrefix(gcs_uri_prefix=gcs_input_uri)
    input_config = documentai.BatchDocumentsInputConfig(gcs_prefix=gcs_prefix)

    # Cloud Storage URI for the Output Directory
    # This must end with a trailing forward slash `/`
    destination_uri = f"{gcs_output_bucket}/{gcs_output_uri_prefix}"

    gcs_output_config = documentai.DocumentOutputConfig.GcsOutputConfig(
        gcs_uri=destination_uri, field_mask=None
    )

    # Where to write results
    output_config = documentai.DocumentOutputConfig(gcs_output_config=gcs_output_config)

    # The full resource name of the processor, e.g.:
    # projects/project_id/locations/location/processor/processor_id
    name = client.processor_path(project_id, location, processor_id)

    request = documentai.BatchProcessRequest(
        name=name,
        input_documents=input_config,
        document_output_config=output_config,
    )

    if not is_async:
        # BatchProcess returns a Long Running Operation (LRO)
        operation = client.batch_process_documents(request)

        # sync
        try:
            operation.result(timeout=timeout)
        # Catch exception when operation doesn't finish before timeout
        except (RetryError, InternalServerError) as e:
            print(e.message)
    else:
        try:
            # BatchProcess returns a Long Running Operation (LRO)
            operation = client.batch_process_documents(request)

            # async
            def my_callback(future):
                result = future.result()

            operation.add_done_callback(my_callback)
        except Exception as e:
            print(traceback.format_exc())

        # Once the operation is complete,
        # get output document information from operation metadata
        while (
            operation.metadata.state != documentai.BatchProcessMetadata.State.SUCCEEDED
        ):
            await asyncio.sleep(1)

    metadata = documentai.BatchProcessMetadata(operation.metadata)
    if metadata.state != documentai.BatchProcessMetadata.State.SUCCEEDED:
        raise ValueError(f"Batch Process Failed: {metadata.state_message}")

    return metadata
