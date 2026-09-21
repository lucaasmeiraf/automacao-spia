"""
Cliente da API do SUPRA/DNIT.

Equivale aos nós HTTP Request que buscam os dados de cada tópico
(ex.: .../secao_ws/justificativa) e ao download de imagens.
"""
from __future__ import annotations

import logging

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class DnitClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self._base_url = settings.dnit_base_url.rstrip("/")
        self._token = settings.dnit_token
        self._client = client

    @property
    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "token": self._token}

    async def buscar_secao(
        self,
        endpoint: str,
        contrato: str,
        periodo_inicio: str,
        periodo_fim: str,
    ) -> dict | list:
        """
        GET .../relatorio/secao_ws/<endpoint>

        Atenção: o parâmetro de início chama-se `periodo_incio` (sem o segundo
        "i"). Esse é o nome que a API do DNIT espera — mantido igual ao fluxo
        original do n8n de propósito. NÃO "corrija" sem confirmar no servidor.
        """
        url = f"{self._base_url}/relatorio/secao_ws/{endpoint}"
        params = {
            "contrato": contrato,
            "periodo_incio": periodo_inicio,  # typo intencional (contrato com a API)
            "periodo_fim": periodo_fim,
        }
        logger.info("DNIT GET secao_ws/%s (contrato=%s)", endpoint, contrato)
        resp = await self._client.get(url, params=params, headers=self._headers)
        resp.raise_for_status()
        return resp.json()

    async def download_arquivo(self, contrato: str, nome_arquivo: str) -> dict | list:
        """GET .../arquivo/download_ws — usado nos tópicos com análise de imagem."""
        url = f"{self._base_url}/arquivo/download_ws"
        params = {"contrato": contrato, "nome_arquivo": nome_arquivo}
        resp = await self._client.get(url, params=params, headers=self._headers)
        resp.raise_for_status()
        return resp.json()
