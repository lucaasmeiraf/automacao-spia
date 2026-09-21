"""
Cliente da API Open-Meteo (dados meteorológicos históricos).

Equivale ao nó "Open-Meteo" do n8n. Não requer autenticação, mas exige
User-Agent identificando a aplicação conforme política de uso.
"""
from __future__ import annotations

import logging

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class OpenMeteoClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self._base_url = settings.openmeteo_base_url.rstrip("/")
        self._client = client
        self._headers = {"User-Agent": "SupraDNIT/1.0 (suporte@dnit.gov.br)"}

    async def buscar_historico(
        self,
        lat: float,
        lon: float,
        start_date: str,
        end_date: str,
    ) -> dict:
        """
        GET /v1/archive — precipitação, temperatura máxima, vento máximo e
        código de tempo (weathercode) diários para o período informado.
        """
        url = f"{self._base_url}/archive"
        params = {
            "latitude": lat,
            "longitude": lon,
            "start_date": start_date,
            "end_date": end_date,
            "daily": "precipitation_sum,temperature_2m_max,windspeed_10m_max,weathercode",
            "timezone": "auto",
        }
        logger.info(
            "Open-Meteo GET archive lat=%.4f lon=%.4f %s..%s",
            lat, lon, start_date, end_date,
        )
        resp = await self._client.get(url, params=params, headers=self._headers)
        resp.raise_for_status()
        return resp.json()
