from typing import Dict, List
from pydantic import BaseModel, Extra


## BASE DATA
class Meta(BaseModel):
    current_page: int
    has_more_results: bool


class Address(BaseModel):
    city: str | None
    country: str | None
    postal_code: str | None
    state: str | None
    street_1: str | None
    street_2: str | None


class BaseSourceDataItem(BaseModel):
    ListId: str
    TimeCreated: str
    TimeModified: str
    EditSequence: str
    Name: str
    IsActive: str


class BaseResponseData(BaseModel):
    id: str
    source_id: str
    source_create_time: str
    source_update_time: str


class BaseSourceData(BaseModel):
    path: str
    content_type: str


class BaseResponseDataTop(BaseModel):
    meta: Meta


## VENDORS
class VendorSourceDataItem(BaseSourceDataItem):
    class Config:
        extra = Extra.allow
        validate_assignment = True


class VendorSourceData(BaseSourceData):
    data: VendorSourceDataItem


class VendorData(BaseResponseData):
    address: Address
    alternate_name: str | None
    code: str | None
    email: str | None
    fax: str | None
    name: str
    phone: str | None
    project_id: str | None
    status: str
    tax_number: str | None
    terms: str | None
    type: str | None
    website: str | None
    source_data: VendorSourceData


class VendorResponseData(BaseResponseDataTop):
    data: List[VendorData]


## ITEMS
class ItemSourceDataItem(BaseSourceDataItem):
    FullName: str | None
    SubLevel: str | None = None
    ParentRef: Dict[str, str] | None = None

    class Config:
        extra = Extra.allow
        validate_assignment = True


class ParentRefModel(BaseModel):
    ListId: str
    FullName: str


class ItemSourceDataItem(BaseSourceDataItem):
    ParentRef: ParentRefModel | None = None

    class Config:
        extra = Extra.allow
        validate_assignment = True


class ItemSourceData(BaseSourceData):
    data: ItemSourceDataItem


class ItemData(BaseResponseData):
    asset_account_id: str | None
    description: str | None
    expense_account_id: str | None
    income_account_id: str | None
    name: str
    status: str | None
    type: str
    unit_cost: str | None
    unit_price: str | None
    source_data: ItemSourceData


class ItemResponseDataData(BaseResponseDataTop):
    data: List[ItemData]


class ItemResponseData(BaseModel):
    url: str
    status: str | int
    data: ItemResponseDataData


class ItemResponse:
    List[ItemResponseData]
