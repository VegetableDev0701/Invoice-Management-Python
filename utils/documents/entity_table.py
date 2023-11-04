from datetime import datetime
from typing import Any, Dict, List

# from google.cloud.storage.blob import Blob
from google.cloud.documentai_v1.types.document import Document

from utils.database import db_utils
from global_vars import globals_db as gv_db

# TODO the user will manually add invoices to the system so should
# grab the file the document was downloaded to the system
# and add this as date received


def parse_raw_entity_table_row(
    entity: Document,
    is_property: bool,
) -> Dict[str, Any]:
    """
    Parse a single row for the entities_table.

    Parameters
    ----------
    entity: protobuf object
        A an entity from `result.document.entities` protobuf object.
    is_property: bool
        True if the element is a sub-level property entity.
    blob: gcs Blob
        The GCS Blob object
    doc_id: str
        The document UUID

    Returns
    -------
    Dictionary type for a single row of the table.
    """

    # Set the base schema so if any entities are missing the one of these
    # values the row will be preserved with a None
    tmp_row_dict = gv_db.RAW_ENTITY_TABLE_DICT.copy()

    # hit a strange case where the protobuf returned an entity that didn't
    # exist on the page. catch this by checking if the list that holds the
    # bounding box is empty, since there will always be a bounding box
    # associated with a real entity.
    if not entity.page_anchor.page_refs:
        return {"entity_type_major": None}

    tmp_row_dict.update(
        {
            "entity_type_major": entity.type_.split("/")[0],
            "entity_value_raw": entity.mention_text,
            "entity_value_norm": (
                db_utils.parse_norm_value(entity.normalized_value, unit=False)
                if db_utils.parse_norm_value(entity.normalized_value, unit=False)
                else None
            ),
            "unit": (
                db_utils.parse_norm_value(entity.normalized_value, unit=True)
                if db_utils.parse_norm_value(entity.normalized_value, unit=True)
                else None
            ),
            "bounding_box": (
                create_bounding_box(
                    entity.page_anchor.page_refs[0].bounding_poly.normalized_vertices
                )
            ),
            "confidence_score": entity.confidence,
            "page_reference": int(entity.page_anchor.page_refs[0].page) + 1,
        }
    )

    # The google protobuf output schema for a sub-property is `type/sub-type`
    # where sub-type is the `entity_type_minor`
    if is_property:
        tmp_row_dict.update({"entity_type_minor": entity.type_.split("/")[1]})
    else:
        tmp_row_dict.update({"entity_type_minor": None})

    return tmp_row_dict


def _parse_raw_entity_table_row_from_dict(
    entity: dict,
    is_property: bool,  # blob: Optional[Blob] = None
) -> Dict[str, Any]:
    """
    Parse a single row for the entities_table.

    Parameters
    ----------
    entity: protobuf object
        A an entity from `result.document.entities` protobuf object.
    is_property: bool
        True if the element is a sub-level property entity.
    blob: gcs Blob
        The GCS Blob object

    Returns
    -------
    Dictionary type for a single row of the table.
    """

    # Set the base schema so if any entities are missing the one of these
    # values the row will be preserved with a None
    tmp_row_dict = gv_db.RAW_ENTITY_TABLE_DICT.copy()

    # hit a strange case where the protobuf returned an entity that didn't
    # exist on the page. catch this by checking if the list that holds the
    # bounding box is empty, since there will always be a bounding box
    # associated with a real entity.
    if not entity["page_anchor"]["page_refs"]:
        return {"entity_type_major": None}

    tmp_row_dict.update(
        {
            "doc_id": None,  # TODO update this with the unique identifier from blob.name
            "project_id": None,  # TODO this gets  updated with the unique id for the project
            "entity_type_major": entity["type_"].split("/")[0],
            "entity_value_raw": entity["mention_text"],
            "entity_value_norm": (
                db_utils.parse_norm_value(entity["normalized_value"], unit=False)
                if db_utils.parse_norm_value(entity["normalized_value"], unit=False)
                else None
            ),
            "unit": (
                db_utils.parse_norm_value(entity["normalized_value"], unit=True)
                if db_utils.parse_norm_value(entity["normalized_value"], unit=True)
                else None
            ),
            "bounding_box": (
                create_bounding_box(
                    entity["page_anchor"]["page_refs"][0]["bounding_poly"][
                        "normalized_vertices"
                    ]
                )
            ),
            "confidence_score": entity["confidence"],
            "page_reference": int(entity["page_anchor"]["page_refs"][0]["page"]) + 1,
            # "doc_type": doc_id.split("/")[3],
            # TODO create date_received from when the document was emailed or downloaded
            "date_received": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    )

    # The google protobuf output schema for a sub-property is `type/sub-type`
    # where sub-type is the `entity_type_minor`
    if is_property:
        tmp_row_dict.update({"entity_type_minor": entity["type_"].split("/")[1]})
    else:
        tmp_row_dict.update({"entity_type_minor": None})

    return tmp_row_dict


def create_bounding_box(
    coords: List[Dict[str, float]],
) -> Dict[str, List[float]]:
    """
    Takes the four coordinate corners and returns human readable
    keys, i.e. `ul` (upper left) `ur` (upper right) etc.

    Parameters
    ----------
    coords: list
        Corner coordinates from the document object for each entity

    Returns
    -------
    Dict[str, List[float, float]]
    """

    if coords:
        vert_key_list = ["ul", "ur", "lr", "ll"]
        bounding_poly_dict = {}
        for i, key in enumerate(vert_key_list):
            bounding_poly_dict[key] = [round(coords[i].x, 5), round(coords[i].y, 5)]
        return bounding_poly_dict
    else:
        return None
