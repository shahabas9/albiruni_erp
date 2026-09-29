from uuid import UUID

from pydantic import BaseModel, Field


class RoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    permissions: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    permissions: list[str] | None = None


class RoleOut(BaseModel):
    id: UUID
    name: str
    permissions: list[str]


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    display_name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=200)
    role_id: UUID
    locale: str = "en-IN"


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    role_id: UUID | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)
    locale: str | None = None
    active: bool | None = None


class UserOut(BaseModel):
    id: UUID
    username: str
    display_name: str
    role_id: UUID
    role_name: str | None
    locale: str
    active: bool
