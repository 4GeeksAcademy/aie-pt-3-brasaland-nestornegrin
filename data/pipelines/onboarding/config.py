"""Definición del onboarding corporativo de Brasaland: las 8 etapas del BRIEFING (contenido, condición de salida, plazo y aprobador),
la restricción de "solo personal corporativo", las variantes de puesto y la identidad (acotada) del agente.

Todo lo que el BRIEFING fija vive aquí, en datos, y no en `if`s repartidos por el código: el grafo, la API y las pruebas leen esta tabla."""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
KB_DIR = Path(os.environ.get("ONBOARDING_KB_DIR") or REPO_ROOT / "docs" / "onboarding-knowledge-base")
DEFAULT_DB = REPO_ROOT / "data" / "runtime" / "onboarding.sqlite"
DEFAULT_CHECKPOINT_DB = REPO_ROOT / "data" / "runtime" / "onboarding_checkpoints.sqlite"

PASS_THRESHOLD = 0.8          # BRIEFING: umbral de superación del 80 %
QUESTIONS_PER_ATTEMPT = 5     # BRIEFING: entre 4 y 6 preguntas por etapa
FAILED_ATTEMPTS_BEFORE_NOTIFY = 2  # tras dos intentos fallidos se avisa al responsable directo
REMINDER_HOURS_BEFORE = 24    # recordatorio a la persona 24 h antes del plazo de cada etapa
TOTAL_DELAY_DAYS_FOR_PEOPLE_MANAGER = 3  # escalado a Ashley cuando el retraso acumulado supera 3 días
DEADLINE_HOUR_LOCAL = 18      # el plazo de un "Día N" vence a las 18:00 hora local de la sede

SITES = {"Medellín": "America/Bogota", "Miami": "America/New_York"}
CORPORATE_DEPARTMENTS = ("Brasaland Digital", "Marketing", "Compras", "Operaciones", "Personas", "Formación")

NOT_CORPORATE_MESSAGE = ("Este flujo es para incorporaciones al equipo corporativo. "
                         "Las incorporaciones de restaurante se gestionan con su responsable de local.")

# Puestos de sala o cocina: se rechazan aunque el departamento declarado sea corporativo (p. ej. "Operaciones").
RESTAURANT_POSITION = re.compile(
    r"\b(mesero|mesera|cocinero|cocinera|cocina|sala|chef|parrillero|parrillera|bartender|barista|host|hostess|anfitrion|anfitriona|"
    r"cajero|cajera|lavaplatos|runner|jefe de cocina|encargado de local|gerente de local|servidor|servidora|waiter|waitress|cook|dishwasher)\b")
RESTAURANT_DEPARTMENTS = ("cocina", "sala", "restaurante", "local", "kitchen", "front of house")

STATUS_ACTIVE, STATUS_COMPLETED = "active", "completed"
KIND_PAPERWORK, KIND_CONTENT, KIND_SHADOW, KIND_CLOSURE = "paperwork", "content", "shadow_day", "closure"

ROLE_PEOPLE_TEAM = "people_team"        # equipo de Personas
ROLE_PEOPLE_MANAGER = "people_manager"  # Ashley Turner
ROLE_OPS_SUPERVISOR = "ops_supervisor"  # supervisor de Operaciones
ROLE_MANAGER = "manager"                # responsables directos (de cualquier departamento)


@dataclass(frozen=True)
class Stage:
    number: int
    key: str
    title: str
    kind: str
    deadline_day: int                 # "Día N" del BRIEFING, contando el día de inicio como día 1
    exit_condition: str
    approver: str | None = None       # regla de aprobación: ver `can_approve`
    approver_label: str = "Automática"
    quiz: bool = False
    document: str | None = None      # clave del documento oficial (None: la etapa no tiene contenido que presentar)


STAGES: tuple[Stage, ...] = (
    Stage(1, "bienvenida_tramites", "Bienvenida y trámites", KIND_PAPERWORK, 2, "Personas marca la documentación como recibida",
          approver="people_team", approver_label="Equipo de Personas"),
    Stage(2, "la_empresa", "La empresa", KIND_CONTENT, 3, "Comprobación superada", quiz=True, document="etapa-2-la-empresa"),
    Stage(3, "como_opera", "Cómo opera un restaurante", KIND_CONTENT, 5, "Comprobación superada", quiz=True,
          document="etapa-3-como-opera-un-restaurante"),
    Stage(4, "jornada_acompanamiento", "Jornada de acompañamiento", KIND_SHADOW, 7, "Un supervisor de Operaciones confirma la jornada",
          approver="ops_supervisor", approver_label="Supervisor de Operaciones"),
    Stage(5, "tu_funcion", "Tu función", KIND_CONTENT, 8, "Comprobación superada y aprobación del responsable directo",
          approver="direct_manager", approver_label="Responsable directo", quiz=True, document="etapa-5-funcion"),
    Stage(6, "como_trabajamos", "Cómo trabajamos", KIND_CONTENT, 9, "Comprobación superada", quiz=True, document="etapa-6-como-trabajamos"),
    Stage(7, "lineamientos", "Lineamientos", KIND_CONTENT, 9, "Comprobación superada", quiz=True, document="etapa-7-lineamientos"),
    Stage(8, "accesos_cierre", "Accesos y cierre", KIND_CLOSURE, 10, "Ashley aprueba el cierre",
          approver="people_manager", approver_label="Ashley Turner"),
)
STAGE_BY_NUMBER = {stage.number: stage for stage in STAGES}
LAST_STAGE = STAGES[-1].number

# Variantes oficiales de la etapa 5: (departamento, palabras del puesto). Sin variante NO se inventa contenido: se rechaza el alta.
VARIANTS = {
    "analista-brasaland-digital": ("Brasaland Digital", ("analista",)),
    "coordinador-marketing": ("Marketing", ("coordinador", "coordinadora")),
    "analista-compras": ("Compras", ("analista",)),
}


def normalize(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(ch) != "Mn").strip()


def is_corporate(department: str, position: str) -> bool:
    if normalize(department) in {normalize(name) for name in RESTAURANT_DEPARTMENTS}:
        return False
    if normalize(department) not in {normalize(name) for name in CORPORATE_DEPARTMENTS}:
        return False
    return RESTAURANT_POSITION.search(normalize(position)) is None


def variant_for(department: str, position: str) -> str | None:
    for key, (dept, keywords) in VARIANTS.items():
        if normalize(dept) == normalize(department) and any(word in normalize(position) for word in keywords):
            return key
    return None


# ---------------------------------------------------------------------------------------------------- identidad del agente
AGENT_ID = "onboarding-orchestrator"
AGENT_ACTOR = f"agent:{AGENT_ID}"
# Permisos del agente: MÁS acotados que los de cualquier persona del equipo. Puede presentar contenido, consultar el material oficial,
# corregir comprobaciones, avisar y anotar el estado del flujo. NO puede aprobar nada, ni leer o escribir datos personales sensibles,
# ni enviar mensajes libres, ni tocar otras tablas de la aplicación.
AGENT_PERMISSIONS = frozenset({"read_onboarding_state", "present_content", "consult_documents", "grade_comprehension", "notify",
                               "record_stage_status"})
AGENT_FORBIDDEN = frozenset({"approve_stage", "reject_stage", "read_sensitive_data", "write_sensitive_data", "send_free_message",
                             "modify_staff_directory", "read_other_systems"})
