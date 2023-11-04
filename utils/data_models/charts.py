from typing import Dict, List
from pydantic import BaseModel

from utils.data_models.budgets import ActualsItem, ChangeOrderActuals

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
