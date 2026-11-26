from __future__ import annotations

import csv
import io
import logging
import os
import sys
from pathlib import Path
import time

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from redis.exceptions import RedisError

# `data/` (pipelines) y `services/reporting/` viven en la raíz del monorepo, fuera de `services/api`:
# se añade la raíz al path para poder importarlos, arranque la API desde donde arranque.
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.analyze import AnalysisResult
from services.async_tasks import results as task_results
from services.async_tasks import staging
from services.async_tasks.incident_tasks import analyze_incidents_csv
from app.access.catalog import AccessCatalog, InternalReportRepository
from app.access.models import Action
from app.access.permissions import OPS, require_access
from app.access.routes import create_router as create_access_router
from app.auth.dependencies import get_current_user
from app.auth.repository import PasswordResetRepository, ProfileRepository, UserRepository
from app.auth.routes import create_router as create_auth_router
from app.database import (
    ACCESS_DATABASE_PATH,
    DATABASE_PATH,
    AUDIT_LOG_PATH, AUDIT_HEAD_PATH,
    FEDERATED_DATABASE_PATH,
    INTERNAL_REPORTS_DATABASE_PATH,
    INCIDENTS_DATABASE_PATH,
    PASSWORD_RESETS_DATABASE_PATH,
    PROFILES_DATABASE_PATH,
    USERS_DATABASE_PATH,
)
from app.incidents.models import TaskAccepted
from app.incidents.repository import IncidentRepository
from app.incidents.routes import create_router as create_incidents_router
from app.profiles.routes import create_router as create_profiles_router
from app.suppliers.repository import SupplierRepository
from app.tasks.routes import create_router as create_tasks_router
from app.telemetry.routes import create_router as create_telemetry_router
from app.routes.suppliers import create_router
from app.financial_close.routes import create_router as create_financial_close_router
from app.routes.knowledge import create_router as create_knowledge_router
from services.agent.router import create_router as create_agent_router  # tras knowledge: añade la raíz del repo a sys.path
from services.agent.chat.router import create_chat_router
from services.agent.service import get_agent_service
from app.auth.ws import authenticate_ws_token
from app.rfp import models as _rfp_models  # noqa: F401 - registra las tablas antes de create_all
from app.rfp.routes import create_router as create_rfp_router
from app.supplier_contracts.routes import create_router as create_supplier_contracts_router
from app.onboarding.routes import create_router as create_onboarding_router
from app.rfp.schema_sync import ensure_columns as ensure_rfp_columns
from app.federated.repository import FederatedRepository
from app.audit.log import AuditLog
from app.audit.middleware import AuditMiddleware
from app.audit.routes import create_audit_router
from app.federated.routes import create_federated_router
from app.users.routes import create_router as create_users_router
from app.inventory.routes import create_router as create_inventory_router
from services.reporting.router import create_router as create_reporting_router
from app.database import engine
from sqlmodel import SQLModel

from app.security import BodySizeLimitMiddleware, SecurityHeadersMiddleware, allowed_origins, bind_actor, consume_model_budget, docs_enabled, limit_model_calls

app = FastAPI(title="Brasaland Operations API", version="1.0.0",
              docs_url="/docs" if docs_enabled() else None, redoc_url="/redoc" if docs_enabled() else None,
              openapi_url="/openapi.json" if docs_enabled() else None)
logger = logging.getLogger(__name__)
timing_logger = logging.getLogger("api.timing")
if not timing_logger.handlers:
    # uvicorn solo configura sus propios loggers: sin handler propio, las
    # líneas de timing (nivel INFO) no llegarían a la consola.
    _timing_handler = logging.StreamHandler()
    _timing_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    timing_logger.addHandler(_timing_handler)
    timing_logger.setLevel(logging.INFO)
    timing_logger.propagate = False
# A05: lista EXACTA de orígenes (ver app/security.py::allowed_origins); antes un comodín admitía el Codespace de cualquiera.
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Last-Event-ID", "Accept"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(BodySizeLimitMiddleware)  # A04: 413 antes de leer cuerpos enormes (V6)
MAX_CSV_BYTES = 5 * 1024 * 1024
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(cell: str) -> str:
    """A03: neutraliza la inyección de fórmulas (`=HYPERLINK(...)`) en celdas que vienen del CSV subido por un usuario y que otro
    usuario abrirá en Excel/Sheets al descargar `results.csv`. Prefijo `'`, como recomienda OWASP."""
    return "'" + cell if cell.startswith(_FORMULA_PREFIXES) else cell


@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    """Una línea de log por petición con su duración, para decidir con datos
    qué endpoints merecen caché (ver CACHING_REPORT.md). También se devuelve
    en la cabecera X-Process-Time-Ms para medirla desde el cliente."""
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Process-Time-Ms"] = f"{duration_ms:.1f}"
    timing_logger.info("%s %s -> %s | %.1fms", request.method, request.url.path, response.status_code, duration_ms)
    return response

supplier_repository = SupplierRepository(DATABASE_PATH)
access_catalog = AccessCatalog(ACCESS_DATABASE_PATH)  # roles y departamentos: entidades propias, siempre sembradas
user_repository = UserRepository(USERS_DATABASE_PATH, access_catalog)
internal_report_repository = InternalReportRepository(INTERNAL_REPORTS_DATABASE_PATH)
federated_repository = FederatedRepository(FEDERATED_DATABASE_PATH)  # vínculos usuario ↔ proveedor (sin tokens) y `state` de OAuth
audit_log = AuditLog(AUDIT_LOG_PATH, AUDIT_HEAD_PATH)  # audit log append-only con cadena HMAC (app/audit)
app.add_middleware(AuditMiddleware, log=audit_log)  # el más externo: ve el estado final de cada petición (incluidos los 403)
profile_repository = ProfileRepository(PROFILES_DATABASE_PATH)
incident_repository = IncidentRepository(INCIDENTS_DATABASE_PATH)

password_reset_repository = PasswordResetRepository(PASSWORD_RESETS_DATABASE_PATH)

if os.environ.get("SEED_DEMO_DATA", "").lower() in ("1", "true", "yes"):  # usuarios y reportes de DEMO (nunca en producción)
    from app.access.seed import seed_demo

    seed_demo(user_repository, profile_repository, access_catalog, internal_report_repository)
    from app.federated.seed import seed_federated_demo

    seed_federated_demo(user_repository, profile_repository, federated_repository)
app.include_router(create_auth_router())
app.include_router(create_federated_router())  # /auth/federated/*: vincular (con sesión) y login con proveedor (solo cuentas vinculadas)
app.include_router(create_audit_router())  # GET /audit-log, /audit-log/facets, /audit-log/verify (solo lectura)
app.include_router(create_users_router())
app.include_router(create_access_router())  # /roles, /departments (Admin) y /internal-reports (alcance departamental)
app.include_router(create_profiles_router())
app.include_router(create_router(supplier_repository))
app.include_router(create_router(supplier_repository, prefix="/suppliers"))
app.include_router(create_incidents_router(incident_repository))
app.include_router(create_knowledge_router(), dependencies=[Depends(bind_actor), Depends(limit_model_calls)])  # POST /knowledge/query (Hito 7 — RAG); A01: exige sesión
app.include_router(create_agent_router(), dependencies=[Depends(bind_actor), Depends(limit_model_calls)])  # POST /agent/query (agente LangGraph); A01: exige sesión y el actor sale del token
app.include_router(create_tasks_router())  # GET /tasks/{task_id} (cola de tareas asíncronas, DEV-55)
app.include_router(create_telemetry_router())
app.include_router(create_reporting_router())  # pipeline de desempeño de negocio (services/reporting/, separado de telemetry)
app.include_router(create_financial_close_router())  # /financial-close/*: cierre financiero mensual (agente + revisión de Felipe + distribución)

def chat_db_path() -> str:
    """Historial del chat en SQLite (`CHAT_DB_PATH`; `:memory:` en pruebas). Por defecto `data/runtime/chat_sessions.sqlite3` (ignorado por git)."""
    configured = os.environ.get("CHAT_DB_PATH")
    if configured:
        return configured
    path = Path(__file__).resolve().parents[3] / "data" / "runtime" / "chat_sessions.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


# WS /agent/chat/ws (Hito 10 · Parte 2): el mismo agente, en streaming y con interrupción. Mismo JWT que el resto de la API.
app.include_router(create_chat_router(authenticate_ws_token, get_agent_service, store_path=chat_db_path(), allowed_origins=allowed_origins, rate_limit=consume_model_budget))

# Inventory (Supabase/SQLModel) - create schema, then mount routes.
SQLModel.metadata.create_all(engine)
ensure_rfp_columns(engine)  # añade a las tablas rfp_* ya creadas las columnas nuevas (create_all no migra)
app.include_router(create_inventory_router())
app.include_router(create_onboarding_router())  # orquestador de onboarding corporativo (agente LangGraph con checkpointer)
app.include_router(create_rfp_router())  # /rfp/tickets (Hito 9 — recepción de RFPs)
app.include_router(create_supplier_contracts_router())  # /supplier-contracts: supervisor + especialistas de precios y contratos (aprobación humana)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Mismo formato que ya usa el resto de la API (detail: lista de
    # {loc, msg, type}) para que el frontend existente (readApiErrorDetails)
    # siga funcionando sin cambios — solo se corrige el status a 400.
    return JSONResponse(status_code=400, content={"detail": jsonable_encoder(exc.errors())})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Cualquier excepción no controlada (bug, fallo de TinyDB, etc.) responde
    # con un mensaje genérico -- el traceback completo se registra en el log
    # del servidor (visible en la consola de uvicorn) para poder
    # diagnosticarlo, pero nunca viaja en la respuesta al cliente.
    logger.exception("Excepción no controlada en %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Ha ocurrido un error inesperado. Inténtalo de nuevo más tarde."})


@app.post("/api/incidents/analyze", status_code=202, response_model=TaskAccepted, tags=["incidents"])
async def analyze_incidents(
    file: UploadFile = File(...),
    current_user=Depends(require_access(Action.CREATE, OPS)),  # análisis de incidentes de local: datos de Operaciones
) -> TaskAccepted:
    """Encola el análisis del CSV y responde al instante con el `task_id` (202 Accepted).

    El análisis ya no se ejecuta en esta petición: lo hace un worker de Celery (proceso aparte). Aquí solo se
    validan lo barato (extensión, fichero no vacío), se aparca el CSV y se encola su identificador —el mensaje
    nunca lleva el contenido—. El cliente consulta el progreso en `GET /tasks/{task_id}`.
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=415, detail="El fichero debe tener extensión .csv")
    content = await file.read(MAX_CSV_BYTES + 1)  # A04: tope de tamaño (antes se leía el fichero entero en memoria, sin límite)
    if len(content) > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="El CSV supera el máximo de 5 MB")
    if not content:
        raise HTTPException(status_code=400, detail="El fichero CSV está vacío")

    upload_id = await run_in_threadpool(staging.stage_upload, content)
    try:
        # `.delay()` publica en Redis (E/S bloqueante): fuera del bucle de eventos.
        task = await run_in_threadpool(analyze_incidents_csv.delay, upload_id)
    except Exception as error:
        # Sin cola no hay tarea: se limpia el fichero aparcado y se avisa de que reintente.
        await run_in_threadpool(staging.delete_upload, upload_id)
        logger.exception("No se pudo encolar el análisis de incidencias")
        raise HTTPException(status_code=503, detail="La cola de tareas no está disponible. Inténtalo de nuevo en unos segundos.") from error
    logger.info("analyze enqueued task_id=%s upload_id=%s bytes=%d", task.id, upload_id, len(content))
    return TaskAccepted(task_id=task.id)


@app.get(
    "/api/incidents/results/export",
    tags=["incidents"],
    response_class=StreamingResponse,
    response_model=None,
    responses={200: {"content": {"text/csv": {"schema": {"type": "string", "format": "binary"}}}, "description": "CSV con columnas metric,dimension,value"}},
)
def export_latest_results(current_user=Depends(require_access(Action.READ, OPS))) -> StreamingResponse:
    try:
        payload = task_results.load_latest()
    except RedisError as error:
        logger.exception("No se pudo leer el último resultado de Redis")
        raise HTTPException(status_code=503, detail="La cola de tareas no está disponible. Inténtalo de nuevo en unos segundos.") from error
    if payload is None:
        raise HTTPException(status_code=404, detail="Todavía no hay ningún análisis disponible")
    result = AnalysisResult(**payload)
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("metric", "dimension", "value"))
    writer.writerows(tuple(csv_safe(cell) for cell in row) for row in result.export_rows())
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=results.csv"},
    )
