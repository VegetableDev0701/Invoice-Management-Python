from typing import Dict, List, Any
from pydantic import BaseModel, Extra


# Update Project in Invoices
class Projects(BaseModel):
    name: str
    address: str
    uuid: str


class InvoiceProjects(BaseModel):
    __root__: Dict[str, Projects]


# Update invoices after processing
class BoundingBox(BaseModel):
    ul: List[float]
    ur: List[float | None]
    lr: List[float]
    ll: List[float] | None = None


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


class LineItemObject(BaseModel):
    __root__: Dict[str, LineItems]


class ProcessedData(BaseModel):
    approver: str | None = None
    change_order: ChangeOrderObject | None
    cost_code: str | None = None
    date_received: str | None = None
    invoice_id: str | None = None
    is_credit: bool | None = None
    line_items: LineItemObject | None = None
    line_items_toggle: bool | None = None
    # remove_from_change_order: str | None = None
    total_amount: str | None = None
    total_tax_amount: str | None = None
    vendor_name: str | None = None


class ProcessedInvoiceData(BaseModel):
    isProcessed: bool
    invoiceId: str
    project: Projects
    processedInvoiceData: ProcessedData


class GPTLineItem(BaseModel):
    description: str | None = None
    amount: str | None = None
    bounding_box: BoundingBox
    page: str


class GPTLineItems(BaseModel):
    __root__: Dict[str, GPTLineItem]
