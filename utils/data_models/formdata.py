from typing import Dict, List
from pydantic import BaseModel


class SelectMenuOptions(BaseModel):
    id: int
    label: str


class Items(BaseModel):
    label: str
    value: str | None = None
    id: str
    type: str | None = None
    required: bool | None = None
    errormessage: str | None = None
    isCurrency: bool | None = None
    isPhoneNumber: bool | None = None
    isAddress: bool | None = None
    isOnOverlay: bool | None = None
    validFunc: str | None = None
    inputType: str | None = None
    sideButton: bool | None = None
    buttonText: str | None = None
    buttonPath: str | None = None
    selectMenuOptions: List[SelectMenuOptions] | None = None


class AddressItems(BaseModel):
    items: List[Items]


class InputElements(BaseModel):
    name: str | None = None
    addressElements: List[AddressItems] | None = None
    items: List[Items] | None = None


class MainCategories(BaseModel):
    name: str
    inputElements: List[InputElements]


# Acount Settings
class AccountSettings(BaseModel):
    name: str
    mainCategories: List[MainCategories]


class ChangeOrder(BaseModel):
    uuid: str
    name: str


class LaborData(BaseModel):
    numCostCodes: int
    name: str | None = None
    uuid: str | None = None
    mainCategories: List[MainCategories]


class Labor(BaseModel):
    __root__: Dict[str, LaborData]


class LaborLineItemItem(BaseModel):
    cost_code: str
    work_description: str
    number_of_hours: str
    change_order: ChangeOrder | None = None
    amount: str


class LaborSummaryItem(BaseModel):
    uuid: str
    name: str
    rate: str
    line_items: Dict[str, LaborLineItemItem]
    payPeriod: str
    totalAmt: str
    clientBillId: str | None = None
    currentLabor: bool
