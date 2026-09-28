"""
Execução de um relatório: seleciona os tópicos e roda todos em paralelo.

É o MESMO caminho para o webhook (`POST /webhook/relatorio`) e para o botão "Executar" da tela de
dev (`POST /api/executar`), para que o que se testa na tela seja exatamente o que a automação faz.

Diferenças que só a tela usa:
  - `somente`: roda exatamente este conjunto de tópicos, ignorando `config/topics.yaml` (execução
    avulsa de um tópico, sem alterar o estado salvo);
  - `dry_run`: não chama a OpenAI (ver `processing/dry_run.py`).
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging

from app.config import Settings
from app.models import RelatorioRequest, RelatorioResponse, TopicoResultado
from app.processing.context import ProcessingContext
from app.processing.dry_run import OpenAISimulado, resultado_dry_run
from app.processing.pipeline import processar_topico
from app.processing.selecao import selecionar_topicos
from app.topic_state import ler_estado
from app.topics import TopicConfig

logger = logging.getLogger(__name__)


class ConfiguracaoIndisponivel(Exception):
    """`config/topics.yaml` ausente ou inválido: falha segura, nada roda."""


# Resposta (503) ao cliente: genérica — o motivo (com caminho de arquivo) fica só no log.
MSG_CONFIG_INDISPONIVEL = "Configuração de tópicos indisponível. Contate o administrador."


async def executar_relatorio(
    req: RelatorioRequest,
    ctx: ProcessingContext,
    settings: Settings,
    *,
    somente: frozenset[str] | None = None,
    dry_run: bool = False,
) -> RelatorioResponse:
    if somente is None:
        estado = await ler_estado(settings.topics_file)
        if estado.erro:
            raise ConfiguracaoIndisponivel(estado.erro)
        ativos = estado.ativos
    else:
        ativos = somente

    prompts = req.prompts_ativos()  # equivale ao "Separa Prompts"
    selecao = await selecionar_topicos(ativos, prompts, settings.prompts_dir)
    logger.info(
        "Execução contrato=%r período=%r..%r | %d tópico(s) a executar, %d ignorado(s)%s",
        req.contrato[:64], req.periodo_inicio[:32], req.periodo_fim[:32],
        len(selecao.executar), len(selecao.ignorados),
        " | DRY-RUN (sem OpenAI)" if dry_run else "",
    )

    async def rodar(cfg: TopicConfig, prompt_sistema: str) -> TopicoResultado:
        if not dry_run:
            return await processar_topico(
                cfg, prompt_sistema, req.contrato, req.periodo_inicio, req.periodo_fim, ctx
            )
        simulado = OpenAISimulado()
        resultado = await processar_topico(
            cfg, prompt_sistema, req.contrato, req.periodo_inicio, req.periodo_fim,
            dataclasses.replace(ctx, openai=simulado),
        )
        return resultado_dry_run(resultado, simulado.chamadas)

    # Tópicos em paralelo (equivale aos branches paralelos do n8n). Cada handler captura as
    # próprias exceções e devolve ok=False, então um tópico com erro não derruba os demais.
    resultados = await asyncio.gather(*(rodar(cfg, p) for cfg, p in selecao.executar))

    return RelatorioResponse(
        contrato=req.contrato,
        periodo_inicio=req.periodo_inicio,
        periodo_fim=req.periodo_fim,
        topicos=list(resultados) + selecao.erros,
    )
