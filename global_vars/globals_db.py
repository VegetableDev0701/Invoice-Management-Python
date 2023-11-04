RAW_ENTITY_TABLE_SCHEMA = [
    # "doc_id",
    "entity_type_major",
    "entity_type_minor",
    "entity_value_raw",
    "entity_value_norm",
    "unit",
    "bounding_box",
    "confidence_score",
    "page_reference",
    # "doc_type",
]
RAW_ENTITY_TABLE_DICT = dict.fromkeys(RAW_ENTITY_TABLE_SCHEMA)

DOCUMENT_INFO_TABLE_SCHEMA = [
    "doc_id",
    "project_id",
    "gcs_uri",
    "number_of_pages",
    "document_type",
    "date_received",
    "supplier_id",
    "processed",
    "approved",
    "total_tax_amount",
    "total_amount",
    "full_document_text",
    "cost_codes",
    "pages",
    "entities"
    # "page_resolution",
    # "page_resolution_unit",
    # "date_received",
    # "approved",
]
DOCUMENT_INFO_TABLE_DICT = dict.fromkeys(DOCUMENT_INFO_TABLE_SCHEMA)

PAGES_JSON_RECORD_KEYS = [
    "number",
    "width",
    "height",
    "resolution_unit",
    "image_content",
    "transition_matrix",
]

SUPPLIERS_TABLE_SCHEMA = [
    "supplier_id",
    "name",
    "address",
    "city",
    "state",
    "zip_code",
    "phone",
    "cost_codes",
    "is_confirmed",
]

SUPPLIERS_TABLE_DICT = dict.fromkeys(SUPPLIERS_TABLE_SCHEMA)
