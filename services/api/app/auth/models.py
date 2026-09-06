from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRole(str, Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    USER = "user"


class UserRecord(BaseModel):
    id: int = Field(gt=0)
    email: EmailStr
    hashed_password: str
    is_active: bool = True
    role: UserRole = UserRole.USER
    created_at: datetime


class ProfileRecord(BaseModel):
    id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    name: str = ""
    phone: str = ""
    address: str = ""


class UserCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8)
    name: str = ""
    phone: str = ""
    address: str = ""


class UserUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email: EmailStr | None = None
    role: UserRole | None = None
    is_active: bool | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    is_active: bool
    role: UserRole
    created_at: datetime


class LoginRequest(BaseModel):
    email: EmailStr | None = None
    username: EmailStr | None = None
    password: str

    @property
    def login_email(self) -> str:
        return str(self.email or self.username).lower()


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = None
    phone: str | None = None
    address: str | None = None


class ProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    name: str
    phone: str
    address: str


class MeResponse(BaseModel):
    email: EmailStr
    role: UserRole
    profile: ProfileResponse | None


class PasswordResetRecord(BaseModel):
    id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    token_hash: str
    expires_at: datetime
    used: bool = False
    created_at: datetime


class ForgotPasswordRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    token: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    current_password: str
    new_password: str = Field(min_length=8)


class MessageResponse(BaseModel):
    message: str
