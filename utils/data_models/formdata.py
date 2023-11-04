from typing import Dict, List
from pydantic import BaseModel, Extra


class SelectMenuOptions(BaseModel):
    id: int
    label: str


class Items(BaseModel):
    label: str
    value: str
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
