"""Pruebas del endpoint POST /agent/query (LangGraph agent base).

El grafo real se monta con dependencias simuladas: aquí se comprueba el contrato HTTP (petición, respuesta, errores
claros, nunca un stack trace) y que el router no tiene lógica propia. El grafo se prueba en
`tests/pipelines/test_agent_graph.py` y los evals en `tests/pipelines/test_agent_evals.py`.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes import knowledge as _knowledge  # noqa: F401 - añade la raíz del repo a sys.path
from data.process.rag_config import RagConfigError
from langgraph.checkpoint.memory import InMemorySaver
from services.agent.nodes import AgentDependencies
from services.agent.router import create_router
from services.agent.service import AgentService
from services.agent.tracing import TraceStore

CONTEXT = [{"source_document": "loyalty-program", "section": "Niveles", "chunk_index": 0, "text": "Oro: 50+ puntos."}]


def make_client(tmp_path, retrieve=lambda q: CONTEXT, generate=lambda q, c: "Necesitas 50 puntos.") -> TestClient:
    service = AgentService(AgentDependencies(retrieve, generate), checkpointer=InMemorySaver(),
                           trace_store=TraceStore(tmp_path))
    app = FastAPI()
    app.include_router(create_router(lambda: service))
    return TestClient(app, raise_server_exceptions=False)


def test_answers_through_the_graph_and_returns_a_run_id(tmp_path):
    response = make_client(tmp_path).post("/agent/query", json={"question": "  ¿Cuántos puntos para Oro?  "})
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Necesitas 50 puntos." and body["status"] == "answered"
    assert body["sources"] == ["rag"]  # qué fuentes se consultaron, en orden
    assert (tmp_path / f"{body['run_id']}.json").exists()  # el trace de la corrida quedó guardado


def test_no_information_is_a_normal_answer(tmp_path):
    response = make_client(tmp_path, retrieve=lambda q: []).post("/agent/query", json={"question": "¿Capital de Francia?"})
    assert response.status_code == 200 and response.json()["status"] == "no_information"
    assert "No tengo información" in response.json()["answer"]


@pytest.mark.parametrize("body", [{}, {"question": ""}, {"question": "   "}, {"question": 5}, {"pregunta": "x"}])
def test_rejects_invalid_requests_with_422(tmp_path, body):
    client = make_client(tmp_path, retrieve=lambda q: pytest.fail("no debe recuperar"))
    assert client.post("/agent/query", json=body).status_code == 422


def test_rejects_a_question_that_is_too_long(tmp_path):
    assert make_client(tmp_path).post("/agent/query", json={"question": "a" * 1001}).status_code == 422


def test_node_failure_returns_502_with_a_reference_and_no_internal_details(tmp_path):
    def boom(question, context):
        raise RuntimeError("qdrant://secreto-interno falló")

    response = make_client(tmp_path, generate=boom).post("/agent/query", json={"question": "¿hola?"})
    assert response.status_code == 502
    assert "secreto-interno" not in response.text and "Traceback" not in response.text
    assert "referencia" in response.json()["detail"]


def test_missing_configuration_returns_503(tmp_path):
    def unconfigured(question):
        raise RagConfigError("falta QDRANT_URL")

    response = make_client(tmp_path, retrieve=unconfigured).post("/agent/query", json={"question": "¿hola?"})
    assert response.status_code == 503 and "QDRANT_URL" not in response.text
