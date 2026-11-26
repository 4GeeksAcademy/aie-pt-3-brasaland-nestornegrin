"""Configuración del cierre financiero. TODO sale del BRIEFING (Cierre Financiero Mensual): cifras de presupuesto/real, umbral, tipo de cambio,
revisor, destinatarios y programación. Si el briefing cambia, cambia AQUÍ y en ningún otro sitio."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DB = REPO_ROOT / "data" / "runtime" / "financial_data.sqlite"      # datos financieros (el agente solo los LEE)
DEFAULT_CLOSE_DB = REPO_ROOT / "data" / "runtime" / "financial_close.sqlite"    # informes, revisiones, eventos, mensajes
DEFAULT_FILES_DIR = REPO_ROOT / "data" / "runtime" / "financial_close"

FX_COP_PER_USD = Decimal("4000")            # tipo de cambio de consolidación (dato de referencia del briefing)
THRESHOLD_PCT = Decimal("5")                # desviación relevante: |desviación| >= 5 % (a favor o en contra)
LANGUAGE = "es"                             # idioma base del informe (las cifras no dependen del idioma)
SCHEDULE_TZ = "America/Bogota"              # hora de Medellín (UTC-5, sin horario de verano)
SCHEDULE_BUSINESS_DAY, SCHEDULE_HOUR = 3, 6  # tercer día hábil de cada mes, 06:00
HOLIDAYS: frozenset[str] = frozenset()      # festivos colombianos (ISO). Vacío por defecto: se declara en la documentación; añadir aquí si se requiere

COUNTRIES = {"CO": ("Colombia", "COP"), "FL": ("Florida", "USD")}
INCOME = "Ingresos por ventas"
CATEGORIES = ("Ingresos por ventas", "Carne de res", "Pollo", "Verduras", "Bebidas", "Nómina", "Alquileres", "Marketing", "Servicios")
PURCHASE_CATEGORIES = ("Carne de res", "Pollo", "Verduras", "Bebidas")
CATEGORY_KEY = {"Ingresos por ventas": "REV", "Carne de res": "BEEF", "Pollo": "CHICKEN", "Verduras": "VEG", "Bebidas": "DRINKS",
                "Nómina": "PAYROLL", "Alquileres": "RENT", "Marketing": "MKT", "Servicios": "UTIL"}


@dataclass(frozen=True)
class Line:
    """Una partida del briefing: presupuesto, real y (si es compra) proveedor, precio unitario y cantidad presupuestados."""
    country: str
    category: str
    label: str
    budget: Decimal
    actual: Decimal | None            # None = sin registros (dato faltante)
    supplier: str | None = None
    unit: str | None = None
    unit_price: Decimal | None = None  # precio unitario presupuestado
    quantity: Decimal | None = None    # cantidad presupuestada
    actual_unit_price: Decimal | None = None
    actual_quantity: Decimal | None = None
    deliveries: int = 4                # nº de registros en el libro


D = Decimal
LINES = (
    # ---- Colombia (COP)
    Line("CO", "Ingresos por ventas", "Ingresos por ventas", D("1120000000"), D("1090000000"), deliveries=4),
    Line("CO", "Carne de res", "Carne de res (Carnes del Valle)", D("106400000"), D("110656000"), "Carnes del Valle", "kg", D("38000"), D("2800"), D("39520"), D("2800"), 4),
    Line("CO", "Pollo", "Pollo (Avícola Antioquia)", D("48875000"), D("53273750"), "Avícola Antioquia", "kg", D("11500"), D("4250"), D("12535"), D("4250"), 5),
    Line("CO", "Verduras", "Verduras (Hortalizas La Sabana)", D("25200000"), D("25200000"), "Hortalizas La Sabana", "kg", D("4200"), D("6000"), D("4200"), D("6000"), 4),
    Line("CO", "Nómina", "Nómina", D("320000000"), D("322000000"), deliveries=2),
    Line("CO", "Alquileres", "Alquileres", D("95000000"), D("95000000"), deliveries=3),
    Line("CO", "Marketing", "Marketing", D("30000000"), D("30500000"), deliveries=3),
    Line("CO", "Servicios", "Servicios (energía, agua, gas)", D("22000000"), D("21800000"), deliveries=3),
    # ---- Florida (USD)
    Line("FL", "Ingresos por ventas", "Ingresos por ventas", D("230000"), D("205000"), deliveries=4),
    Line("FL", "Carne de res", "Carne de res (Sunshine Prime Meats)", D("17280"), D("19353.6"), "Sunshine Prime Meats", "lb", D("7.20"), D("2400"), D("8.064"), D("2400"), 4),
    Line("FL", "Pollo", "Pollo (Gulf Poultry Co.)", D("6300"), D("6300"), "Gulf Poultry Co.", "lb", D("2.10"), D("3000"), D("2.10"), D("3000"), 4),
    Line("FL", "Bebidas", "Bebidas (Brava Beverages FL)", D("7200"), D("7632"), "Brava Beverages FL", "caja", D("24.00"), D("300"), D("25.44"), D("300"), 4),
    Line("FL", "Nómina", "Nómina", D("78000"), D("77500"), deliveries=2),
    Line("FL", "Alquileres", "Alquileres", D("42000"), D("42000"), deliveries=3),
    Line("FL", "Marketing", "Marketing", D("9000"), D("15500"), deliveries=3),
    Line("FL", "Servicios", "Servicios (energía, agua, gas)", D("6500"), None, deliveries=0),     # SIN REGISTROS (dato faltante)
)
# Indicadores operativos (presupuesto, real) por país
OPERATIONS = {
    ("CO", "covers_served"): (D("28000"), D("27250")), ("CO", "avg_ticket"): (D("40000"), D("40000")),
    ("FL", "covers_served"): (D("9200"), D("8200")), ("FL", "avg_ticket"): (D("25.00"), D("25.00")),
}

# ---- Revisión y distribución (BRIEFING)
ROLE_REVIEWER, ROLE_CEO, ROLE_CTO = "ops_director", "ceo", "cto"
STAFF = (   # directorio de PRUEBA: en producción vendría de Personas
    ("s-mariana", "Mariana Restrepo", "mariana.restrepo@brasaland-demo.com", ROLE_CEO),
    ("s-felipe", "Felipe Guerrero", "felipe.guerrero@brasaland-demo.com", ROLE_REVIEWER),
    ("s-nicolas", "Nicolás Park", "nicolas.park@brasaland-demo.com", ROLE_CTO),
    ("s-lucia", "Lucía Fernández", "lucia.fernandez@brasaland-demo.com", "procurement_lead"),
    ("s-camila", "Camila Ospina", "camila.ospina@brasaland-demo.com", "marketing_lead"),
    ("s-ashley", "Ashley Turner", "ashley.turner@brasaland-demo.com", "people_lead"),
    ("s-jake", "Jake Morrison", "jake.morrison@brasaland-demo.com", "training_lead"),
)
REVIEWER_ID = "s-felipe"
RECIPIENT_IDS = tuple(s[0] for s in STAFF)          # Mariana, Felipe, Nicolás, Lucía, Camila, Ashley y Jake (todos)
AUDIT_ROLES = (ROLE_REVIEWER, ROLE_CEO, ROLE_CTO)   # quién consulta la auditoría
OPERATOR_ROLES = (ROLE_REVIEWER, ROLE_CTO)          # quién puede lanzar un cierre manual

# ---- Agente: identidad propia y acceso de SOLO LECTURA a los datos financieros
AGENT_ID = "agent:financial-close"
AGENT_TOOLS = frozenset({"read_ledger", "read_budget", "read_operations", "sum_amounts", "variance", "convert_currency", "consolidate",
                         "parse_purchase", "price_volume_effect", "compose_report"})
FORBIDDEN_FOR_AGENT = frozenset({"write_ledger", "write_budget", "approve_report", "distribute_report", "read_sensitive_data"})


def norm(text: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn").strip()
