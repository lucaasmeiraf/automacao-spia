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
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
