"""Testes do `OpenAIClient` com servidor simulado (httpx.MockTransport — nada real)."""
from __future__ import annotations

import logging

import httpx
import pytest

from app.clients.openai_client import OpenAIClient
from tests.helpers import fazer_settings


def _cliente(resposta: httpx.Response) -> tuple[OpenAIClient, httpx.AsyncClient]:
    async def handler(req: httpx.Request) -> httpx.Response:
        return resposta

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAIClient(fazer_settings(openai_api_key="sk-teste"), http), http


def _ok(conteudo: str, finish_reason: str = "stop") -> httpx.Response:
    return httpx.Response(200, json={
        "model": "gpt-4o-mini",
        "choices": [{"message": {"content": conteudo}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150},
    })


@pytest.mark.asyncio
async def test_devolve_conteudo_e_loga_tokens(caplog):
    openai, http = _cliente(_ok('{"conforme": "Conforme"}'))
    with caplog.at_level(logging.INFO, logger="app.clients.openai_client"):
        async with http:
            texto = await openai.chat({"model": "gpt-4o-mini", "messages": []})
    assert texto == '{"conforme": "Conforme"}'
    assert "entrada=120 saida=30 total=150" in caplog.text


@pytest.mark.asyncio
async def test_avisa_quando_a_resposta_foi_cortada(caplog):
    openai, http = _cliente(_ok('{"conforme": "Conf', finish_reason="length"))
    with caplog.at_level(logging.WARNING, logger="app.clients.openai_client"):
        async with http:
            await openai.chat({"model": "gpt-4o", "max_tokens": 800, "messages": []})
    assert "max_tokens=800" in caplog.text


@pytest.mark.asyncio
async def test_erro_mostra_a_mensagem_da_openai_sem_a_chave():
    erro = httpx.Response(400, json={"error": {"message": "Invalid model 'gpt-x'."}})
    openai, http = _cliente(erro)
    async with http:
        with pytest.raises(httpx.HTTPStatusError) as exc:
            await openai.chat({"model": "gpt-x", "messages": []})
    assert "OpenAI HTTP 400: Invalid model 'gpt-x'." in str(exc.value)
    assert "sk-teste" not in str(exc.value)
