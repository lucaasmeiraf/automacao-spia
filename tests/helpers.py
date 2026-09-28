"""
Auxiliares de teste: Settings hermético e app sem lifespan (clientes HTTP são mocks).
"""
from __future__ import annotations

from unittest.mock import MagicMock

from app.config import Settings
from app.main import create_app

CHAVE_WEBHOOK = "k" * 40
SENHA_ADMIN = "senha-de-teste-bem-longa"


def fazer_settings(**kw) -> Settings:
    """Settings que ignora o .env do desenvolvedor (`_env_file=None`)."""
    base = dict(openai_api_key="x", dnit_token="y", webhook_api_key=CHAVE_WEBHOOK)
    base.update(kw)
    return Settings(_env_file=None, **base)


def fazer_app(settings: Settings):
    """create_app sem executar o lifespan: clientes HTTP são mocks."""
    app = create_app(settings)
    for nome in ("dnit", "openai", "openmeteo", "nominatim"):
        setattr(app.state, nome, MagicMock())
    return app
