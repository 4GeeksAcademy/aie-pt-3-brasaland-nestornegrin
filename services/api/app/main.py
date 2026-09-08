from __future__ import annotations

import csv
import io
import logging
from threading import Lock

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from scripts.analyze import AnalysisResult, analyze_csv_text
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
_latest_result: AnalysisResult | None = None
_result_lock = Lock()
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


@app.post("/api/incidents/analyze")
async def analyze_incidents(
    file: UploadFile = File(...),
    current_user=Depends(get_current_user),
) -> dict[str, object]:
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=415, detail="El fichero debe tener extensión .csv")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="El fichero CSV está vacío")
    try:
        result = analyze_csv_text(content.decode("utf-8-sig"))
    except UnicodeDecodeError as error:
        raise HTTPException(status_code=400, detail="El fichero debe estar codificado en UTF-8") from error
    except (csv.Error, ValueError) as error:
        raise HTTPException(status_code=400, detail=str(error)) from error

    global _latest_result
    with _result_lock:
        _latest_result = result
    return {
        "total_processed": result.total_processed,
        "valid_records": result.valid_records,
        "invalid_records": result.invalid_records,
        "by_category": result.by_category,
        "by_status": result.by_status,
        "average_closed_satisfaction": result.average_closed_satisfaction,
        "invalid_reasons": result.invalid_reasons,
    }


@app.get("/api/incidents/results/export")
def export_latest_results(current_user=Depends(get_current_user)) -> StreamingResponse:
    with _result_lock:
        result = _latest_result
    if result is None:
        raise HTTPException(status_code=404, detail="Todavía no hay ningún análisis disponible")
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(("metric", "dimension", "value"))
    writer.writerows(result.export_rows())
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=results.csv"},
    )
