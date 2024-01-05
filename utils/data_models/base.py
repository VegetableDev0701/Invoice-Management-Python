from pydantic import BaseModel


class NameWithId(BaseModel):
    uuid: str | None
    name: str
