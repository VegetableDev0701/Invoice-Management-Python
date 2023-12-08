from typing import Dict, List
from pydantic import BaseModel, Extra


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


class ChangeOrderObject(BaseModel):
    name: str
    uuid: str


class LineItems(BaseModel):
    description: str | None = None
    amount: str | None = None
    cost_code: str | None = None
    work_description: str | None = None
    change_order: ChangeOrderObject | None = None
    bounding_box: BoundingBox | None = None
    page: float | None = None
    number_of_hours: int | None = None
    billable: bool


class LineItemObject(BaseModel):
    __root__: Dict[str, LineItems]


class Vendor(BaseModel):
    name: str
    uuid: str | None


class ProcessedInvoiceDataItem(BaseModel):
    is_credit: bool | None = None
    approver: str | None = None
    total_tax_amount: str | None = None
    line_items: Dict[str, LineItems] | None = None
    vendor: Vendor
    change_order: ChangeOrderObject | None
    cost_code: str | None = None
    line_items_toggle: bool | None = None
    total_amount: str | None = None
    invoice_id: str | None = None
    date_received: str | None = None
    is_synced: str | None = None
    invoice_date: str | None = None
    is_credit: bool
    billable: bool


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


class ChangeOrder(BaseModel):
    name: str
    uuid: str


class InvoiceLineItemItem(BaseModel):
    description: str | None = None
    amount: str
    cost_code: str | None = None
    work_description: str | None = None
    page: int | None = None
    bounding_box: BoundingBox | None = None
    number_of_hours: int | None = None
    change_order: ChangeOrder | None = None


class ProcessedInvoiceData1(BaseModel):
    approver: str
    change_order: ChangeOrder | None
    cost_code: str | None = None
    date_received: str
    invoice_id: str | None
    is_credit: bool
    line_items: Dict[str, InvoiceLineItemItem] | None = None
    line_items_toggle: bool
    total_amount: str
    total_tax_amount: str
    vendor_name: str
    is_synced: str | None = None


class InvoiceItem(BaseModel):
    processedData: ProcessedInvoiceData1 | None = None

    class Config:
        extra = Extra.allow
        validate_assignment = True


class Invoices(BaseModel):
    __root__: Dict[str, InvoiceItem]
