"""Endurecimiento del servidor (infra/hardening): el script se prueba en modo DRY_RUN sobre un sistema de ficheros falso, sin tocar la máquina."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "infra" / "hardening"
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEXAMPLEKEYEXAMPLEKEYEXAMPLEKEYEXAMPLEKEY0 nestor@laptop\n"


def run(tmp_path: Path, *args: str, key: str | None = KEY, env: dict | None = None) -> subprocess.CompletedProcess:
    pubkey = tmp_path / "id.pub"
    if key is not None:
        pubkey.write_text(key)
    cli = list(args) if args else []
    if key is not None and "--pubkey-file" not in cli:
        cli += ["--pubkey-file", str(pubkey)]
    return subprocess.run(["bash", str(SCRIPTS / "harden-server.sh"), *cli], capture_output=True, text=True,
                          env={**os.environ, "DRY_RUN": "1", "ROOT": str(tmp_path / "fs"), **(env or {})})


@pytest.mark.parametrize("script", ["harden-server.sh", "verify-hardening.sh"])
def test_los_scripts_tienen_sintaxis_valida(script):
    assert subprocess.run(["bash", "-n", str(SCRIPTS / script)]).returncode == 0


def test_la_configuracion_sshd_prohibe_root_y_contrasenas(tmp_path):
    result = run(tmp_path)
    assert result.returncode == 0, result.stderr
    config = (tmp_path / "fs/etc/ssh/sshd_config.d/99-brasaland-hardening.conf").read_text()
    for line in ("PermitRootLogin no", "PasswordAuthentication no", "PubkeyAuthentication yes", "X11Forwarding no", "AllowUsers brasaland"):
        assert line in config.splitlines()


def test_el_firewall_deniega_por_defecto_y_abre_solo_ssh_80_443(tmp_path):
    out = run(tmp_path, "--ssh-port", "2222").stdout
    assert "ufw default deny incoming" in out
    opened = [line.split()[3] for line in out.splitlines() if line.startswith("[dry-run] ufw allow ")]
    assert opened == ["2222/tcp", "80/tcp", "443/tcp"]
    assert out.index("ufw allow 2222/tcp") < out.index("ufw --force enable")  # SSH abierto ANTES de activar: no te deja fuera
    for closed in ("5432", "6379", "8001", "3306"):
        assert f"allow {closed}" not in out


def test_permisos_explicitos_separan_codigo_configuracion_logs_y_datos(tmp_path):
    out = run(tmp_path).stdout
    assert "install -d -m 755 -o root -g brasaland" in out and "/opt/brasaland/app" in out
    assert "install -d -m 750 -o root -g brasaland" in out and "/opt/brasaland/config" in out
    assert "install -d -m 750 -o brasaland -g brasaland" in out and "/opt/brasaland/logs" in out
    assert "install -d -m 700 -o brasaland -g brasaland" in out and "/opt/brasaland/data" in out


def test_se_niega_a_ejecutar_sin_clave_publica_para_no_dejarte_sin_acceso(tmp_path):
    no_key = run(tmp_path, key=None)
    assert no_key.returncode != 0 and "clave pública" in no_key.stderr
    not_a_key = run(tmp_path, key="esto no es una clave\n")
    assert not_a_key.returncode != 0


@pytest.mark.parametrize("bad", ["root; rm -rf /", "UPPER", "a b", ""])
def test_rechaza_nombres_de_usuario_peligrosos(tmp_path, bad):
    assert run(tmp_path, "--user", bad).returncode != 0
