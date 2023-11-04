from google.cloud.documentai_v1.types.document import Document
from google.cloud import storage

from utils.documents import documents_table, entity_table


async def create_document_object(
    document: Document, doc_id: str, blob: storage.blob.Blob | None = None
):
    """
    Parses a Document instance and a storage.blob.Blob instance to create a document object.

    Parameters
    ----------
    document : Document
        An instance of the Document class containing the data to be parsed.
    blob : storage.blob.Blob, optional
        An instance of the Blob class representing the binary data of an image file.
        Defaults to None.

    Returns
    -------
    Dict[str, Any]
        A dictionary containing the parsed data from the Document instance and
        the Blob instance.
    """
    if blob:
        filename = blob.name.split("/")[-1]
    doc_dict = documents_table.parse_documents_table_row(document, doc_id, blob)
    image_hex_list = []
    for page in doc_dict["pages"]:
        img_hex = page["image_content"]
        image_hex_list.append(img_hex)
        # TODO make sure to keep information on the page number
        del page["image_content"]

    entities = []
    for ents in document.entities:
        entities.append(
            entity_table.parse_raw_entity_table_row(
                ents,
                is_property=False,
            )
        )
        if "properties" in ents:
            # We don't need to find another page reference because the properties
            # are always subtypes of the major entity and therefore will be on the
            # same page.
            for prop in ents.properties:
                entities.append(
                    entity_table.parse_raw_entity_table_row(
                        prop,
                        is_property=True,
                    )
                )
    doc_dict["entities"] = entities

    line_items_list = []
    for ent in entities:
        if ent["entity_type_major"] is None:
            continue
        if "line_item" in ent["entity_type_major"]:
            line_items_list.append(ent)
            continue
        doc_dict.update({ent["entity_type_major"]: ent})
    doc_dict.update({"line_items": line_items_list})
    doc_dict.update(
        {
            "line_items_gpt": await documents_table.create_line_items_gpt(
                data_orig=line_items_list
            )
        }
    )

    return doc_dict, image_hex_list
