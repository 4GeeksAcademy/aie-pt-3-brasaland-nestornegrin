"""Pruebas del endpoint POST /knowledge/query (Hito 7 — RAG).

`query()` se simula: aquí solo se comprueba el contrato HTTP (petición, respuesta, errores) y que el router llama a
`query()` sin duplicar lógica. El pipeline en sí se prueba en `tests/pipelines/test_rag.py`.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import knowledge as knowledge_routes
from data.process.rag_config import RagConfigError


@pytest.fixture
def knowledge_client() -> TestClient:
    app = FastAPI()
    app.include_router(knowledge_routes.create_router())
    return TestClient(app, raise_server_exceptions=False)


def test_returns_only_the_generated_answer(knowledge_client, monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(knowledge_routes, "query", lambda question: seen.append(question) or "Necesitas 50 puntos.")
    response = knowledge_client.post("/knowledge/query", json={"question": "  ¿Cuántos puntos para Oro?  "})
    assert response.status_code == 200
    assert response.json() == {"answer": "Necesitas 50 puntos."}  # solo "answer": sin chunks ni puntuaciones
    assert seen == ["¿Cuántos puntos para Oro?"]  # llega recortada, sin lógica extra en el router


@pytest.mark.parametrize("body", [{}, {"question": ""}, {"question": "   "}, {"question": 5}, {"pregunta": "x"}])
def test_rejects_invalid_requests_without_calling_query(knowledge_client, monkeypatch, body):
    monkeypatch.setattr(knowledge_routes, "query", lambda question: pytest.fail("query() no debe llamarse"))
    assert knowledge_client.post("/knowledge/query", json=body).status_code == 422


def test_rejects_a_question_that_is_too_long(knowledge_client, monkeypatch):
    monkeypatch.setattr(knowledge_routes, "query", lambda question: pytest.fail("query() no debe llamarse"))
    assert knowledge_client.post("/knowledge/query", json={"question": "a" * 1001}).status_code == 422


def test_upstream_failure_returns_502_without_leaking_details(knowledge_client, monkeypatch):
    def boom(question):
        raise RuntimeError("qdrant://secreto-interno falló")

    monkeypatch.setattr(knowledge_routes, "query", boom)
    response = knowledge_client.post("/knowledge/query", json={"question": "¿hola?"})
    assert response.status_code == 502
    assert "secreto-interno" not in response.text
    assert set(response.json()) == {"detail"}


def test_missing_configuration_returns_503(knowledge_client, monkeypatch):
    def not_configured(question):
        raise RagConfigError("Falta la variable de entorno QDRANT_URL")

    monkeypatch.setattr(knowledge_routes, "query", not_configured)
    response = knowledge_client.post("/knowledge/query", json={"question": "¿hola?"})
    assert response.status_code == 503
    assert "QDRANT_URL" not in response.text
