"""Autenticación federada (Google). Dos flujos separados que comparten proveedor pero NO lógica:

* VINCULAR  — solo desde el perfil de un usuario YA autenticado: `link/start` + `link/complete` (exigen sesión).
* LOGIN     — solo para cuentas que ya tienen ese proveedor vinculado: `login/start` + `login/complete` (públicos).
              Una identidad sin vincular se RECHAZA (403) y no se crea ninguna cuenta ni fila de usuario.

Ambos validan `state` (aleatorio, de un solo uso, atado al flujo y al usuario) y `redirect_uri` (lista blanca exacta).
La sesión que emite el login federado es la misma (`create_access_token`) que la del login tradicional: misma caducidad
y misma revocación (`get_current_user` rechaza al usuario desactivado).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from app import security as limits
from app.audit.recorder import note
from app.auth.dependencies import get_current_user
from app.auth.models import TokenResponse
from app.auth.security import create_access_token

from .models import (
    SUPPORTED_PROVIDERS,
    CompleteRequest,
    LinkedAccountsResponse,
    LinkedProvider,
    LinkResponse,
    ProvidersResponse,
    ProviderStatus,
    StartRequest,
    StartResponse,
    UnlinkResponse,
)
from .oauth import OAuthError, OAuthProvider, allowed_redirect_uris, default_redirect_uri, federated_enabled, get_oauth_provider_by_name
from .repository import IdentityAlreadyLinked

logger = logging.getLogger("brasaland.audit")

NOT_LINKED_MESSAGE = ("Esta cuenta de Google no está vinculada a ninguna cuenta de Brasaland. "
                      "Regístrate primero con tu correo y contraseña y vincula Google desde tu perfil.")
INVALID_STATE_MESSAGE = "La solicitud de inicio de sesión no es válida o ha caducado. Inténtalo de nuevo."


def get_oauth_provider(provider: str) -> OAuthProvider:
    """Dependencia del proveedor (se sustituye en las pruebas por un Google simulado)."""
    found = get_oauth_provider_by_name(provider)
    if found is None or provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(status_code=404, detail="Proveedor de identidad no soportado")
    return found


def _require_available(provider: OAuthProvider) -> None:
    if not federated_enabled():
        raise HTTPException(status_code=403, detail="El acceso con proveedores externos está desactivado en este despliegue.")
    if not provider.is_configured():
        raise HTTPException(status_code=503, detail="El proveedor externo no está configurado en el servidor.")


def _resolve_redirect(requested: str | None) -> str:
    uri = requested or default_redirect_uri()
    if not uri or uri not in allowed_redirect_uris():  # coincidencia exacta con la lista blanca
        raise HTTPException(status_code=400, detail="redirect_uri no permitido")
    return uri


def _accounts(user) -> LinkedAccountsResponse:
    from app.main import federated_repository

    identities = {i.provider: i for i in federated_repository.for_user(user.id)}
    providers = [LinkedProvider(provider=p, linked=p in identities,
                                email_at_link_time=identities[p].email_at_link_time if p in identities else None,
                                linked_at=identities[p].linked_at if p in identities else None) for p in SUPPORTED_PROVIDERS]
    has_password = bool(user.hashed_password)
    return LinkedAccountsResponse(has_password=has_password, access_methods=int(has_password) + len(identities), providers=providers)


def create_federated_router() -> APIRouter:
    router = APIRouter(prefix="/auth/federated", tags=["federated-auth"])

    @router.get("/providers", response_model=ProvidersResponse)
    def available_providers() -> ProvidersResponse:
        """Público: qué botones mostrar en el login. Con el interruptor apagado (tablets compartidas) no se ofrece ninguno."""
        enabled = federated_enabled()
        return ProvidersResponse(enabled=enabled, providers=[
            ProviderStatus(provider=name, configured=enabled and bool((get_oauth_provider_by_name(name) or _Missing()).is_configured()))
            for name in SUPPORTED_PROVIDERS])

    @router.get("", response_model=LinkedAccountsResponse)
    def my_accounts(user=Depends(get_current_user)) -> LinkedAccountsResponse:
        return _accounts(user)

    # ------------------------------------------------------------------ flujo 1 · VINCULAR (sesión obligatoria)
    @router.post("/{provider}/link/start", response_model=StartResponse)
    def link_start(payload: StartRequest, provider: OAuthProvider = Depends(get_oauth_provider), user=Depends(get_current_user)) -> StartResponse:
        from app.main import federated_repository

        _require_available(provider)
        redirect_uri = _resolve_redirect(payload.redirect_uri)
        state = federated_repository.issue_state("link", redirect_uri, user.id)
        return StartResponse(authorization_url=provider.authorization_url(state, redirect_uri))

    @router.post("/{provider}/link/complete", response_model=LinkResponse)
    def link_complete(payload: CompleteRequest, request: Request, provider: OAuthProvider = Depends(get_oauth_provider),
                      user=Depends(get_current_user)) -> LinkResponse:
        from app.main import federated_repository

        _require_available(provider)
        redirect_uri = _resolve_redirect(payload.redirect_uri)
        stored = federated_repository.consume_state(payload.state)
        if stored is None or stored["purpose"] != "link" or stored["user_id"] != user.id or stored["redirect_uri"] != redirect_uri:
            raise HTTPException(status_code=400, detail=INVALID_STATE_MESSAGE)
        try:
            identity = provider.exchange_code(payload.code, redirect_uri)
        except OAuthError:
            raise HTTPException(status_code=400, detail="No se pudo validar la cuenta con el proveedor. Inténtalo de nuevo.")
        if any(i.provider == provider.name for i in federated_repository.for_user(user.id)):
            raise HTTPException(status_code=409, detail="Ya tienes una cuenta de este proveedor vinculada. Desvincúlala antes de vincular otra.")
        try:
            link = federated_repository.link(user.id, identity.provider, identity.provider_user_id, identity.email)
        except IdentityAlreadyLinked:
            # No se dice a QUIÉN pertenece: solo que esa identidad ya está en uso.
            logger.warning("federated_link_refused provider=%s user_id=%s reason=identity_in_use", identity.provider, user.id)
            raise HTTPException(status_code=409, detail="Esa cuenta de Google ya está vinculada a otro usuario de Brasaland.")
        note(request, resource_id=link.provider, details={"provider": link.provider, "provider_user_id": link.provider_user_id})
        logger.info("federated_link user_id=%s provider=%s", user.id, link.provider)
        accounts = _accounts(user)
        account = next(p for p in accounts.providers if p.provider == link.provider)
        return LinkResponse(message=f"Listo: tu cuenta de Google ({link.email_at_link_time}) quedó vinculada.", account=account, accounts=accounts)

    @router.delete("/{provider}", response_model=UnlinkResponse)
    def unlink(request: Request, provider: OAuthProvider = Depends(get_oauth_provider), user=Depends(get_current_user)) -> UnlinkResponse:
        from app.main import federated_repository

        current = _accounts(user)
        if not any(p.provider == provider.name and p.linked for p in current.providers):
            raise HTTPException(status_code=404, detail="Ese proveedor no está vinculado a tu cuenta.")
        if current.access_methods <= 1:  # Google es el ÚNICO método: la API lo rechaza (la interfaz avisa antes)
            raise HTTPException(status_code=409, detail="Google es tu único método de acceso. Crea una contraseña o vincula otro proveedor antes de desvincularlo.")
        removed = federated_repository.unlink(user.id, provider.name)
        note(request, resource_id=removed.provider, details={"provider": removed.provider, "provider_user_id": removed.provider_user_id})
        logger.info("federated_unlink user_id=%s provider=%s", user.id, removed.provider)
        return UnlinkResponse(message="Cuenta de Google desvinculada.", accounts=_accounts(user))

    # ------------------------------------------------------------------ flujo 2 · LOGIN (solo cuentas ya vinculadas)
    @router.post("/{provider}/login/start", response_model=StartResponse)
    def login_start(payload: StartRequest, provider: OAuthProvider = Depends(get_oauth_provider)) -> StartResponse:
        from app.main import federated_repository

        _require_available(provider)
        redirect_uri = _resolve_redirect(payload.redirect_uri)
        state = federated_repository.issue_state("login", redirect_uri, None)
        return StartResponse(authorization_url=provider.authorization_url(state, redirect_uri))

    @router.post("/{provider}/login/complete", response_model=TokenResponse)
    def login_complete(payload: CompleteRequest, request: Request, provider: OAuthProvider = Depends(get_oauth_provider)) -> TokenResponse:
        from app.main import federated_repository, user_repository

        _require_available(provider)
        ip = limits.client_ip(request)
        limits.login_by_ip.check(ip)
        redirect_uri = _resolve_redirect(payload.redirect_uri)
        stored = federated_repository.consume_state(payload.state)
        if stored is None or stored["purpose"] != "login" or stored["redirect_uri"] != redirect_uri:
            limits.login_by_ip.record(ip)
            raise HTTPException(status_code=400, detail=INVALID_STATE_MESSAGE)
        try:
            identity = provider.exchange_code(payload.code, redirect_uri)
        except OAuthError:
            limits.login_by_ip.record(ip)
            raise HTTPException(status_code=400, detail="No se pudo validar la cuenta con el proveedor. Inténtalo de nuevo.")
        link = federated_repository.find(identity.provider, identity.provider_user_id)
        user = user_repository.get(link.user_id) if link else None
        if link is None or user is None or not user.is_active:
            # RECHAZO: nunca se crea una cuenta. Queda auditado (user_id nulo si ni siquiera hay vínculo).
            limits.login_by_ip.record(ip)
            note(request, user=user, label=identity.email, resource_id=identity.provider,
                 details={"provider": identity.provider, "provider_user_id": identity.provider_user_id,
                          "reason": "not_linked" if link is None else "inactive"})
            logger.warning("federated_login_rejected provider=%s ip=%s", identity.provider, ip)
            raise HTTPException(status_code=403, detail=NOT_LINKED_MESSAGE if link is None else "Esta cuenta está desactivada.",
                                headers={"X-Federated-Error": "not_linked" if link is None else "inactive"})
        note(request, user=user, resource_id=link.provider, details={"provider": link.provider, "provider_user_id": link.provider_user_id})
        logger.info("federated_login_success user_id=%s provider=%s", user.id, link.provider)
        return TokenResponse(access_token=create_access_token(user.id, user.hashed_password or ""))  # misma sesión (caducidad y revocación) que el login tradicional

    return router


class _Missing:
    def is_configured(self) -> bool:
        return False
