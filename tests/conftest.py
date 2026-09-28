"""
Fixtures compartilhadas.

`_ambiente_limpo` remove do processo as variáveis de ambiente que mudam o comportamento de
segurança, para que os testes não dependam do shell de quem os executa.
"""
from __future__ import annotations

import pytest

from app.security.passwords import gerar_hash
from tests.helpers import SENHA_ADMIN

_VARS_QUE_INTERFEREM = (
    "ENV", "WEBHOOK_API_KEY", "ADMIN_USERS", "COOKIE_SECURE", "ENABLE_DOCS",
    "SESSION_IDLE_MINUTES", "SESSION_MAX_HOURS", "TOPICS_FILE", "PROMPTS_DIR",
)


@pytest.fixture(autouse=True)
def _ambiente_limpo(monkeypatch):
    for nome in _VARS_QUE_INTERFEREM:
        monkeypatch.delenv(nome, raising=False)


@pytest.fixture(scope="session")
def hash_admin() -> str:
    # argon2 é caro de propósito: gera uma vez por sessão de testes.
    return gerar_hash(SENHA_ADMIN)
