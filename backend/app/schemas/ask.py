from pydantic import BaseModel


class AskRequest(BaseModel):
    text: str


class ConfirmRequest(BaseModel):
    preview_token: str
