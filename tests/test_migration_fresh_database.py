"""Regressao do BRK-1: `alembic upgrade head` deixava o sistema sem login.

A revision inicial cria 10 das 12 tabelas de models.py. Faltavam `sessions` e
`audit_events` — as duas que a autenticacao escreve. O upgrade terminava com
exito e o primeiro login respondia 500. Producao so nao quebrou porque o schema
de la nasceu por `create_all` antes de a migration existir; qualquer VPS nova ou
restore de backup caia.

Este teste roda a migration DE VERDADE contra um banco vazio — a suite existente
monta o schema com `Base.metadata.create_all`, que e exatamente o caminho que
mascarava o defeito.
"""
import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Toda tabela declarada em models.py precisa existir depois do upgrade.
TABELAS_ESPERADAS = {
    "organizations", "users", "memberships", "projects", "project_versions",
    "file_assets", "processing_jobs", "lots", "share_links", "edit_proposals",
    "sessions", "audit_events",
}


def _run_alembic(database_url, tmp_path):
    env = dict(os.environ, DATABASE_URL=database_url, PYTHONPATH=ROOT)
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=180,
    )


@pytest.fixture()
def banco_limpo(tmp_path):
    return "sqlite:///%s" % (tmp_path / "fresh.db")


def test_upgrade_head_cria_todas_as_tabelas_de_models(banco_limpo, tmp_path):
    resultado = _run_alembic(banco_limpo, tmp_path)
    assert resultado.returncode == 0, (
        "alembic upgrade head falhou:\n%s\n%s" % (resultado.stdout, resultado.stderr))

    tabelas = set(inspect(create_engine(banco_limpo)).get_table_names())
    faltando = TABELAS_ESPERADAS - tabelas
    assert not faltando, "tabelas ausentes depois do upgrade: %s" % sorted(faltando)


def test_login_funciona_em_banco_criado_so_pela_migration(banco_limpo, tmp_path):
    """O teste que o `create_all` da suite escondia: setup + login ponta a ponta."""
    resultado = _run_alembic(banco_limpo, tmp_path)
    assert resultado.returncode == 0, resultado.stderr

    os.environ["DATABASE_URL"] = banco_limpo
    os.environ["SETUP_TOKEN"] = "token-de-teste-com-mais-de-16-chars"
    os.environ["SESSION_COOKIE_SECURE"] = "false"
    for module in [name for name in list(sys.modules)
                   if name in {"api", "auth", "database", "models"}
                   or name.startswith("app_v1")]:
        sys.modules.pop(module, None)

    from fastapi.testclient import TestClient
    import api

    with TestClient(api.app) as client:
        setup = client.post("/api/auth/setup", json={
            "token": "token-de-teste-com-mais-de-16-chars",
            "email": "dono@exemplo.com",
            "password": "senha-longa-de-teste",
            "name": "Dono",
        })
        assert setup.status_code < 400, setup.text

        login = client.post("/api/auth/login", json={
            "email": "dono@exemplo.com",
            "password": "senha-longa-de-teste",
        })
        assert login.status_code == 200, login.text
        assert api.COOKIE_NAME in login.cookies
