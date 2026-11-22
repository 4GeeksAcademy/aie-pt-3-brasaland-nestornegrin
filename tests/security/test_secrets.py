"""Manejo de secretos (NIST Protect · OWASP A02): ningún `.env` real se versiona y el repo no contiene credenciales."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEY_PATTERNS = re.compile(r"sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|SG\.[A-Za-z0-9_-]{20,}|re_[A-Za-z0-9]{20,}|-----BEGIN [A-Z ]*PRIVATE KEY")


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)


def test_los_env_reales_estan_ignorados_y_las_plantillas_no():
    for path in (".env", "services/api/.env", "mcps/brasaland_mcp/.env", "uis/backoffice/.env.local"):
        assert git("check-ignore", "-q", path).returncode == 0, f"{path} debería estar en .gitignore"
    for template in ("services/api/.env.example", "mcps/brasaland_mcp/.env.example"):
        assert git("check-ignore", "-q", template).returncode != 0, f"{template} debe poder versionarse"


def test_ningun_env_real_esta_versionado():
    tracked = git("ls-files").stdout.splitlines()
    assert [f for f in tracked if re.search(r"(^|/)\.env($|\.(?!example))", f)] == []


def test_no_hay_credenciales_en_el_codigo_versionado():
    hits = []
    for name in git("ls-files").stdout.splitlines():
        if name.endswith((".lock", "lock.json", ".png", ".jpg", ".pdf", ".csv")) or name.startswith("docs/security/"):
            continue
        try:
            text = (ROOT / name).read_text(errors="ignore")
        except OSError:
            continue
        if KEY_PATTERNS.search(text):
            hits.append(name)
    assert hits == [], f"posibles credenciales en: {hits}"
