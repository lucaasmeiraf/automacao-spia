"""
Testes da leitura das configurações de segurança do .env (Settings).

Inclui o caso real de colar o hash argon2 no .env: ele contém '$', e precisa chegar íntegro
com as aspas simples que o script `gerar_hash_senha` imprime.
"""
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.security.passwords import verificar
from tests.helpers import SENHA_ADMIN

BASE = dict(openai_api_key="x", dnit_token="y")


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, **{**BASE, **kw})


def test_padroes_sao_restritivos():
    s = _settings()
    assert s.env == "prod"
    assert s.webhook_api_key is None
    assert s.admin_users == {}
    assert s.cookie_secure is True
    assert s.enable_docs is False


@pytest.mark.parametrize("valor", ["", "   "])
def test_webhook_key_em_branco_vira_nao_configurada(valor):
    assert _settings(webhook_api_key=valor).webhook_api_key is None


def test_webhook_key_curta_e_rejeitada_sem_vazar_o_valor():
    with pytest.raises(ValidationError) as exc:
        _settings(webhook_api_key="senha123-curta")
    texto = str(exc.value)
    assert "32 caracteres" in texto
    assert "senha123-curta" not in texto


def test_webhook_key_forte_e_aceita_e_aparada():
    assert _settings(webhook_api_key="  " + "a" * 32 + "  ").webhook_api_key == "a" * 32


def test_admin_com_senha_em_texto_puro_e_rejeitado_sem_vazar_a_senha():
    with pytest.raises(ValidationError) as exc:
        _settings(admin_users={"lucas": "MinhaSenhaEmTextoPuro!"})
    texto = str(exc.value)
    assert "hash argon2" in texto
    assert "MinhaSenhaEmTextoPuro" not in texto


def test_admin_com_nome_vazio_e_rejeitado(hash_admin):
    with pytest.raises(ValidationError):
        _settings(admin_users={"  ": hash_admin})


def test_admin_users_vem_do_ambiente_como_json(monkeypatch, hash_admin):
    monkeypatch.setenv("ADMIN_USERS", json.dumps({"lucas": hash_admin}))
    monkeypatch.setenv("ENV", "dev")
    s = Settings(_env_file=None, **BASE)
    assert s.env == "dev" and list(s.admin_users) == ["lucas"]


def test_env_invalido_e_rejeitado(monkeypatch):
    monkeypatch.setenv("ENV", "producao")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **BASE)


def test_linha_do_env_gerada_pelo_script_com_aspas_simples_chega_integra(tmp_path, hash_admin):
    """Reproduz exatamente o que scripts/gerar_hash_senha.py imprime e o que o usuário cola no .env."""
    linha = f"ADMIN_USERS='{json.dumps({'lucas.meira': hash_admin})}'"
    arquivo = tmp_path / ".env"
    arquivo.write_text(
        "ENV=dev\n"
        "OPENAI_API_KEY=sk-x\n"
        "DNIT_TOKEN=y\n"
        f"WEBHOOK_API_KEY={'z' * 40}\n"
        f"{linha}\n"
        "HTTP_TIMEOUT=120        # comentário na mesma linha\n",
        encoding="utf-8",
    )
    s = Settings(_env_file=str(arquivo))
    assert s.env == "dev"
    assert s.http_timeout == 120
    assert verificar(s.admin_users["lucas.meira"], SENHA_ADMIN) is True


def test_env_example_versionado_carrega_sem_erro(tmp_path):
    """O .env.example (com placeholders) precisa ser um .env sintaticamente válido."""
    from pathlib import Path

    exemplo = Path(__file__).resolve().parent.parent / ".env.example"
    s = Settings(_env_file=str(exemplo))
    assert s.env == "dev"
    assert s.webhook_api_key is None          # em branco => webhook desligado até configurar
    assert s.admin_users == {}                # '{}' => ninguém loga até rodar o script
    assert s.cookie_secure is True
