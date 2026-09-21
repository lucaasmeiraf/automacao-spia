"""
Cliente do Nominatim / OpenStreetMap (geocodificação).

Equivale ao nó "Pega Latitude e Longitude" (forward search) do n8n.
Não requer autenticação; identifica-se pelo User-Agent conforme política de uso.
"""
from __future__ import annotations

import logging

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class NominatimClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self._base_url = settings.nominatim_base_url.rstrip("/")
        self._client = client
        self._headers = {
            "User-Agent": "SupraDNIT/1.0 (suporte@dnit.gov.br)",
            "Accept-Language": "pt-BR",
        }

    async def search(self, query: str) -> list[dict]:
        """GET /search — geocodificação direta (endereço → lat/lon)."""
        url = f"{self._base_url}/search"
        params = {"q": query, "format": "json", "limit": 1}
        logger.info("Nominatim search query=%r", query)
        resp = await self._client.get(url, params=params, headers=self._headers)
        resp.raise_for_status()
        return resp.json()
