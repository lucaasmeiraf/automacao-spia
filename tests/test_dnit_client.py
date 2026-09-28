"""
Testes do cliente SUPRA (`DnitClient`) com servidor simulado (httpx.MockTransport — nada real).

Cobrem a proteção contra "502 Proxy Error" (limite de simultaneidade + nova tentativa em
502/503/504) e, principalmente, que NADA mudou no que é enviado: URL, parâmetros (inclusive o
typo `periodo_incio`), headers e o JSON devolvido.
"""
from __future__ import annotations

import asyncio

import httpx
import pytest

from app.clients.dnit import DnitClient
from tests.helpers import fazer_settings

BASE = "https://supra.teste/index_cgcont_common.php/cgcont/ai"


def _cliente(handler, **kw) -> tuple[DnitClient, httpx.AsyncClient]:
    settings = fazer_settings(dnit_base_url=BASE, dnit_token="TOKEN-TESTE", dnit_retry_espera=0, **kw)
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return DnitClient(settings, http), http


def _roteiro(*respostas):
    """Handler que devolve as respostas em sequência e registra as requisições."""
    chamadas: list[httpx.Request] = []
    fila = list(respostas)

    async def handler(req: httpx.Request) -> httpx.Response:
        chamadas.append(req)
        status, corpo = fila.pop(0) if len(fila) > 1 else fila[0]
        return httpx.Response(status, json=corpo) if corpo is not None else httpx.Response(status, text="<html>erro</html>")

    return handler, chamadas


# ---------------------------------------------------------------------------
# Nada mudou no que é enviado
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_requisicao_identica_a_de_antes():
    handler, chamadas = _roteiro((200, {"status": True, "resultado": [{"resumo": "x"}]}))
    dnit, http = _cliente(handler)
    async with http:
        dados = await dnit.buscar_secao("justificativa", "00 00493/2013", "2025-10-01", "2025-10-31")

    assert dados == {"status": True, "resultado": [{"resumo": "x"}]}
    (req,) = chamadas
    assert req.method == "GET"
    assert req.url.path.endswith("/cgcont/ai/relatorio/secao_ws/justificativa")
    assert dict(req.url.params) == {
        "contrato": "00 00493/2013",
        "periodo_incio": "2025-10-01",   # typo intencional da API SUPRA
        "periodo_fim": "2025-10-31",
    }
    assert req.headers["token"] == "TOKEN-TESTE"
    assert req.headers["accept"] == "application/json"


@pytest.mark.asyncio
async def test_resposta_status_false_passa_adiante_sem_nova_tentativa():
    # Recusa lógica da SUPRA (HTTP 200): o comportamento continua o mesmo — devolve o JSON.
    handler, chamadas = _roteiro((200, {"status": False, "mensagem": "Token inválido."}))
    dnit, http = _cliente(handler)
    async with http:
        dados = await dnit.buscar_secao("capa", "c", "a", "b")
    assert dados == {"status": False, "mensagem": "Token inválido."}
    assert len(chamadas) == 1


@pytest.mark.asyncio
async def test_download_arquivo_mesmos_parametros():
    handler, chamadas = _roteiro((200, {"status": True, "resultado": "base64..."}))
    dnit, http = _cliente(handler)
    async with http:
        await dnit.download_arquivo("00 00493/2013", "mapa.png")
    (req,) = chamadas
    assert req.url.path.endswith("/arquivo/download_ws")
    assert dict(req.url.params) == {"contrato": "00 00493/2013", "nome_arquivo": "mapa.png"}


# ---------------------------------------------------------------------------
# Nova tentativa em 502/503/504
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [502, 503, 504])
async def test_erro_de_gateway_e_repetido_e_depois_funciona(status):
    handler, chamadas = _roteiro((status, None), (200, {"status": True, "resultado": []}))
    dnit, http = _cliente(handler)
    async with http:
        dados = await dnit.buscar_secao("historico", "c", "a", "b")
    assert dados == {"status": True, "resultado": []}
    assert len(chamadas) == 2


@pytest.mark.asyncio
async def test_502_persistente_falha_depois_das_tentativas():
    handler, chamadas = _roteiro((502, None))
    dnit, http = _cliente(handler, dnit_retries=2)
    async with http:
        with pytest.raises(httpx.HTTPStatusError):
            await dnit.buscar_secao("rpfo", "c", "a", "b")
    assert len(chamadas) == 3  # 1 + 2 novas tentativas


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 404, 500])
async def test_outros_erros_falham_na_hora_como_antes(status):
    handler, chamadas = _roteiro((status, {"erro": "x"}))
    dnit, http = _cliente(handler)
    async with http:
        with pytest.raises(httpx.HTTPStatusError):
            await dnit.buscar_secao("oaes", "c", "a", "b")
    assert len(chamadas) == 1


@pytest.mark.asyncio
async def test_retries_zero_desliga_novas_tentativas():
    handler, chamadas = _roteiro((502, None))
    dnit, http = _cliente(handler, dnit_retries=0)
    async with http:
        with pytest.raises(httpx.HTTPStatusError):
            await dnit.buscar_secao("rpfo", "c", "a", "b")
    assert len(chamadas) == 1


# ---------------------------------------------------------------------------
# Limite de simultaneidade
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_maximo_n_requisicoes_simultaneas_e_todas_concluem():
    em_curso = 0
    pico = 0

    async def handler(req: httpx.Request) -> httpx.Response:
        nonlocal em_curso, pico
        em_curso += 1
        pico = max(pico, em_curso)
        await asyncio.sleep(0.02)
        em_curso -= 1
        return httpx.Response(200, json={"status": True, "endpoint": req.url.path.rsplit("/", 1)[-1]})

    dnit, http = _cliente(handler, dnit_max_concorrencia=4)
    endpoints = [f"secao{i}" for i in range(15)]
    async with http:
        resultados = await asyncio.gather(*(dnit.buscar_secao(e, "c", "a", "b") for e in endpoints))

    assert pico == 4
    assert [r["endpoint"] for r in resultados] == endpoints  # todas concluem, cada uma com o seu dado


def test_configuracao_invalida_e_recusada():
    for kw in ({"dnit_max_concorrencia": 0}, {"dnit_retries": -1}, {"dnit_retry_espera": -1}):
        with pytest.raises(ValueError):
            fazer_settings(**kw)
