from typing import Dict, List, Optional
from pydantic import BaseModel


# Cost Codes
class SubItems(BaseModel):
    name: str
    number: float
    id: str
    inputType: str
    isCurrency: bool
    required: bool
    type: str
    value: str
    subItems: List['SubItems']


class Divisions(BaseModel):
    name: str
    number: float
    subItems: List[SubItems]


class CostCodes(BaseModel):
    format: str
    currency: str
    updated: bool
    status: str
    divisions: List[Divisions]

    # Update all budgets when user updates the master cost code list


class UpdateBudgetDivision(BaseModel):
    name: str
    number: str


class UpdateBudgetSubDivision(BaseModel):
    name: str
    number: str
    divisionNumber: float


class UpdateBudgetCostCode(BaseModel):
    name: str
    number: str
    divisionNumber: float
    subDivNumber: float


class DeleteDivision(BaseModel):
    divisionNumber: float


class DeleteSubDivision(BaseModel):
    divisionNumber: float
    subDivNumber: float


class DeleteCostCode(BaseModel):
    divisionNumber: float
    subDivNumber: float
    costCodeNumber: float


class UpdateBudgets(BaseModel):
    addCostCodes: List[UpdateBudgetCostCode] | None
    addSubDivisions: List[UpdateBudgetSubDivision] | None
    addDivisions: List[UpdateBudgetDivision] | None
    deleteCostCodes: List[DeleteCostCode] | None
    deleteDivisions: List[DeleteDivision] | None
    deleteSubDivisions: List[DeleteSubDivision] | None


class ActualsItem(BaseModel):
    changeOrder: str | None
    costCodeName: str
    description: str
    division: float
    divisionName: str
    subDivision: float
    subDivisionName: str
    qtyAmt: str
    rateAmt: str
    totalAmt: str
    vendor: str
    group: str
    invoiceIds: List[str] | None = None
    laborFeeIds: List[str] | None = None


class CurrentActuals(BaseModel):
    __root__: Dict[str, ActualsItem]


class ChangeOrderActuals(BaseModel):
    __root__: Dict[str, CurrentActuals]

class ActualsItemV2(BaseModel):
    changeOrder: Optional[str] = None
    costCodeName: str
    description: Optional[str] = None
    recursiveLevel: Optional[List[int]] = None
    # division: float
    # divisionName: str
    # subDivision: float
    # subDivisionName: str
    qtyAmt: Optional[str] = None
    rateAmt: Optional[str] = None
    totalAmt: str
    vendor: str
    group: str
    invoiceIds: Optional[List[str]] = None
    laborFeeIds: Optional[List[str]] = None

class CurrentActualsV2(BaseModel):
    __root__: Dict[str, ActualsItemV2]

class ChangeOrderActualsV2(BaseModel):
    __root__: Dict[str, CurrentActualsV2]
