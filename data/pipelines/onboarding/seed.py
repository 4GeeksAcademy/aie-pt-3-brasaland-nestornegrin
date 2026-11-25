"""Datos semilla FICTICIOS (BRIEFING: «Datos semilla»). Se generan conduciendo el agente de verdad (no insertando filas a mano) con un reloj
simulado, así los estados que se ven en el tablero son los que el grafo produciría y quedan en el checkpoint.

Personas: 2 responsables directos de departamentos distintos (+1 de Compras para la variante de ese puesto), 1 supervisor de Operaciones,
el equipo de Personas y Ashley Turner. Incorporaciones: Laura (Medellín, etapa 2), Daniel (Miami, esperando documentación en la etapa 1) y
Mateo (Medellín, BLOQUEADO en la etapa 4 con el plazo vencido). Los 5 documentos oficiales viven en `docs/onboarding-knowledge-base/`."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from . import config, quiz, schedule
from .runner import OnboardingEngine

STAFF = [
    ("s-ashley", "Ashley Turner", "ashley.turner@brasaland-demo.com", "Personas", config.ROLE_PEOPLE_MANAGER, "Miami"),
    ("s-camilo", "Camilo Duarte", "camilo.duarte@brasaland-demo.com", "Personas", config.ROLE_PEOPLE_TEAM, "Medellín"),
    ("s-felipe", "Felipe Guerrero", "felipe.guerrero@brasaland-demo.com", "Operaciones", config.ROLE_OPS_SUPERVISOR, "Medellín"),
    ("s-santiago", "Santiago Ruiz", "santiago.ruiz@brasaland-demo.com", "Brasaland Digital", config.ROLE_MANAGER, "Medellín"),
    ("s-emily", "Emily Carter", "emily.carter@brasaland-demo.com", "Marketing", config.ROLE_MANAGER, "Miami"),
    ("s-lucia", "Lucía Herrera", "lucia.herrera@brasaland-demo.com", "Compras", config.ROLE_MANAGER, "Medellín"),
]
DOCS_OK = {"contract_received": True, "payroll_docs_received": True}


def _answer(engine: OnboardingEngine, onboarding_id: str) -> None:
    pending = engine.awaiting(onboarding_id)
    record = engine.store.onboarding(onboarding_id)
    stage = config.STAGE_BY_NUMBER[pending["stage"]]
    answers = {qid: quiz.question_by_id(stage, record["variant"], qid, engine.kb_dir).answer for qid in pending["question_ids"]}
    engine.apply_answers(onboarding_id, answers)


def seed(engine: OnboardingEngine, today: date | None = None) -> dict[str, str]:
    """Idempotente: si ya existe el directorio de personas, no hace nada. Devuelve {clave: onboarding_id}."""
    store = engine.store
    if store.staff("s-ashley"):
        return {r["email"]: r["id"] for r in store.onboardings()}
    for row in STAFF:
        store.upsert_staff(*row)
    real_clock = engine.clock
    today = today or real_clock().date()
    moment = {"now": real_clock()}
    engine.clock = engine.agent.clock = lambda: moment["now"]
    ids: dict[str, str] = {}
    try:
        def at(day: date, hour: int = 14) -> None:
            moment["now"] = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=hour)

        def create(key: str, **data) -> str:
            at(data["start_date"], 13)
            record = engine.register("s-camilo", data)
            engine.start(record["id"])
            ids[key] = record["id"]
            return record["id"]

        # Laura · Medellín · Analista de Brasaland Digital: documentación recibida, en la etapa 2 (comprobación pendiente)
        start = schedule.first_business_day(today)
        laura = create("laura", name="Laura Gómez", email="laura.gomez@brasaland-demo.com", position="Analista de Brasaland Digital",
                       department="Brasaland Digital", site="Medellín", manager_id="s-santiago", start_date=start)
        engine.apply_decision(laura, "s-camilo", "approve", None, DOCS_OK)

        # Daniel · Miami · Coordinador de Marketing: acaba de llegar, Personas aún no marca la documentación como recibida
        create("daniel", name="Daniel Foster", email="daniel.foster@brasaland-demo.com", position="Coordinador de Marketing",
               department="Marketing", site="Miami", manager_id="s-emily", start_date=start)

        # Mateo · Medellín · Analista de Brasaland Digital: superó 1-3, la jornada de la etapa 4 nunca se confirmó y el plazo venció
        old_start = schedule.first_business_day(today - timedelta(days=21))
        mateo = create("mateo", name="Mateo Restrepo", email="mateo.restrepo@brasaland-demo.com", position="Analista de Brasaland Digital",
                       department="Brasaland Digital", site="Medellín", manager_id="s-santiago", start_date=old_start)
        engine.apply_decision(mateo, "s-camilo", "approve", None, DOCS_OK)
        _answer(engine, mateo)
        _answer(engine, mateo)
    finally:
        engine.clock = engine.agent.clock = real_clock
    return ids
