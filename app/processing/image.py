"""
Handler para tópicos com análise de imagem (Mapa de Situação, Diagrama de Ocorrências).

Equivale às chains: fetch endpoint → download imagem → gpt-4o visão →
limpa retorno (com estrutura garantida por tópico).

Formato real do endpoint (confirmado na SUPRA em 2026-09-29, mapa_situacao):
    {"status": true, "mensagem": "...", "resultado": [{"id_arquivo": "481468",
     "nome_arquivo": "573706884_795.jpg", "nomeOriginalArquivo": "Mapa Localização L1",
     "desc_arquivo": "None", "pasta_origem": "arquivo", "ultima_alteracao": "2024-04-23 14:33:25.000", ...}]}
O download fica em `DnitClient.download_arquivo`.

Comparado com o fluxo n8n (nós "Payload …" e "Limpa Retorno …"): o download_ws responde JSON com
`resultado.base64` + `resultado.mime_type` (o n8n NÃO convertia nada); o retorno da IA tem ```json
removido e, se não for JSON, os campos são recuperados por regex; a estrutura garantida usa as mesmas
chaves do n8n. Diferença proposital: sem imagem, não chamamos a LLM só para devolver o fallback.
"""
from __future__ import annotations

import logging

from app.clients.dnit import ArquivoInvalido
from app.models import TopicoResultado
from app.processing.context import ProcessingContext
from app.processing.html_clean import strip_html
from app.processing.llm_resposta import (
    CONFORME_PADRAO,
    MOTIVO_ERRO_PARSE,
    campo_por_regex,
    extrair_json,
    pedir_json,
)
from app.topics import TopicConfig

logger = logging.getLogger(__name__)

def _texto_meta(meta: dict, *campos: str) -> str:
    """Primeiro campo preenchido. A SUPRA manda "None" (texto) quando o campo está vazio."""
    for campo in campos:
        valor = meta.get(campo)
        if valor is None:
            continue
        texto = str(valor).strip()
        if texto and texto.lower() not in ("none", "null"):
            return texto
    return ""


def _como_lista(resultado) -> list[dict]:
    if isinstance(resultado, list):
        return resultado
    if isinstance(resultado, dict) and "resultado" in resultado:
        r = resultado["resultado"]
        return r if isinstance(r, list) else [r]
    return [resultado]


# Estrutura garantida por tópico — as MESMAS chaves dos nós "Limpa Retorno" do n8n (e que os prompts
# pedem à LLM). Chaves diferentes fazem a resposta da IA ser descartada e virar "Não identificado".
_ESQUEMAS: dict[str, tuple[str, dict[str, tuple[str, ...]]]] = {
    "mapa_situacao": ("Mapa de Situação", {
        "elementos_cartograficos": (
            "mapa_brasil", "mapa_regional", "malha_viaria", "corpos_dagua", "folha_a4_rm2",
        ),
        "informacoes_legenda": ("rodovia", "trecho", "segmento", "extensao", "codigo_snv"),
    }),
    "diagrama_ocorrencias": ("Diagrama de Ocorrências", {
        "pontos_passagem": ("municipios", "travessias_urbanas", "entroncamentos", "oaes", "rios"),
        "ocorrencias_projeto": ("jazidas_pedreiras", "usinas_canteiros", "areas_emprestimo_botafora"),
        "apresentacao": ("diagrama_unifilar", "legenda", "quilometragem"),
    }),
}

def _esquema(chave: str) -> tuple[str, dict[str, tuple[str, ...]]]:
    return _ESQUEMAS.get(chave, _ESQUEMAS["mapa_situacao"])


def _fallback(chave: str, motivo: str) -> dict:
    identificador, grupos = _esquema(chave)
    conteudo: dict = {"identificador": identificador, "conforme": "Atenção", "motivo": motivo}
    for grupo, campos in grupos.items():
        conteudo[grupo] = {campo: "Não analisado" for campo in campos}
    conteudo["infos"] = {}
    return conteudo


def _normalizar(chave: str, ai: dict, infos: dict) -> dict:
    """Garante a estrutura do n8n sem descartar o que a IA respondeu (campos extras são mantidos)."""
    identificador, grupos = _esquema(chave)
    ai["identificador"] = identificador
    for grupo, campos in grupos.items():
        recebido = ai.get(grupo) if isinstance(ai.get(grupo), dict) else {}
        ai[grupo] = {campo: recebido.get(campo) or "Não identificado" for campo in campos}
        ai[grupo].update({k: v for k, v in recebido.items() if k not in campos})
    ai["infos"] = infos
    return ai


def _interpretar_resposta(chave: str, resposta: str | None) -> dict:
    """Resposta da IA → dict; sem JSON válido, recupera campo a campo por regex (como o n8n)."""
    dados = extrair_json(resposta)
    if isinstance(dados, dict):
        return dados

    logger.warning("Resposta da IA para '%s' não é JSON válido; recuperando campos por regex.", chave)
    _, grupos = _esquema(chave)
    recuperado: dict = {
        "conforme": campo_por_regex(resposta, "conforme") or CONFORME_PADRAO,
        "motivo": campo_por_regex(resposta, "motivo") or MOTIVO_ERRO_PARSE,
        "erro_parse": True,
    }
    for grupo, campos in grupos.items():
        recuperado[grupo] = {campo: campo_por_regex(resposta, campo) for campo in campos}
    return recuperado


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
        if isinstance(bruto, dict) and bruto.get("status") is False:
            motivo = bruto.get("mensagem") or "SUPRA não retornou dados."
            conteudo = _fallback(cfg.chave, f"SUPRA: {motivo}")
            return TopicoResultado(topico=cfg.chave, ok=True, conteudo=conteudo)

        registros = [r for r in _como_lista(bruto) if isinstance(r, dict)]
        if not registros:
            conteudo = _fallback(cfg.chave, "Nenhum registro retornado pelo endpoint.")
            return TopicoResultado(topico=cfg.chave, ok=True, conteudo=conteudo)

        meta = registros[0]
        nome_arquivo = _texto_meta(meta, "nome_arquivo")
        nome_original = _texto_meta(meta, "nomeOriginalArquivo")
        # Nomes reais: desc_arquivo / ultima_alteracao (os antigos ficam como alternativa).
        descricao = strip_html(_texto_meta(meta, "desc_arquivo", "descricao_arquivo"))
        data_arquivo = _texto_meta(meta, "ultima_alteracao", "data_foto")

        if not nome_arquivo:
            conteudo = _fallback(cfg.chave, "Arquivo de imagem não informado pelo endpoint.")
            return TopicoResultado(topico=cfg.chave, ok=True, conteudo=conteudo)

        # 2. Download da imagem (binário ou base64 — o cliente resolve e gera o base64 no Python)
        try:
            arquivo = await ctx.dnit.download_arquivo(contrato, nome_arquivo)
        except ArquivoInvalido as exc:
            conteudo = _fallback(cfg.chave, f"Falha ao baixar a imagem: {exc}")
            return TopicoResultado(topico=cfg.chave, ok=True, conteudo=conteudo)

        data_uri = arquivo.data_uri

        infos = {
            "nomeArquivo": nome_arquivo,
            "nomeOriginal": nome_original,
            "descricao": descricao,
            "data": data_arquivo,
            "mimeType": arquivo.mime_type,
            "tamanhoBytes": len(arquivo.conteudo),
            "base64": data_uri,
        }

        # 3. Monta mensagem com visão para o gpt-4o
        texto_usuario = (
            f"Analise este arquivo para o período de {periodo_inicio} a {periodo_fim}.\n\n"
            f"Metadados:\n"
            f"- Arquivo: {nome_original or nome_arquivo}\n"
            f"- Última alteração: {data_arquivo or 'não informada'}\n"
            f"- Descrição: \"{descricao or 'sem descrição'}\"\n\n"
            f"Retorne o JSON conforme instruído."
        )
        body = pedir_json({
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
        })

        # 4. Chamada à LLM
        resposta = await ctx.openai.chat(body)

        # 5. Limpa retorno e garante estrutura (mesmas regras do "Limpa Retorno" do n8n)
        conteudo = _normalizar(cfg.chave, _interpretar_resposta(cfg.chave, resposta), infos)
        return TopicoResultado(topico=cfg.chave, ok=True, conteudo=conteudo)

    except Exception as exc:
        logger.exception("Falha ao processar tópico de imagem '%s'", cfg.chave)
        return TopicoResultado(topico=cfg.chave, ok=False, erro=str(exc))
