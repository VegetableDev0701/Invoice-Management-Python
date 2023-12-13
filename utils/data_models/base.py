from pydantic import BaseModel

class NameWithId(BaseModel):
    uuid: str
    name: str
