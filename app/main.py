"""
Aplicação FastAPI — ponto de entrada.

Substitui o nó "Webhook" (+ "If" + "Separa Prompts" + "Respond to Webhook").
Recebe o POST, valida, separa os prompts ativos e processa cada tópico ativo
que já esteja configurado em `app/topics.py`.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from app.clients.dnit import DnitClient
from app.clients.nominatim import NominatimClient
from app.clients.openai_client import OpenAIClient
from app.clients.openmeteo import OpenMeteoClient
from app.config import get_settings
from app.logging_config import setup_logging
from app.models import RelatorioRequest, RelatorioResponse, TopicoResultado
from app.processing.context import ProcessingContext
from app.processing.pipeline import processar_topico
from app.topics import topico_configurado

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    # Um único AsyncClient reaproveitado por toda a aplicação (connection pooling).
    async with httpx.AsyncClient(
        timeout=settings.http_timeout,
        transport=httpx.AsyncHTTPTransport(retries=settings.http_max_retries),
    ) as client:
        app.state.settings = settings
        app.state.dnit = DnitClient(settings, client)
        app.state.openai = OpenAIClient(settings, client)
        app.state.openmeteo = OpenMeteoClient(settings, client)
        app.state.nominatim = NominatimClient(settings, client)
        logger.info("Supra IA iniciada.")
        yield
    logger.info("Supra IA finalizada.")


app = FastAPI(title="Supra IA", version="0.1.0", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    """Checagem simples de saúde (útil para Docker/monitoramento)."""
    return {"status": "ok"}


@app.post("/webhook/relatorio", response_model=RelatorioResponse)
async def gerar_relatorio(req: RelatorioRequest) -> RelatorioResponse:
    """
    Endpoint principal. A validação de contrato/período é feita automaticamente
    pelo modelo Pydantic (equivale ao nó 'If'); se algo faltar, o FastAPI
    devolve 422 sem entrar aqui.
    """
    prompts = req.prompts_ativos()  # equivale ao "Separa Prompts"
    logger.info(
        "Requisição contrato=%s período=%s..%s | %d prompt(s) ativo(s)",
        req.contrato, req.periodo_inicio, req.periodo_fim, len(prompts),
    )

    ctx = ProcessingContext(
        dnit=app.state.dnit,
        openai=app.state.openai,
        openmeteo=app.state.openmeteo,
        nominatim=app.state.nominatim,
    )

    # Separa tópicos configurados dos não-configurados
    tarefas = []
    nao_configurados: list[TopicoResultado] = []

    for chave, prompt_sistema in prompts.items():
        cfg = topico_configurado(chave)
        if cfg is None:
            nao_configurados.append(
                TopicoResultado(
                    topico=chave,
                    ok=False,
                    erro="tópico ainda não configurado em app/topics.py",
                )
            )
        else:
            tarefas.append(
                processar_topico(
                    cfg, prompt_sistema,
                    req.contrato, req.periodo_inicio, req.periodo_fim,
                    ctx,
                )
            )

    # Executa tópicos configurados em paralelo (equivale aos branches paralelos do n8n)
    resultados_paralelos = await asyncio.gather(*tarefas)

    return RelatorioResponse(
        contrato=req.contrato,
        periodo_inicio=req.periodo_inicio,
        periodo_fim=req.periodo_fim,
        topicos=list(resultados_paralelos) + nao_configurados,
    )
