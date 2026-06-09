from pydantic import BaseModel


class ErrorEnvelope(BaseModel):
    detail: str
