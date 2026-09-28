"""
Cliente da API do SUPRA/DNIT.

Equivale aos nós HTTP Request que buscam os dados de cada tópico
(ex.: .../secao_ws/justificativa) e ao download de imagens.

Proteção do servidor da SUPRA (2026-09-28): com ~15 chamadas simultâneas o proxy da SUPRA
devolve "502 Proxy Error" para algumas; uma a uma, todas funcionam. Por isso:
  - no máximo `dnit_max_concorrencia` requisições simultâneas à SUPRA (as demais aguardam a vez);
  - 502/503/504 são repetidos até `dnit_retries` vezes, com espera crescente. Só GETs de leitura:
    repetir não altera nada no SUPRA. Outros erros (401, 404, 500…) falham na hora, como antes.
Os dados, parâmetros e headers enviados são exatamente os mesmos de antes.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

# Erros de gateway/proxy: indicam sobrecarga momentânea, não um problema na requisição.
_STATUS_REPETIVEIS = frozenset({502, 503, 504})


class DnitClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self._base_url = settings.dnit_base_url.rstrip("/")
        self._token = settings.dnit_token
        self._client = client
        self._semaforo = asyncio.Semaphore(settings.dnit_max_concorrencia)
        self._retries = settings.dnit_retries
        self._espera = settings.dnit_retry_espera

    @property
    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "token": self._token}

    async def _get_json(self, url: str, params: dict[str, str], descricao: str) -> dict | list:
        """GET com limite de simultaneidade e nova tentativa em 502/503/504."""
        for tentativa in range(self._retries + 1):
            async with self._semaforo:
                resp = await self._client.get(url, params=params, headers=self._headers)
            if resp.status_code in _STATUS_REPETIVEIS and tentativa < self._retries:
                espera = self._espera * (tentativa + 1)
                logger.warning(
                    "SUPRA %s: HTTP %d, nova tentativa %d/%d em %.1f s",
                    descricao, resp.status_code, tentativa + 1, self._retries, espera,
                )
                await asyncio.sleep(espera)  # fora do semáforo: não segura a vaga de outro tópico
                continue
            resp.raise_for_status()
            return resp.json()
        raise AssertionError("inalcançável")  # o laço sempre retorna ou levanta

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
        return await self._get_json(url, params, f"secao_ws/{endpoint}")

    async def download_arquivo(self, contrato: str, nome_arquivo: str) -> dict | list:
        """GET .../arquivo/download_ws — usado nos tópicos com análise de imagem."""
        url = f"{self._base_url}/arquivo/download_ws"
        params = {"contrato": contrato, "nome_arquivo": nome_arquivo}
        return await self._get_json(url, params, "arquivo/download_ws")
