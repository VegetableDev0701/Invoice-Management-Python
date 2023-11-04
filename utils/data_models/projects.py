from typing import Dict, List
from pydantic import BaseModel, Extra

from utils.data_models.formdata import MainCategories
from utils.data_models.budgets import Divisions, CurrentActuals, ChangeOrderActuals
from utils.data_models.invoices import ChangeOrderObject


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
    change_order: ChangeOrderObject | None
    amount: str


class LaborLineItems(BaseModel):
    __root__: Dict[str, LaborLineItemItem]


class SummaryLaborData(BaseModel):
    name: str
    rate: str
    line_items: LaborLineItems
    totalAmt: str
    payPeriod: str
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


class BillSummary(BaseModel):
    billTitle: str
    changeOrders: str | None
    subTotal: str
    budgetedSalesTax: str
    profit: str
    insuranceLiability: str
    total: str
    boTax: str
    numInvoices: float
    numChangeOrders: float
    # totalLaborFeesAmount: str
    # totalSubInvoiceAmount: str
    uuid: str
    totalsByChangeOrder: Dict[str, float]
    laborFeeIds: List[str] | None
    invoiceIds: List[str] | None


class AddClientBillData(BaseModel):
    invoiceIds: List[str] | None
    laborIds: List[str] | None
    clientBillSummary: BillSummary | None
    currentActuals: CurrentActuals | None
    currentActualsChangeOrders: ChangeOrderActuals | None
    clientBillObj: ClientBillData | None
