"""Configuración del flujo de proveedores y contratos. TODO sale del BRIEFING (Gestión de Proveedores y Contratos): proveedores, contratos,
umbrales, plazos de alerta, aprobadores y datos de referencia. Si el briefing cambia, cambia AQUÍ y en ningún otro sitio."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = REPO_ROOT / "data" / "runtime" / "supplier_contracts.sqlite"
DEFAULT_DATA_DIR = REPO_ROOT / "data" / "runtime" / "supplier_contracts"

# Datos de referencia para los cálculos (BRIEFING)
COLOMBIA_CPI = Decimal("5.2")            # IPC anual de Colombia, %
FX_COP_PER_USD = Decimal("4000")         # 1 USD = 4.000 COP

# Umbrales y alertas (BRIEFING)
BEEF = "Carne de res"
PRICE_THRESHOLD_BEEF_PCT = Decimal("3")     # carne de res: > 3 % frente al mes anterior
PRICE_THRESHOLD_OTHER_PCT = Decimal("8")    # resto de categorías: > 8 %
EXPIRY_ALERT_DAYS = (90, 30)                # vencimiento de contrato: 90 y 30 días antes
NOTICE_ALERT_DAYS = 15                      # fecha límite de preaviso: 15 días antes
BIG_CONTRACT_USD = Decimal("200000")        # > USD 200.000 (o equivalente en COP) → también Mariana
MAX_CONSULTS_PER_REQUEST = 4                # tope de consultas del supervisor por petición (evita bucles)

LANGUAGE = "es"                             # idioma base de respuestas, briefs y alertas (las citas van en el idioma del contrato)


@dataclass(frozen=True)
class Supplier:
    id: str
    name: str
    country: str
    category: str
    currency: str


SUPPLIERS = (
    Supplier("BR-S01", "Carnes del Valle S.A.S.", "Colombia", BEEF, "COP"),
    Supplier("BR-S02", "Avícola Antioquia", "Colombia", "Pollo", "COP"),
    Supplier("BR-S03", "Hortalizas La Sabana", "Colombia", "Verduras", "COP"),
    Supplier("BR-S04", "Frigorífico Andino", "Colombia", BEEF, "COP"),
    Supplier("BR-S05", "Sunshine Prime Meats", "Estados Unidos", BEEF, "USD"),
    Supplier("BR-S06", "Gulf Coast Beef Co.", "Estados Unidos", BEEF, "USD"),
    Supplier("BR-S07", "Gulf Poultry Co.", "Estados Unidos", "Pollo", "USD"),
    Supplier("BR-S08", "Brava Beverages FL", "Estados Unidos", "Bebidas", "USD"),
)
SUPPLIER_BY_ID = {s.id: s for s in SUPPLIERS}


@dataclass(frozen=True)
class ContractSpec:
    """Lo que el BRIEFING dice de cada contrato; sirve para GENERAR los PDFs de prueba (la extracción NO lo lee: parte del PDF)."""
    id: str
    supplier_id: str
    language: str
    expires_in_days: int            # relativo a la fecha de carga
    annual_value: Decimal
    currency: str


CONTRACTS = (
    ContractSpec("CT-BR-01", "BR-S01", "es", 120, Decimal("1276800000"), "COP"),
    ContractSpec("CT-BR-02", "BR-S05", "en", 75, Decimal("207360"), "USD"),
    ContractSpec("CT-BR-03", "BR-S02", "es", 200, Decimal("586500000"), "COP"),
    ContractSpec("CT-BR-04", "BR-S08", "en", 20, Decimal("86400"), "USD"),
)
CONTRACT_BY_SUPPLIER = {c.supplier_id: c for c in CONTRACTS}

# Histórico de precios (BRIEFING): proveedor → producto, unidad, precio base, volumen mensual (0 = solo cotización)
PRICE_BASES = (
    ("BR-S01", "Punta de anca", "kg", Decimal("38000"), 2800),
    ("BR-S04", "Punta de anca", "kg", Decimal("36500"), 0),
    ("BR-S05", "Picanha", "lb", Decimal("7.20"), 2400),
    ("BR-S06", "Picanha", "lb", Decimal("7.05"), 0),
    ("BR-S02", "Pollo entero", "kg", Decimal("11500"), 4250),
    ("BR-S07", "Whole chicken", "lb", Decimal("2.10"), 3000),
    ("BR-S03", "Surtido de verduras", "kg", Decimal("4200"), 6000),
    ("BR-S08", "Bebidas (caja)", "caja", Decimal("24.00"), 300),
)
# Escenarios del último mes (BRIEFING): variación % sobre el precio base
SCENARIOS = {"BR-S05": Decimal("12"), "BR-S01": Decimal("4"), "BR-S02": Decimal("9"), "BR-S08": Decimal("6")}
HISTORY_MONTHS = 12

# Personas y aprobaciones (BRIEFING). El directorio es de PRUEBA (correos ficticios).
ROLE_OPS_DIRECTOR = "ops_director"      # Felipe Guerrero, Director de Operaciones
ROLE_CEO = "ceo"                        # Mariana Restrepo
ROLE_PROCUREMENT = "procurement_lead"   # Lucía Fernández, Compras
STAFF = (
    ("s-felipe", "Felipe Guerrero", "felipe.guerrero@brasaland-demo.com", ROLE_OPS_DIRECTOR),
    ("s-mariana", "Mariana Restrepo", "mariana.restrepo@brasaland-demo.com", ROLE_CEO),
    ("s-lucia", "Lucía Fernández", "lucia.fernandez@brasaland-demo.com", ROLE_PROCUREMENT),
)
ALERT_RECIPIENTS = ("s-lucia", "s-felipe")      # las alertas van a Lucía (Compras) y a Felipe


def required_approvers(annual_value_usd: Decimal | None) -> tuple[str, ...]:
    """Cualquier comunicación a un proveedor: Felipe. Si el contrato vale más de USD 200.000: Felipe Y Mariana. (Sin contrato: solo Felipe.)"""
    if annual_value_usd is not None and annual_value_usd > BIG_CONTRACT_USD:
        return (ROLE_OPS_DIRECTOR, ROLE_CEO)
    return (ROLE_OPS_DIRECTOR,)


# Identidades de los agentes: cada uno con SU identidad y solo las herramientas de su especialidad.
SUPERVISOR_ID, PRICE_AGENT_ID, CONTRACT_AGENT_ID = "agent:supplier-supervisor", "agent:price-specialist", "agent:contract-specialist"
AGENT_PERMISSIONS = {
    SUPERVISOR_ID: frozenset({"consult_price_specialist", "consult_contract_specialist", "compose_answer", "draft_communication"}),
    PRICE_AGENT_ID: frozenset({"read_prices", "detect_increase", "compute_impact", "compare_peers", "convert_currency"}),
    CONTRACT_AGENT_ID: frozenset({"read_contract_terms", "check_price_increase", "compute_deadlines", "convert_currency"}),
}
# Lo que NINGÚN agente puede hacer (no existe como herramienta): enviar a proveedores, aprobar, leer datos sensibles, tocar el directorio.
FORBIDDEN_FOR_AGENTS = frozenset({"send_to_supplier", "approve_communication", "read_sensitive_data", "modify_staff", "modify_contracts"})


def normalize(text: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn").strip()
