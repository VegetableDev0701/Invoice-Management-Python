from typing import Dict, List
from pydantic import BaseModel, Extra

from utils.data_models.formdata import (
    MainCategories, 
    Labor,
    LaborSummaryItem
)
from utils.data_models.budgets import (
    Divisions,
    CurrentActuals,
    CurrentActualsV2,
    ChangeOrderActuals,
    ChangeOrderActualsV2,
)
from utils.data_models.invoices import ( 
    ChangeOrderObject,
    Invoices
)


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
    createdAt: str | None


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

