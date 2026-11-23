from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator


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
    """Vista de detalle de una cuenta (GET/PUT /users/{id}): solo campos
    seguros, nunca hashed_password."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    is_active: bool
    role: UserRole
    created_at: datetime


class UserListItem(BaseModel):
    """Fila del listado de administración (GET /users): forma más ligera que
    el detalle, sin timestamps de auditoría."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role: UserRole
    is_active: bool


class RegisterResponse(BaseModel):
    """Respuesta de POST /users (registro). El email ya viaja en la petición,
    así que no se devuelve: solo el id de la cuenta creada y un mensaje."""

    id: int
    message: str = "Cuenta creada correctamente"


class LoginRequest(BaseModel):
    email: EmailStr | None = None
    username: EmailStr | None = None
    password: str

    @model_validator(mode="after")
    def _require_an_identifier(self) -> "LoginRequest":
        # Antes, sin email ni username, login_email valía "none" y se
        # intentaba autenticar contra esa cadena.
        if self.email is None and self.username is None:
            raise ValueError("Debes indicar email o username")
        return self

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


class ProfilePublic(BaseModel):
    """Proyección del perfil que ve su propio dueño. Deja fuera el id del
    documento y la clave foránea user_id: son detalles de almacenamiento y el
    cliente no los usa (el perfil siempre se pide como /profiles/me)."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    phone: str
    address: str


class MeResponse(BaseModel):
    email: EmailStr
    role: UserRole
    profile: ProfilePublic | None


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
