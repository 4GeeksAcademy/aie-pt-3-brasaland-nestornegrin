from __future__ import annotations

import csv
import io
import logging

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from redis.exceptions import RedisError

from scripts.analyze import AnalysisResult
from services.async_tasks import results as task_results
from services.async_tasks import staging
from services.async_tasks.incident_tasks import analyze_incidents_csv
from app.auth.dependencies import get_current_user
from app.auth.repository import PasswordResetRepository, ProfileRepository, UserRepository
from app.auth.routes import create_router as create_auth_router
from app.database import (
    DATABASE_PATH,
    INCIDENTS_DATABASE_PATH,
    PASSWORD_RESETS_DATABASE_PATH,
    PROFILES_DATABASE_PATH,
    USERS_DATABASE_PATH,
)
from app.incidents.repository import IncidentRepository
from app.incidents.routes import create_router as create_incidents_router
from app.profiles.routes import create_router as create_profiles_router
from app.suppliers.repository import SupplierRepository
from app.tasks.routes import create_router as create_tasks_router
from app.routes.suppliers import create_router
from app.users.routes import create_router as create_users_router
from app.inventory.routes import create_router as create_inventory_router
from app.database import engine
from sqlmodel import SQLModel

app = FastAPI(title="Brasaland Operations API", version="1.0.0")
logger = logging.getLogger(__name__)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_origin_regex=r"https://.*\.app\.github\.dev",
        allow_methods=["*"],
    allow_headers=["*"],
)
supplier_repository = SupplierRepository(DATABASE_PATH)
user_repository = UserRepository(USERS_DATABASE_PATH)
profile_repository = ProfileRepository(PROFILES_DATABASE_PATH)
incident_repository = IncidentRepository(INCIDENTS_DATABASE_PATH)
password_reset_repository = PasswordResetRepository(PASSWORD_RESETS_DATABASE_PATH)
app.include_router(create_auth_router())
app.include_router(create_users_router())
app.include_router(create_profiles_router())
app.include_router(create_router(supplier_repository))
app.include_router(create_router(supplier_repository, prefix="/suppliers"))
app.include_router(create_incidents_router(incident_repository))
app.include_router(create_tasks_router())  # GET /tasks/{task_id} (cola de tareas asíncronas, DEV-55)

# Inventory (Supabase/SQLModel) - create schema, then mount routes.
SQLModel.metadata.create_all(engine)
app.include_router(create_inventory_router())


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


@app.post("/api/incidents/analyze", status_code=202)
async def analyze_incidents(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
) -> dict[str, str]:
    """Encola el análisis del CSV y responde al instante con el `task_id` (202 Accepted).

    El análisis ya no se ejecuta en esta petición: lo hace un worker de Celery (proceso aparte). Aquí solo se
    validan lo barato (extensión, fichero no vacío), se aparca el CSV y se encola su identificador —el mensaje
    nunca lleva el contenido—. El cliente consulta el progreso en `GET /tasks/{task_id}`.
    """
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=415, detail="El fichero debe tener extensión .csv")
    content = await file.read()
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
    return {"task_id": task.id}


@app.get("/api/incidents/results/export")
def export_latest_results(current_user=Depends(get_current_user)) -> StreamingResponse:
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
    writer.writerows(result.export_rows())
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=results.csv"},
    )
