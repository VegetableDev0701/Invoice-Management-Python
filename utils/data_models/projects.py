from typing import Dict, List
from pydantic import BaseModel, Extra

from utils.data_models.formdata import MainCategories, Labor, LaborSummaryItem
from utils.data_models.budgets import (
    Divisions,
    CurrentActuals,
    CurrentActualsV2,
    ChangeOrderActuals,
    ChangeOrderActualsV2,
)
from utils.data_models.invoices import Invoices
from utils.data_models.base import NameWithId


class AddProjectData(BaseModel):
    name: str
    isActive: bool
    mainCategories: List[MainCategories]
    numRecurringFees: int | None
    # projectId: str | None = None
    uuid: str | None = None

    class Config:
        extra = Extra.allow
        validate_assignment = True


class SummaryProjectData(BaseModel):
    projectName: str
    ownerName: str
    projectSuper: str
    estCompletionDate: str
    contractAmt: str
    address: str
    city: str

    class Config:
        extra = Extra.allow
        validate_assignment = True


class FullProjectDataToAdd(BaseModel):
    fullData: AddProjectData
    summaryData: SummaryProjectData


# Add Labor to Project
class AddLaborData(BaseModel):
    mainCategories: List[MainCategories]
    numCostCodes: int | None

    class Config:
        extra = Extra.allow
        validate_assignment = True


class LaborLineItemItem(BaseModel):
    cost_code: str
    number_of_hours: str
    work_description: str
    change_order: NameWithId | None
    amount: str


class LaborLineItems(BaseModel):
    __root__: Dict[str, LaborLineItemItem]


class SummaryLaborData(BaseModel):
    name: str
    rate: str
    line_items: LaborLineItems
    totalAmt: str
    payPeriod: str | None
    currentLabor: bool
    clientBillId: str | None = None
    uuid: str | None = None
    rowId: int | None = None


class SummaryLabor(BaseModel):
    __root__: Dict[str, SummaryLaborData]


class FullLaborDataToAdd(BaseModel):
    fullData: AddLaborData
    summaryData: SummaryLaborData


class ProjectBudget(BaseModel):
    format: str
    currency: str
    divisions: List[Divisions]


# Client bill
class InvoiceCurrentActuals(BaseModel):
    __root__: Dict[str, CurrentActuals]


class InvoiceChangeOrderCurrentActuals(BaseModel):
    __root__: Dict[str, ChangeOrderActuals]


class GroupedInvoiceActuals(BaseModel):
    invoice: InvoiceCurrentActuals
    laborFee: InvoiceCurrentActuals


class ClientBillData(BaseModel):
    actuals: GroupedInvoiceActuals
    actualsChangeOrders: InvoiceChangeOrderCurrentActuals


class Payment(BaseModel):
    total_due: str
    paid_amount: str
    status: str
    date_payment: str
    date_due: str


class BillSummary(BaseModel):
    billTitle: str
    boTax: str
    changeOrders: str | None
    createdAt: str | None
    insuranceLiability: str
    invoiceIds: List[str] | None
    laborFeeIds: List[str] | None
    numInvoices: float
    numChangeOrders: float
    payment: Payment | None
    profit: str
    salesTax: str
    salesTaxPercent: str
    subTotal: str
    total: str
    totalsByChangeOrder: Dict[str, float]
    uuid: str


class InvoiceCurrentActualsV2(BaseModel):
    __root__: Dict[str, CurrentActualsV2]


class InvoiceChangeOrderCurrentActualsV2(BaseModel):
    __root__: Dict[str, ChangeOrderActualsV2]


class GroupedInvoiceActualsV2(BaseModel):
    invoice: InvoiceCurrentActualsV2
    laborFee: InvoiceCurrentActualsV2


class ClientBillDataV2(BaseModel):
    actuals: GroupedInvoiceActualsV2
    actualsChangeOrders: InvoiceChangeOrderCurrentActualsV2


class AddClientBillData(BaseModel):
    invoiceIds: List[str] | None
    laborIds: List[str] | None
    clientBillSummary: BillSummary | None
    currentActuals: CurrentActualsV2 | None
    currentActualsChangeOrders: ChangeOrderActuals | ChangeOrderActualsV2 | None
    clientBillObj: ClientBillDataV2 | None


class UpdateClientBillData(BaseModel):
    invoices: Invoices | None
    clientBillSummary: BillSummary | None
    clientBillObj: ClientBillDataV2 | None
    labor: Labor | None
    laborSummary: List[LaborSummaryItem] | None


class ContractVendorObject(BaseModel):
    agave_uuid: str | None
    name: str | None
    uuid: str | None
    vendor_match_conf_score: float | None


class ContractSummaryData(BaseModel):
    projectName: str
    date: str
    contractAmt: str
    workDescription: str
    vendor: ContractVendorObject
    # uuid: str
    # vendor: str
    # vendor_match_conf_score: int | None = None
    # agave_uuid: str | None = None


class ContractEntry(BaseModel):
    gcs_img_uri: List[str]
    gcs_uri: str
    summaryData: ContractSummaryData
    uuid: str
