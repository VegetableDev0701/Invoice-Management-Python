from typing import Dict, List
from pydantic import BaseModel, Extra

from utils.data_models.base import NameWithId


# Update Project in Invoices
class Project(BaseModel):
    name: str | None
    address: str | None
    uuid: str | None


class PredictedProject(BaseModel):
    name: str | None = None
    address: str | None = None
    uuid: str | None = None
    top_scores: Dict[str, float]
    score: float | None = None
    project_key: str | None = None


class InvoiceProjects(BaseModel):
    __root__: Dict[str, Project]


# Update invoices after processing
class BoundingBox(BaseModel):
    ul: List[float]
    ur: List[float | None]
    lr: List[float]
    ll: List[float] | None = None
    page: int | None = None


class LineItems(BaseModel):
    description: str | None = None
    amount: str | None = None
    cost_code: str | None = None
    work_description: str | None = None
    change_order: NameWithId | None = None
    bounding_box: BoundingBox | None = None
    page: float | None = None
    number_of_hours: int | None = None
    billable: bool


class LineItemObject(BaseModel):
    __root__: Dict[str, LineItems]


class ProcessedInvoiceDataItem(BaseModel):
    approver: str | None = None
    billable: bool
    change_order: NameWithId | None
    cost_code: str | None = None
    date_received: str | None = None
    expense_tax: bool
    invoice_date: str | None = None
    invoice_id: str | None = None
    is_credit: bool
    is_credit: bool | None = None
    is_synced: str | None = None
    line_items: Dict[str, LineItems] | None = None
    line_items_toggle: bool | None = None
    total_amount: str | None = None
    total_tax_amount: str | None = None
    vendor: NameWithId


class ProcessedInvoiceData(BaseModel):
    isProcessed: bool
    invoiceId: str
    project: Project
    processedInvoiceData: ProcessedInvoiceDataItem


class GPTLineItem(BaseModel):
    description: str | None = None
    amount: str | None = None
    bounding_box: BoundingBox
    page: str


class GPTLineItems(BaseModel):
    __root__: Dict[str, GPTLineItem]


class Page(BaseModel):
    height: float
    number: float
    resolution_unit: str
    image_transform: List[float] | None = None
    width: float


class Entity(BaseModel):
    entity_value_raw: str
    unit: str | None = None
    entity_value_norm: str | None = None
    page_reference: int
    bounding_box: BoundingBox | None = None
    entity_type_minor: str | None = None
    confidence_score: int


class InvoiceLineItemItem(BaseModel):
    description: str | None = None
    amount: str | None
    cost_code: str | None = None
    work_description: str | None = None
    page: int | None = None
    bounding_box: BoundingBox | None = None
    number_of_hours: int | None = None
    change_order: NameWithId | None = None


class ProcessedInvoiceData1(BaseModel):
    approver: str
    change_order: NameWithId | None
    cost_code: str | None = None
    date_received: str
    invoice_id: str | None
    is_credit: bool
    line_items: Dict[str, InvoiceLineItemItem] | None = None
    line_items_toggle: bool
    total_amount: str
    total_tax_amount: str
    vendor_name: str | None = None
    vendor: NameWithId | None = None
    is_synced: str | None = None

class PredictedSupplier(BaseModel):
  supplier_name: str
  isGPT: bool
  agave_uuid: str | None
  score: str | float | None
  vendor_match_conf_score: float | None
  uuid: str | None

class InvoiceItemForSingle(BaseModel):
    approved: bool
    client_bill_id: str | None
    currency: Entity | None
    date_received: str
    doc_id: str
    document_type: str | None
    gcs_img_uri: List[str]
    gcs_uri: str
    invoice_date: Entity | None
    invoice_id: Entity | None
    invoice_type: Entity | None
    is_attached_to_bill: bool
    line_items: List[Entity]
    line_items_gpt: GPTLineItems | None
    net_amount: Entity | None
    number_of_pages: float
    pages: List[Page]
    payment_terms: Entity | None
    processed: bool
    predicted_supplier_name: PredictedSupplier | None
    predicted_project: PredictedProject | None
    processedData: ProcessedInvoiceDataItem
    project: Project | None
    project_id: str | None
    receiver_address: Entity | None
    receiver_name: Entity | None
    supplier_address: Entity | None
    supplier_id: str | None
    supplier_name: Entity | None
    total_amount: Entity | None
    total_tax_amount: Entity | None

class InvoiceItem(BaseModel):
    processedData: ProcessedInvoiceData1 | None = None

    class Config:
        extra = Extra.allow
        validate_assignment = True


class Invoices(BaseModel):
    __root__: Dict[str, InvoiceItem]
