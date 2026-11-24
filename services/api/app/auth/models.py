from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.access.models import UserRole  # noqa: F401 - se reexporta: los códigos de rol sembrados


class UserRecord(BaseModel):
    """Usuario. `role_id` y `department_id` son claves foráneas SEPARADAS: ninguna se deriva de la otra.

    `role`, `department`, `rank` y `capabilities` no se guardan: el repositorio los resuelve desde el catálogo al leer,
    así un cambio de rol surte efecto en la siguiente petición (el JWT solo identifica a la persona).
    """

    id: int = Field(gt=0)
    email: EmailStr
    hashed_password: str
    is_active: bool = True
    account_type: Literal["human", "agent"] = "human"  # «agent»: cuenta de un agente automatizado (el audit log lo distingue de una persona)
    role_id: int = Field(gt=0)
    department_id: int | None = Field(default=None, gt=0)
    created_at: datetime
    role: str = ""
    rank: int = 0
    capabilities: list[str] = Field(default_factory=list)
    department: str | None = None


class ProfileRecord(BaseModel):
    id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    name: str = ""
    phone: str = ""
    address: str = ""


class UserCreate(BaseModel):
    """Registro público (POST /auth/register): siempre rol Empleado y sin departamento hasta que un Admin lo asigne."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email: EmailStr
    password: str = Field(min_length=8)
    name: str = ""
    phone: str = ""
    address: str = ""


class AdminUserCreate(UserCreate):
    """Alta de usuarios por un Admin (POST /users): rol y departamento se eligen aquí, de forma independiente."""

    role_id: int | None = Field(default=None, gt=0, description="Por defecto, el rol de menor rango (Empleado).")
    account_type: Literal["human", "agent"] = "human"
    department_id: int | None = Field(default=None, gt=0)


class UserUpdate(BaseModel):
    """PUT /users/{id}. El rol y el departamento NO se cambian aquí sino en PATCH /users/{id}/assignment (solo Admin)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    email: EmailStr | None = None
    is_active: bool | None = None


class UserResponse(BaseModel):
    """Vista de detalle de una cuenta (GET/PUT /users/{id}): solo campos
    seguros, nunca hashed_password."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    is_active: bool
    role_id: int
    role: str
    department_id: int | None
    department: str | None
    created_at: datetime


class UserListItem(BaseModel):
    """Fila del listado de administración (GET /users): forma más ligera que
    el detalle, sin timestamps de auditoría."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    role_id: int
    role: str
    department_id: int | None
    department: str | None
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
    """Identidad autenticada: rol Y departamento (ejes independientes) y las capacidades efectivas del rol,
    para que el backoffice oculte lo que no se puede hacer (el backend lo vuelve a comprobar siempre)."""

    email: EmailStr
    role_id: int
    role: str
    role_label: str
    rank: int
    department_id: int | None
    department: str | None
    department_label: str | None
    capabilities: list[str]
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
