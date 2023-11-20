from typing import Dict, List
from pydantic import BaseModel, Extra

from utils.data_models.formdata import MainCategories
from utils.data_models.invoices import ProcessedInvoiceDataItem
from utils.data_models.projects import SummaryLabor


# Add Change Order
class AddChangeOrderData(BaseModel):
    mainCategories: List[MainCategories]

    class Config:
        extra = Extra.allow
        validate_assignment = True


class ChangeOrderContentItem(BaseModel):
    costCode: str
    totalAmt: str
    qtyAmt: str
    rateAmt: str
    description: str
    vendor: str
    uuid: str
    isLaborFee: bool | None = None
    isInvoice: bool | None = None


class ChangeOrderContentItemDict(BaseModel):
    __root__: Dict[str, Dict[str, ChangeOrderContentItem]]


class ChangeOrderContent(BaseModel):
    __root__: Dict[str, ChangeOrderContentItemDict]


class SummaryChangeOrderData(BaseModel):
    name: str
    projectName: str
    clientName: str
    address: str
    workDescription: str
    subtotalAmt: str
    date: str
    uuid: str
    # invoices: List[str]
    content: ChangeOrderContent | dict


class FullChangeOrderDataToAdd(BaseModel):
    fullData: AddChangeOrderData
    summaryData: SummaryChangeOrderData


class BulkFullChangeOrderDataToAdd(BaseModel):
    fullData: Dict[str, AddChangeOrderData]
    summaryData: Dict[str, SummaryChangeOrderData]


class UpdateProcessedData(BaseModel):
    processedData: ProcessedInvoiceDataItem


class InvoiceProcessedData(BaseModel):
    __root__: Dict[str, UpdateProcessedData]


class DeleteChangeOrderData(BaseModel):
    removeChangeOrderIds: List[str]
    updateProcessedData: InvoiceProcessedData
    laborToUpdate: SummaryLabor
