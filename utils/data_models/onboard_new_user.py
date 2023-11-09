from pydantic import BaseModel

class UpdateUserInfo(BaseModel):
    company_id: str
    company_name: str
    user_id: str
    user_name: str
    business_address: str | None = None
    business_city: str | None = None
    business_state: str | None = None
    business_zip: str | None = None
