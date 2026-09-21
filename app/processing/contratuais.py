"""
Handler para o tópico 'info_contratuais_supervisora'.

Equivale ao nó "Payload Infos. Contratuais Sup." do n8n: formata datas e
valores monetários antes de enviar à LLM.
"""
from __future__ import annotations

import json
import logging

from app.models import TopicoResultado
from app.processing.context import ProcessingContext
from app.topics import TopicConfig

logger = logging.getLogger(__name__)


def _formatar_data(iso: str | None) -> str:
    """Converte YYYY-MM-DD em DD/MM/YYYY. Retorna 'Não informado' se vazio."""
    if not iso:
        return "Não informado"
    try:
        partes = iso[:10].split("-")
        return f"{partes[2]}/{partes[1]}/{partes[0]}"
    except (IndexError, ValueError):
        return iso


def _formatar_moeda(valor) -> str:
    """Formata float/int como 'R$ X.XXX,XX'. Retorna 'Não informado' se nulo."""
    if valor is None:
        return "Não informado"
    try:
        f = float(valor)
        inteiro = int(f)
        centavos = round((f - inteiro) * 100)
        inteiro_fmt = f"{inteiro:,}".replace(",", ".")
        return f"R$ {inteiro_fmt},{centavos:02d}"
    except (TypeError, ValueError):
        return str(valor)


def _formatar_registro(d: dict) -> dict:
    """
    Transforma o registro bruto da API em dicionário com campos formatados,
    equivalente ao código JS do nó 'Payload Infos. Contratuais Sup.'.
    """
    return {
        "empresa": (d.get("empresa") or "").strip() or "Não informado",
        "contrato": d.get("contrato_supervisora") or "Não informado",
        "processo_base": d.get("num_processo_base") or "Não informado",
        "objeto": (d.get("objeto_contrato") or "").strip() or "Não informado",
        "data_base": _formatar_data(d.get("data_base")),
        "data_publicacao_dou": _formatar_data(d.get("data_publicacao_DOU")),
        "data_publicacao_resultado_dou": _formatar_data(
            d.get("data_publicacao_resultado_licitacao_DOU")
        ),
        "data_assinatura": _formatar_data(d.get("data_assinatura")),
        "data_licitacao": _formatar_data(d.get("data_licitacao")),
        "ordem_inicio": _formatar_data(d.get("ordem_inicio_servicos")),
        "prazo_inicial_dias": d.get("prazo_inicial_execucao") or "Não informado",
        "data_inicial_termino": _formatar_data(d.get("data_inicial_termino")),
        "total_dias_aditados": d.get("total_dias_aditados") or "Não informado",
        "total_dias_paralisados": d.get("total_dias_paralisados") or "Não informado",
        "data_termino_atualizada": _formatar_data(d.get("dt_termino_atualizada")),
        "valor_pi": _formatar_moeda(d.get("valor_pi_contrato")),
        "valor_aditivado": _formatar_moeda(d.get("valor_total_aditivado_contrato")),
        "valor_reajuste": _formatar_moeda(d.get("valor_reajuste_contrato")),
        "valor_atualizado": _formatar_moeda(d.get("valor_atualizado_contrato")),
        # Campos não retornados pela API (mantidos como no n8n)
        "rodovia": "Não retornado pela API",
        "pnv_inicial_final": "Não retornado pela API",
        "estaca_inicial_final": "Não retornado pela API",
        "extensao": "Não retornado pela API",
    }


def _como_lista(resultado) -> list[dict]:
    if isinstance(resultado, list):
        return resultado
    if isinstance(resultado, dict) and "resultado" in resultado:
        r = resultado["resultado"]
        return r if isinstance(r, list) else [r]
    return [resultado]


async def processar_contratuais(
    cfg: TopicConfig,
    prompt_sistema: str,
    contrato: str,
    periodo_inicio: str,
    periodo_fim: str,
    ctx: ProcessingContext,
) -> TopicoResultado:
    """Fluxo: fetch → formata campos → LLM → interpreta retorno."""
    try:
        bruto = await ctx.dnit.buscar_secao(cfg.endpoint, contrato, periodo_inicio, periodo_fim)
        registros = _como_lista(bruto)
        primeiro = registros[0] if registros else {}

        formatado = _formatar_registro(primeiro)
        user_content = json.dumps(formatado, ensure_ascii=False)

        body = {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "messages": [
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": user_content},
            ],
        }

        resposta = await ctx.openai.chat(body)

        try:
            conteudo = json.loads(resposta)
        except (json.JSONDecodeError, TypeError):
            conteudo = resposta

        if isinstance(conteudo, dict):
            conteudo["infos"] = formatado

        return TopicoResultado(topico=cfg.chave, ok=True, conteudo=conteudo)

    except Exception as exc:
        logger.exception("Falha ao processar tópico '%s'", cfg.chave)
        return TopicoResultado(topico=cfg.chave, ok=False, erro=str(exc))
