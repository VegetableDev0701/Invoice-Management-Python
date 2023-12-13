from typing import Dict, List
from pydantic import BaseModel, Extra

from utils.data_models.formdata import MainCategories


class AddVendordata(BaseModel):
    name: str | None = None
    mainCategories: List[MainCategories]
    vendorId: str | None = None
    uuid: str | None = None

    class Config:
        extra = Extra.allow
        validate_assignment = True


class SummaryVendorData(BaseModel):
    vendorName: str
    uuid: str
    email: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zipCode: str | None = None
    businessLicNumber: str | None = None
    businessLicExpirationDate: str | None = None
    insuranceName: str | None = None
    insuranceExpirationDate: str | None = None
    landiLicNumber: str | None = None
    landiExpirationDate: str | None = None
    w9OnFile: bool | None
    cellPhone: str | None = None
    zipCode: str | None = None
    vendorType: str | None = None
    primaryContact: str | None = None
    insuranceCoverageAmt: str | None = None
    bondCompanyName: str | None = None
    bondAmt: str | None = None
    workPhone: str | None = None
    workersCompExpirationDate: str | None = None
    taxNumber: str | None = None
    agave_uuid: str | None = None


class FullVendorDataToAdd(BaseModel):
    fullData: AddVendordata
    summaryData: SummaryVendorData


class FullBulkVendorDataToAdd(BaseModel):
    fullData: Dict[str, AddVendordata]
    summaryData: Dict[str, SummaryVendorData]


class PredictedVendorModel(BaseModel):
    supplier_name: str | None
    isGPT: bool
    score: str | None = None
    uuid: str | None = None
    agave_uuid: str | None = None
    vendor_match_conf_score: float | None
