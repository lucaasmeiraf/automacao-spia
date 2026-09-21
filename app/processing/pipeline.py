"""
Pipeline genérico de um tópico.

Para tópicos com estratégia simples ("campo" ou "json"), executa a sequência
de 4 nós do n8n: fetch → payload → LLM → limpa retorno.

Para estratégias especiais, delega para o handler correspondente:
  - "imagem"        → app/processing/image.py
  - "contratuais"   → app/processing/contratuais.py
  - "pluviometrico" → app/processing/pluviometrico.py
"""
from __future__ import annotations

import json
import logging

from app.models import TopicoResultado
from app.processing.context import ProcessingContext
from app.processing.records import detectar_vazio, limpar_registro
from app.topics import TopicConfig

logger = logging.getLogger(__name__)


def _como_lista(resultado) -> list[dict]:
    """A API às vezes devolve um objeto, às vezes uma lista. Normaliza para lista."""
    if isinstance(resultado, list):
        return resultado
    if isinstance(resultado, dict) and "resultado" in resultado:
        r = resultado["resultado"]
        return r if isinstance(r, list) else [r]
    return [resultado]


def _montar_user_content(cfg: TopicConfig, registros: list[dict]) -> str:
    """
    Monta o conteúdo do usuário conforme a estratégia do tópico.

    Para "json": detecta registros sem dados e envia [] quando empty_as_array=True,
    ou [{_nao_encontrado: true}] quando a API retornou status=false sem empty_as_array.
    """
    if cfg.estrategia == "json":
        primeiro = registros[0] if registros else {}

        # API sinalizou ausência de dados
        if primeiro.get("status") is False:
            if cfg.empty_as_array:
                return "[]"
            return json.dumps(
                [{"_nao_encontrado": True, "mensagem": primeiro.get("mensagem", "")}],
                ensure_ascii=False,
            )

        # Verifica se os registros têm dados reais
        if cfg.empty_as_array and detectar_vazio(registros, cfg.campos_presenca):
            return "[]"

        # Filtra colunas, limpa HTML e remove \r\n
        limpos = [
            limpar_registro(r, cfg.campos_manter, cfg.html_fields)
            for r in registros
        ]
        return json.dumps(limpos, ensure_ascii=False)

    # estrategia == "campo": usa o campo indicado do primeiro registro
    if cfg.html_fields:
        registros = [limpar_registro(r, (), cfg.html_fields) for r in registros]
    primeiro = registros[0] if registros else {}
    return str(primeiro.get(cfg.campo_conteudo, "") or "")


def _interpretar_retorno(conteudo: str):
    """
    Tenta interpretar a resposta da IA como JSON.
    Se não for JSON válido, devolve o texto puro.
    """
    try:
        return json.loads(conteudo)
    except (json.JSONDecodeError, TypeError):
        return conteudo


async def processar_topico(
    cfg: TopicConfig,
    prompt_sistema: str,
    contrato: str,
    periodo_inicio: str,
    periodo_fim: str,
    ctx: ProcessingContext,
) -> TopicoResultado:
    """
    Ponto de entrada único para processar qualquer tópico.
    Estratégias complexas são delegadas; "campo" e "json" são tratadas aqui.
    """
    # Roteamento para handlers especializados
    if cfg.estrategia == "imagem":
        from app.processing.image import processar_imagem
        return await processar_imagem(
            cfg, prompt_sistema, contrato, periodo_inicio, periodo_fim, ctx
        )

    if cfg.estrategia == "contratuais":
        from app.processing.contratuais import processar_contratuais
        return await processar_contratuais(
            cfg, prompt_sistema, contrato, periodo_inicio, periodo_fim, ctx
        )

    if cfg.estrategia == "pluviometrico":
        from app.processing.pluviometrico import processar_pluviometrico
        return await processar_pluviometrico(
            cfg, prompt_sistema, contrato, periodo_inicio, periodo_fim, ctx
        )

    # Fluxo genérico: "campo" e "json"
    try:
        # 1) FETCH
        bruto = await ctx.dnit.buscar_secao(
            cfg.endpoint, contrato, periodo_inicio, periodo_fim
        )
        registros = _como_lista(bruto)

        # 2) PAYLOAD (monta corpo da chamada à OpenAI)
        user_content = _montar_user_content(cfg, registros)

        body = {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "messages": [
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": user_content},
            ],
        }

        # 3) LLM
        resposta = await ctx.openai.chat(body)

        # 4) LIMPA RETORNO (interpreta + anexa dado bruto original em 'infos')
        conteudo = _interpretar_retorno(resposta)
        if isinstance(conteudo, dict):
            conteudo["infos"] = user_content

        return TopicoResultado(topico=cfg.chave, ok=True, conteudo=conteudo)

    except Exception as exc:
        logger.exception("Falha ao processar tópico '%s'", cfg.chave)
        return TopicoResultado(topico=cfg.chave, ok=False, erro=str(exc))
