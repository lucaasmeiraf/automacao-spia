"""
Cliente da OpenAI (Chat Completions).

Equivale aos nós "LLM" (HTTP Request para api.openai.com/v1/chat/completions).
Mantém a chamada explícita via httpx — sem o SDK — para espelhar o fluxo atual
e facilitar a troca de modelo por tópico.
"""
from __future__ import annotations

import logging

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class OpenAIClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self._base_url = settings.openai_base_url.rstrip("/")
        self._api_key = settings.openai_api_key
        self._client = client

    async def chat(self, body: dict) -> str:
        """
        Envia um corpo já montado (model, messages, max_tokens, ...) e devolve
        o texto de choices[0].message.content.
        """
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        logger.info("OpenAI chat model=%s", body.get("model"))
        resp = await self._client.post(url, json=body, headers=headers)
        if resp.is_error:
            # A OpenAI explica o erro no corpo (ex.: modelo inválido, cota, formato) — sem isso o
            # log mostraria só "400 Bad Request". O corpo de erro não contém a chave.
            try:
                detalhe = resp.json().get("error", {}).get("message") or resp.text[:300]
            except ValueError:
                detalhe = resp.text[:300]
            raise httpx.HTTPStatusError(
                f"OpenAI HTTP {resp.status_code}: {detalhe}", request=resp.request, response=resp
            )
        data = resp.json()
        escolha = data["choices"][0]

        uso = data.get("usage") or {}
        logger.info(
            "OpenAI tokens model=%s entrada=%s saida=%s total=%s",
            data.get("model", body.get("model")),
            uso.get("prompt_tokens"), uso.get("completion_tokens"), uso.get("total_tokens"),
        )
        if escolha.get("finish_reason") == "length":
            logger.warning(
                "OpenAI cortou a resposta no limite de max_tokens=%s (model=%s): o JSON pode vir "
                "incompleto — aumente o max_tokens do tópico.",
                body.get("max_tokens"), body.get("model"),
            )
        return escolha["message"]["content"]
