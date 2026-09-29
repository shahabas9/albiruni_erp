from pydantic import BaseModel


class AskRequest(BaseModel):
    text: str
    # IANA zone of the user's browser, so "tomorrow at 3pm" means their 3pm.
    timezone: str = "Asia/Kolkata"


class ConfirmRequest(BaseModel):
    preview_token: str
