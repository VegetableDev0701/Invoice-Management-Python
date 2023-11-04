from typing import Dict, List
from pydantic import BaseModel, Extra

from utils.data_models.formdata import MainCategories


class AddVendordata(BaseModel):
    name: str
    mainCategories: List[MainCategories]
    vendorId: str | None = None
    uuid: str | None = None

    class Config:
        extra = Extra.allow
        validate_assignment = True


class SummaryVendorData(BaseModel):
    vendorName: str
    email: str
    address: str
    city: str
    state: str
    zipCode: str
    businessLicNumber: str
    businessLicExpirationDate: str
    insuranceName: str
    insuranceExpirationDate: str
    landiLicNumber: str
    landiExpirationDate: str

    class Config:
        extra = Extra.allow
        validate_assignment = True


class FullVendorDataToAdd(BaseModel):
    fullData: AddVendordata
    summaryData: SummaryVendorData
