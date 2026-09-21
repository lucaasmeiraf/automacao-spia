"""
Handler para tópicos com análise de imagem (Mapa de Situação, Diagrama de Ocorrências).

Equivale às chains: fetch endpoint → download imagem → gpt-4o visão →
limpa retorno (com estrutura garantida por tópico).
"""
from __future__ import annotations

import json
import logging
import re

from app.models import TopicoResultado
from app.processing.context import ProcessingContext
from app.processing.html_clean import strip_html
from app.topics import TopicConfig

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]*>")


def _como_lista(resultado) -> list[dict]:
    if isinstance(resultado, list):
        return resultado
    if isinstance(resultado, dict) and "resultado" in resultado:
        r = resultado["resultado"]
        return r if isinstance(r, list) else [r]
    return [resultado]


def _fallback_mapa_situacao(motivo: str) -> dict:
    return {
        "identificador": "Mapa de Situação",
        "conforme": "Atenção",
        "motivo": motivo,
        "elementos_cartograficos": {
            "mapa_brasil": "Não analisado",
            "localizacao_rodovia": "Não analisado",
            "ponto_inicial_final": "Não analisado",
            "municipios_atravessados": "Não analisado",
            "sentido_predominante": "Não analisado",
        },
        "informacoes_legenda": {
            "rodovia": "Não analisado",
            "extensao_pnv": "Não analisado",
            "trecho_contrato": "Não analisado",
        },
        "infos": {},
    }


def _fallback_diagrama_ocorrencias(motivo: str) -> dict:
    return {
        "identificador": "Diagrama de Ocorrências",
        "conforme": "Atenção",
        "motivo": motivo,
        "pontos_passagem": {
            "municipios": "Não analisado",
            "sentido_n_s": "Não analisado",
            "distancia_extensao": "Não analisado",
        },
        "ocorrencias_projeto": {
            "tipo": "Não analisado",
            "quantidade": "Não analisado",
            "localizacao": "Não analisado",
        },
        "apresentacao": {
            "escala": "Não analisado",
            "orientacao": "Não analisado",
            "legenda": "Não analisado",
        },
        "infos": {},
    }


def _fallback(chave: str, motivo: str) -> dict:
    if chave == "diagrama_ocorrencias":
        return _fallback_diagrama_ocorrencias(motivo)
    return _fallback_mapa_situacao(motivo)


def _normalizar_mapa_situacao(ai: dict, infos: dict) -> dict:
    ec = ai.get("elementos_cartograficos") or {}
    il = ai.get("informacoes_legenda") or {}
    ai["identificador"] = "Mapa de Situação"
    ai["elementos_cartograficos"] = {
        "mapa_brasil": ec.get("mapa_brasil") or "Não identificado",
        "localizacao_rodovia": ec.get("localizacao_rodovia") or "Não identificado",
        "ponto_inicial_final": ec.get("ponto_inicial_final") or "Não identificado",
        "municipios_atravessados": ec.get("municipios_atravessados") or "Não identificado",
        "sentido_predominante": ec.get("sentido_predominante") or "Não identificado",
    }
    ai["informacoes_legenda"] = {
        "rodovia": il.get("rodovia") or "Não identificado",
        "extensao_pnv": il.get("extensao_pnv") or "Não identificado",
        "trecho_contrato": il.get("trecho_contrato") or "Não identificado",
    }
    ai["infos"] = infos
    return ai


def _normalizar_diagrama_ocorrencias(ai: dict, infos: dict) -> dict:
    pp = ai.get("pontos_passagem") or {}
    op = ai.get("ocorrencias_projeto") or {}
    ap = ai.get("apresentacao") or {}
    ai["identificador"] = "Diagrama de Ocorrências"
    ai["pontos_passagem"] = {
        "municipios": pp.get("municipios") or "Não identificado",
        "sentido_n_s": pp.get("sentido_n_s") or "Não identificado",
        "distancia_extensao": pp.get("distancia_extensao") or "Não identificado",
    }
    ai["ocorrencias_projeto"] = {
        "tipo": op.get("tipo") or "Não identificado",
        "quantidade": op.get("quantidade") or "Não identificado",
        "localizacao": op.get("localizacao") or "Não identificado",
    }
    ai["apresentacao"] = {
        "escala": ap.get("escala") or "Não identificado",
        "orientacao": ap.get("orientacao") or "Não identificado",
        "legenda": ap.get("legenda") or "Não identificado",
    }
    ai["infos"] = infos
    return ai


def _normalizar(chave: str, ai: dict, infos: dict) -> dict:
    if chave == "diagrama_ocorrencias":
        return _normalizar_diagrama_ocorrencias(ai, infos)
    return _normalizar_mapa_situacao(ai, infos)


async def processar_imagem(
    cfg: TopicConfig,
    prompt_sistema: str,
    contrato: str,
    periodo_inicio: str,
    periodo_fim: str,
    ctx: ProcessingContext,
) -> TopicoResultado:
    """
    Fluxo: fetch endpoint → extrai nome_arquivo → download → análise gpt-4o.
    Retorna fallback estruturado em caso de erro ou imagem não disponível.
    """
    try:
        # 1. Busca metadados da imagem no endpoint do tópico
        bruto = await ctx.dnit.buscar_secao(cfg.endpoint, contrato, periodo_inicio, periodo_fim)
        registros = _como_lista(bruto)
        if not registros:
            conteudo = _fallback(cfg.chave, "Nenhum registro retornado pelo endpoint.")
            return TopicoResultado(topico=cfg.chave, ok=True, conteudo=conteudo)

        meta = registros[0]
        nome_arquivo = meta.get("nome_arquivo") or ""
        descricao = strip_html(meta.get("descricao_arquivo") or "")
        data_foto = meta.get("data_foto") or ""

        if not nome_arquivo:
            conteudo = _fallback(cfg.chave, "Arquivo de imagem não informado pelo endpoint.")
            return TopicoResultado(topico=cfg.chave, ok=True, conteudo=conteudo)

        # 2. Download da imagem
        download_resp = await ctx.dnit.download_arquivo(contrato, nome_arquivo)
        arquivo = (
            download_resp.get("resultado") if isinstance(download_resp, dict) else None
        )
        if not arquivo:
            conteudo = _fallback(cfg.chave, "Falha ao baixar o arquivo de imagem.")
            return TopicoResultado(topico=cfg.chave, ok=True, conteudo=conteudo)

        base64_data = arquivo.get("base64") or ""
        mime_type = arquivo.get("mime_type") or "image/png"

        if not base64_data or not mime_type.startswith("image/"):
            conteudo = _fallback(cfg.chave, "Arquivo baixado não é uma imagem válida.")
            return TopicoResultado(topico=cfg.chave, ok=True, conteudo=conteudo)

        data_uri = f"data:{mime_type};base64,{base64_data}"

        infos = {
            "nomeArquivo": nome_arquivo,
            "descricao": descricao,
            "data": data_foto,
            "base64": data_uri,
        }

        # 3. Monta mensagem com visão para o gpt-4o
        texto_usuario = (
            f"Analise este arquivo para o período de {periodo_inicio} a {periodo_fim}.\n\n"
            f"Metadados:\n"
            f"- Arquivo: {nome_arquivo}\n"
            f"- Data: {data_foto}\n"
            f"- Descrição: \"{descricao}\"\n\n"
            f"Retorne o JSON conforme instruído."
        )
        body = {
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "messages": [
                {"role": "system", "content": prompt_sistema},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": data_uri, "detail": "high"},
                        },
                        {"type": "text", "text": texto_usuario},
                    ],
                },
            ],
        }

        # 4. Chamada à LLM
        resposta = await ctx.openai.chat(body)

        # 5. Limpa retorno e garante estrutura
        try:
            parsed = json.loads(resposta)
        except (json.JSONDecodeError, TypeError):
            conteudo = _fallback(cfg.chave, "Retorno da IA não pôde ser interpretado como JSON.")
            conteudo["infos"] = infos
            return TopicoResultado(topico=cfg.chave, ok=True, conteudo=conteudo)

        conteudo = _normalizar(cfg.chave, parsed, infos)
        return TopicoResultado(topico=cfg.chave, ok=True, conteudo=conteudo)

    except Exception as exc:
        logger.exception("Falha ao processar tópico de imagem '%s'", cfg.chave)
        return TopicoResultado(topico=cfg.chave, ok=False, erro=str(exc))
