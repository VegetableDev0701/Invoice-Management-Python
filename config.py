import os

from dotenv import load_dotenv

PROJECT_NAME = "stak-app"
FORM_COLLECTION = "forms"
CUSTOMER_DOCUMENT_BUCKET = "stak-customer-documents"

if os.getenv("ENV") == "development":
    load_dotenv()
    AGAVE_ACCOUNT_TOKEN = os.getenv("DEMO_QBD_ACCOUNT_TOKEN")
else:
    AGAVE_ACCOUNT_TOKEN = None

AGAVE_CLIENT_ID = os.getenv("AGAVE_CLIENT_ID")
AGAVE_CLIENT_SECRET = os.getenv("AGAVE_CLIENT_SECRET")
AGAVE_API_VERSION = os.getenv("AGAVE_API_VERSION")
AGAVE_TOKEN_EXCHANGE_URL = os.getenv("AGAVE_TOKEN_EXCHANGE_URL")
AGAVE_LINK_CONNECTION_URL = os.getenv("AGAVE_LINK_CONNECTION_URL")


class Config:
    BATCH_LIMIT = 200
    THEFUZZ_SCORE_CUTOFF = 40
    CUSTOMER_REGEX_POST_CHARACTERS = 40
    MATCH_CUSTOMER_REGEX = ["customer", r"ref |reference"]
    PREDICTION_CONFIDENCE_CUTOFF = 0.60
    PREDICTION_CONFIDENCE_CUTOFF_WITH_ADDRESS_MATCH = 0.1
    N_TOP_SCORES_TO_KEEP = 5
    VENDOR_NAME_CONFIDENCE_CUTOFF = 0.75
    AGAVE_CLIENT_ID = AGAVE_CLIENT_ID
    AGAVE_CLIENT_SECRET = AGAVE_CLIENT_SECRET
    AGAVE_ACCOUNT_TOKEN = AGAVE_ACCOUNT_TOKEN
    AGAVE_API_VERSION = AGAVE_API_VERSION
    AGAVE_TOKEN_EXCHANGE_URL = AGAVE_TOKEN_EXCHANGE_URL
    AGAVE_LINK_CONNECTION_URL = AGAVE_LINK_CONNECTION_URL

    def __init__(self, company_id, project_id):
        self.company_id = company_id
        self.project_id = project_id


class ProjectPredConfig:
    def __init__(self, address_choices, owner_choices, model, doc_emb):
        self.address_choices = address_choices
        self.owner_choices = owner_choices
        self.model = model
        self.doc_emb = doc_emb
