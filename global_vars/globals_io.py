# from enum import Enum
LOCATION = "us"  # Format is 'us' or 'eu'
INVOICE_PROCESSOR_ID = ""
RECEIPT_PROCESSOR_ID = ""
OCR_PROCESSOR_ID = ""  # ocr processor

GCS_OUTPUT_BUCKET = "gs://stak-customer-documents"
STAK_CUSTOMER_DOCUMENTS_BUCKET = "stak-customer-documents"
STAK_BASE_FORM_BUCKET = "stak-base-form-data"
STAK_COMPANY_FILES_BUCKET = "stak-company-files"

RAW_DOCS_UNPROCESSED_INVOICE_PATH = "raw-documents/unprocessed"
RAW_DOCS_PROCESSED_INVOICE_PATH = "raw-documents/processed"

RAW_DOCS_UNPROCESSED_CONTRACTS_PATH = "contracts/raw-documents/unprocessed"
RAW_DOCS_PROCESSED_CONTRACTS_PATH = "contracts/raw-documents/processed"

DOC_TYPE_INVOICE = "invoice"
DOC_TYPE_RECEIPT = "receipt"

MESSAGE_STREAM_RETRY_TIMEOUT = 15000
MESSAGE_STREAM_DELAY = 1
HEARTBEAT_INTERVAL = 5

BATCH_SIZE_CUTOFF = 50
COLLECTION_BATCH_SIZE = 75
FIRESTORE_QUERY_BATCH_SIZE = 30

RETRY_TIMES = 3

# needed for getting signed urls inside a google cloud run
SCOPES = [
    "https://www.googleapis.com/auth/devstorage.read_only",
    "https://www.googleapis.com/auth/iam",
]

BASE_URL = "https://api.agaveapi.com/"
AGAVE_EMPLOYEES_URL = BASE_URL + "employees"
AGAVE_VENDORS_URL = BASE_URL + "vendors"
AGAVE_CUSTOMERS_URL = BASE_URL + "customers"
AGAVE_AP_INVOICES_URL = BASE_URL + "ap-invoices"
AGAVE_AR_INVOICES_URL = BASE_URL + "ar-invoices"
AGAVE_PASSTHROUGH_URL = BASE_URL + "passthrough"
AGAVE_ITEMS_URL = BASE_URL + "items"

QBD_ITEM_TYPES = [
    "Service",
    "NonInventory",
    "OtherCharge",
    "Inventory",
    "InventoryAssembly",
    "FixedAsset",
    "Subtotal",
    "Discount",
    "Payment",
    "SalesTax",
    "SalesTaxGroup",
    "ItemGroup",
]

QBD_INIT_ITEM_TYPE = "Service"

QBD_VENDOR_EXT_NAMES_LOOKUP_KEY = "qbd_custom_vendor_ext_name_lookup"

INITIAL = 5
JITTER = 5
