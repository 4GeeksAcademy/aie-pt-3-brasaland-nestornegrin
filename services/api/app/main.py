from __future__ import annotations

import csv
import io
from threading import Lock

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from scripts.analyze import AnalysisResult, analyze_csv_text
from app.database import DATABASE_PATH
from app.suppliers.repository import SupplierRepository
from app.routes.suppliers import create_router

app = FastAPI(title="Brasaland Operations API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3001"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
_latest_result: AnalysisResult | None = None
_result_lock = Lock()
supplier_repository = SupplierRepository(DATABASE_PATH)
app.include_router(create_router(supplier_repository))
app.include_router(create_router(supplier_repository, prefix="/suppliers"))


@app.post("/api/incidents/analyze")
async def analyze_incidents(file: UploadFile = File(...)) -> dict[str, object]:
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
def export_latest_results() -> StreamingResponse:
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