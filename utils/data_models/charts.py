from typing import Dict, List, Optional
from pydantic import BaseModel

from utils.data_models.budgets import (
    ActualsItem,
    ActualsItemV2,
    ChangeOrderActuals,
    ChangeOrderActualsV2,
)

###
# Budget to Actuals Chart Data
###


class CostCodeB2AData(BaseModel):
    subDivision: float | str
    subDivisionName: str
    costCodeLabels: List[str]
    costCodeTotals: List[float]
    costCodeNumbers: List[str]
    costCodeActuals: List[float]


class SubDivisionB2AData(BaseModel):
    __root__: Dict[str, CostCodeB2AData]


class DivisionData(BaseModel):
    division: float | str
    divisionName: str
    subDivisionLabels: List[str]
    subDivisionTotals: List[float]
    subDivisionActuals: List[float]
    subDivisions: SubDivisionB2AData


class ChartData(BaseModel):
    __root__: Dict[str, DivisionData]


# class ChangeOrderCostCodeItem(BaseModel):
#     changeOrder: str | None
#     costCodeName: str
#     division: float
#     divisionName: str
#     laborFeeIds: List[str] | None = None
#     invoiceIds: List[str] | None = None
#     subDivision: float
#     subDivisionName: str
#     value: float


class ChangeOrderChartDataItem(BaseModel):
    totalValue: float | None
    actualValue: float | None
    # invoiceIds: List[str] | None = None
    # laborFeeIds: List[str] | None = None
    costCodeObj: Dict[str, ActualsItem] | None = None


class ChangeOrderChartData(BaseModel):
    __root__: Dict[str, ChangeOrderChartDataItem]


class FullB2AData(BaseModel):
    b2aChartData: ChartData
    b2aChartDataChangeOrder: ChangeOrderChartData | None
    updatedCurrentActualsChangeOrders: ChangeOrderActuals | None
    currentGrandTotal: Dict[str, float]
    currentBudgetedTotal: Dict[str, float]
    currentChangeOrderTotal: Dict[str, float]


class ChangeOrderChartDataItemV2(BaseModel):
    totalValue: float | None
    actualValue: float | None
    # invoiceIds: List[str] | None = None
    # laborFeeIds: List[str] | None = None
    costCodeObj: Dict[str, ActualsItemV2] | None = None


class ChangeOrderChartDataV2(BaseModel):
    __root__: Dict[str, ChangeOrderChartDataItemV2]


class CostCodeB2ADataV2(BaseModel):
    number: str | None
    name: Optional[str] = None
    value: Optional[str] = None
    actual: Optional[str] = None
    subItems: Optional[List["CostCodeB2ADataV2"]] = None


class DivisionDataV2(BaseModel):
    number: str
    name: Optional[str] = None
    subItems: Optional[List[CostCodeB2ADataV2]] = None


class ChartDataV2(BaseModel):
    divisions: Optional[List[DivisionDataV2]] = None


class FullB2ADataV2(BaseModel):
    b2aChartData: ChartDataV2
    b2aChartDataChangeOrder: ChangeOrderChartDataV2 | None
    updatedCurrentActualsChangeOrders: ChangeOrderActualsV2 | None
    currentGrandTotal: Dict[str, float]
    currentBudgetedTotal: Dict[str, float]
    currentChangeOrderTotal: Dict[str, float]


class BaseReportDataItem(BaseModel):
    title: str
    budgetAmount: str
    actualAmount: str
    difference: str
    percent: str
    depth: int


class B2AReport(BaseModel):
    service: List[BaseReportDataItem]
    serviceTotal: BaseReportDataItem
    otherCharges: List[BaseReportDataItem]
    otherChargesTotal: BaseReportDataItem
    contractTotal: BaseReportDataItem
    changeOrder: List[BaseReportDataItem]
    changeOrderTotal: BaseReportDataItem
    grandTotal: BaseReportDataItem
