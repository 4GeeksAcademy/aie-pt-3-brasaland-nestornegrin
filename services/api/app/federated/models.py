"""Autenticación federada: el VÍNCULO usuario ↔ proveedor externo (no la sesión de Google) y el registro de auditoría."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Provider = Literal["google"]  # `apple` es opcional en el BRIEFING y no se ofrece
SUPPORTED_PROVIDERS: tuple[str, ...] = ("google",)

class FederatedIdentity(BaseModel):
    """Qué se guarda: SOLO el vínculo. Nunca access/refresh tokens ni credenciales de Google."""

    id: int = Field(gt=0)
    user_id: int = Field(gt=0)
    provider: str
    provider_user_id: str  # `sub` de Google: único junto con `provider`
    email_at_link_time: str  # instantánea informativa, NO es la clave de identidad
    linked_at: datetime


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    redirect_uri: str | None = Field(default=None, max_length=500)  # debe coincidir EXACTAMENTE con la lista blanca


class CompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=1, max_length=2048)
    state: str = Field(min_length=1, max_length=256)
    redirect_uri: str = Field(min_length=1, max_length=500)


class StartResponse(BaseModel):
    authorization_url: str


class ProviderStatus(BaseModel):
    provider: str
    configured: bool


class ProvidersResponse(BaseModel):
    enabled: bool
    providers: list[ProviderStatus]


class LinkedProvider(BaseModel):
    provider: str
    linked: bool
    email_at_link_time: str | None = None
    linked_at: datetime | None = None


class LinkedAccountsResponse(BaseModel):
    has_password: bool
    access_methods: int  # contraseña (si hay) + proveedores vinculados
    providers: list[LinkedProvider]


class LinkResponse(BaseModel):
    message: str
    account: LinkedProvider
    accounts: LinkedAccountsResponse


class UnlinkResponse(BaseModel):
    message: str
    accounts: LinkedAccountsResponse

