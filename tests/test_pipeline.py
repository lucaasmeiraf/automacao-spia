"""
Testes do pipeline genérico e dos helpers de registro.

Cobre: estratégia "campo", estratégia "json" (com filtro de campos,
empty_as_array, status=false) e roteamento para handlers especializados.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.processing.pipeline import _como_lista, _montar_user_content, processar_topico
from app.processing.records import detectar_vazio, limpar_registro
from app.topics import TopicConfig


# ---------------------------------------------------------------------------
# _como_lista
# ---------------------------------------------------------------------------

def test_como_lista_lista_direta():
    assert _como_lista([{"a": 1}]) == [{"a": 1}]


def test_como_lista_objeto_com_resultado_lista():
    bruto = {"resultado": [{"x": 1}, {"x": 2}]}
    assert _como_lista(bruto) == [{"x": 1}, {"x": 2}]


def test_como_lista_objeto_com_resultado_simples():
    bruto = {"resultado": {"x": 1}}
    assert _como_lista(bruto) == [{"x": 1}]


# ---------------------------------------------------------------------------
# limpar_registro
# ---------------------------------------------------------------------------

def test_limpar_registro_filtra_campos():
    reg = {"a": 1, "b": 2, "c": 3}
    resultado = limpar_registro(reg, campos_manter=("a", "c"))
    assert "b" not in resultado
    assert resultado["a"] == 1 and resultado["c"] == 3


def test_limpar_registro_remove_html():
    reg = {"descricao": "<p>Texto <b>em negrito</b></p>", "outro": "ok"}
    resultado = limpar_registro(reg, html_fields=("descricao",))
    assert "<p>" not in resultado["descricao"]
    assert "Texto" in resultado["descricao"]


def test_limpar_registro_remove_crlf():
    reg = {"campo": "linha1\r\nlinha2\nlinha3"}
    resultado = limpar_registro(reg)
    assert "\r\n" not in resultado["campo"]
    assert "\n" not in resultado["campo"]


# ---------------------------------------------------------------------------
# detectar_vazio
# ---------------------------------------------------------------------------

def test_detectar_vazio_lista_vazia():
    assert detectar_vazio([]) is True


def test_detectar_vazio_status_false():
    assert detectar_vazio([{"status": False, "mensagem": "sem dados"}]) is True


def test_detectar_vazio_campos_presenca_todos_nulos():
    registros = [{"numero_termo": None, "numero": None, "num_termo": None}]
    assert detectar_vazio(registros, campos_presenca=("numero_termo", "numero", "num_termo")) is True


def test_detectar_vazio_campos_presenca_com_dado():
    registros = [{"numero_termo": "001/2024", "numero": None}]
    assert detectar_vazio(registros, campos_presenca=("numero_termo", "numero")) is False


def test_detectar_vazio_sem_campos_presenca_registros_validos():
    registros = [{"a": 1}]
    assert detectar_vazio(registros) is False


# ---------------------------------------------------------------------------
# _montar_user_content — estratégia "campo"
# ---------------------------------------------------------------------------

def test_montar_user_content_campo_usa_campo_indicado():
    cfg = TopicConfig(
        chave="justificativa", endpoint="justificativa",
        estrategia="campo", campo_conteudo="resumo",
    )
    registros = [{"resumo": "Texto do resumo", "descricao": "outra coisa"}]
    resultado = _montar_user_content(cfg, registros)
    assert resultado == "Texto do resumo"


def test_montar_user_content_campo_vazio_quando_sem_registros():
    cfg = TopicConfig(
        chave="justificativa", endpoint="justificativa",
        estrategia="campo", campo_conteudo="resumo",
    )
    assert _montar_user_content(cfg, []) == ""


# ---------------------------------------------------------------------------
# _montar_user_content — estratégia "json"
# ---------------------------------------------------------------------------

def test_montar_user_content_json_serializa_registros():
    cfg = TopicConfig(chave="oaes", endpoint="oaes", estrategia="json")
    registros = [{"nome": "OAE-01", "tipo": "Ponte"}]
    resultado = json.loads(_montar_user_content(cfg, registros))
    assert resultado[0]["nome"] == "OAE-01"


def test_montar_user_content_json_empty_as_array_sem_dados():
    cfg = TopicConfig(
        chave="aditivos", endpoint="aditivos",
        estrategia="json",
        empty_as_array=True,
        campos_presenca=("numero_termo",),
    )
    registros = [{"numero_termo": None}]
    assert _montar_user_content(cfg, registros) == "[]"


def test_montar_user_content_json_status_false_empty_as_array():
    cfg = TopicConfig(
        chave="aditivos", endpoint="aditivos",
        estrategia="json",
        empty_as_array=True,
    )
    registros = [{"status": False, "mensagem": "período sem dados"}]
    assert _montar_user_content(cfg, registros) == "[]"


def test_montar_user_content_json_status_false_sem_empty_as_array():
    cfg = TopicConfig(chave="rpfo", endpoint="rpfo", estrategia="json")
    registros = [{"status": False, "mensagem": "sem RPFO"}]
    resultado = json.loads(_montar_user_content(cfg, registros))
    assert resultado[0]["_nao_encontrado"] is True
    assert resultado[0]["mensagem"] == "sem RPFO"


def test_montar_user_content_json_filtra_campos_manter():
    cfg = TopicConfig(
        chave="rpfo", endpoint="rpfo",
        estrategia="json",
        campos_manter=("rpfo_numero", "rpfo_status"),
    )
    registros = [{"rpfo_numero": "001", "rpfo_status": "aberto", "campo_extra": "ignorado"}]
    resultado = json.loads(_montar_user_content(cfg, registros))
    assert "campo_extra" not in resultado[0]
    assert resultado[0]["rpfo_numero"] == "001"


# ---------------------------------------------------------------------------
# processar_topico — testes de integração com mocks
# ---------------------------------------------------------------------------

def _make_ctx(dnit_resp=None, openai_resp='{"conforme":"Conforme","motivo":"ok"}'):
    ctx = MagicMock()
    ctx.dnit = MagicMock()
    ctx.dnit.buscar_secao = AsyncMock(return_value={"resultado": [{"resumo": "Texto resumo."}]})
    if dnit_resp is not None:
        ctx.dnit.buscar_secao = AsyncMock(return_value=dnit_resp)
    ctx.openai = MagicMock()
    ctx.openai.chat = AsyncMock(return_value=openai_resp)
    ctx.openmeteo = MagicMock()
    ctx.nominatim = MagicMock()
    return ctx


@pytest.mark.asyncio
async def test_processar_topico_campo_ok():
    cfg = TopicConfig(
        chave="justificativa", endpoint="justificativa",
        estrategia="campo", campo_conteudo="resumo",
    )
    ctx = _make_ctx()
    resultado = await processar_topico(cfg, "system prompt", "contrato", "2025-01-01", "2025-01-31", ctx)
    assert resultado.ok is True
    assert resultado.topico == "justificativa"
    assert resultado.conteudo["conforme"] == "Conforme"


@pytest.mark.asyncio
async def test_processar_topico_json_ok():
    cfg = TopicConfig(
        chave="oaes", endpoint="oaes",
        estrategia="json",
        campos_manter=("nome_oae", "tipo_oae"),
    )
    ctx = _make_ctx(
        dnit_resp={"resultado": [{"nome_oae": "OAE-1", "tipo_oae": "Ponte", "campo_extra": "x"}]},
        openai_resp='{"conforme":"Atenção","motivo":"verificar"}',
    )
    resultado = await processar_topico(cfg, "prompt", "contrato", "2025-01-01", "2025-01-31", ctx)
    assert resultado.ok is True
    # infos não deve conter campo_extra (campos_manter filtra)
    infos = json.loads(resultado.conteudo["infos"])
    assert "campo_extra" not in infos[0]


@pytest.mark.asyncio
async def test_processar_topico_erro_propagado():
    cfg = TopicConfig(chave="justificativa", endpoint="justificativa", estrategia="campo")
    ctx = _make_ctx()
    ctx.dnit.buscar_secao = AsyncMock(side_effect=Exception("timeout"))
    resultado = await processar_topico(cfg, "prompt", "c", "2025-01-01", "2025-01-31", ctx)
    assert resultado.ok is False
    assert "timeout" in resultado.erro


@pytest.mark.asyncio
async def test_processar_topico_json_texto_nao_json_retornado():
    """Quando a LLM retorna texto puro (não JSON), o resultado deve ser ok=True com string."""
    cfg = TopicConfig(chave="oaes", endpoint="oaes", estrategia="json")
    ctx = _make_ctx(
        dnit_resp={"resultado": [{"nome_oae": "OAE-1"}]},
        openai_resp="Não foi possível avaliar.",
    )
    resultado = await processar_topico(cfg, "prompt", "c", "2025-01-01", "2025-01-31", ctx)
    assert resultado.ok is True
    assert isinstance(resultado.conteudo, str)
