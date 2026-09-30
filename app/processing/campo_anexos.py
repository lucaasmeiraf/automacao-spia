"""
Handler da estratégia "campo_anexos": texto da seção + conteúdo extraído (ETL) dos anexos.

Primeiro uso: Resumo do Projeto. Cada item (Pavimento Novo, Pavimento Existente, OAEs) é um registro da
seção; os de pavimento trazem um anexo (planilha/PDF) identificado por `id_arquivo`. O texto e os anexos
vão juntos à LLM para o cruzamento de dados. Desenho completo: docs/architecture.md §4
"Anexos lidos por ETL".

Mensagem enviada (o prompt do tópico espera o bloco "ANEXOS"; sem anexo, o bloco não existe):

    <texto da seção>

    ANEXOS
    [Anexo 1] Projeto Pavimento 493.xlsx
    <conteúdo extraído>
    [Fim do anexo 1]

Enquanto a SUPRA não devolver `id_arquivo` na seção, nenhum registro tem anexo e o resultado é o mesmo
da estratégia "campo" — com uma diferença: com vários registros, os textos de todos são usados.
"""
from __future__ import annotations

import asyncio
import logging

from app.clients.dnit import ArquivoInvalido
from app.models import TopicoResultado
from app.processing.context import ProcessingContext
from app.processing.extracao import FormatoNaoSuportado, extrair_texto
from app.processing.llm_resposta import interpretar_resposta, pedir_json
from app.processing.records import limpar_registro
from app.topics import TopicConfig

logger = logging.getLogger(__name__)


def _como_lista(resultado) -> list[dict]:
    if isinstance(resultado, list):
        return [r for r in resultado if isinstance(r, dict)]
    if isinstance(resultado, dict) and "resultado" in resultado:
        r = resultado["resultado"]
        return _como_lista(r if isinstance(r, list) else [r])
    return [resultado] if isinstance(resultado, dict) else []


def _valor(registro: dict, campo: str) -> str:
    """Texto do campo; a SUPRA manda "None"/"null" (texto) quando está vazio."""
    valor = registro.get(campo)
    if valor is None:
        return ""
    texto = str(valor).strip()
    return "" if texto.lower() in ("none", "null") else texto


def _textos(cfg: TopicConfig, registros: list[dict]) -> str:
    """Campo de conteúdo de cada registro (limpo como na estratégia "campo"), sem repetir textos iguais."""
    vistos: list[str] = []
    for registro in registros:
        texto = _valor(limpar_registro(registro, (), cfg.html_fields), cfg.campo_conteudo)
        if texto and texto not in vistos:
            vistos.append(texto)
    return "\n\n".join(vistos)


def _referencias(registros: list[dict]) -> list[dict]:
    """Um anexo por arquivo distinto (`nome_arquivo` e/ou `id_arquivo`), na ordem dos registros."""
    anexos: list[dict] = []
    vistos: set[str] = set()
    for registro in registros:
        nome_arquivo = _valor(registro, "nome_arquivo")
        id_arquivo = _valor(registro, "id_arquivo")
        chave = id_arquivo or nome_arquivo
        if not chave or chave in vistos:
            continue
        vistos.add(chave)
        anexos.append({
            "id_arquivo": id_arquivo,
            "nome_arquivo": nome_arquivo,
            "nome": _valor(registro, "nomeOriginalArquivo"),
        })
    return anexos


async def _ler_anexo(ctx: ProcessingContext, contrato: str, ref: dict) -> dict:
    """Baixa e extrai um anexo. Falha do arquivo vira `erro` (o tópico segue); SUPRA fora do ar propaga."""
    anexo = {**ref, "formato": "", "caracteres": 0, "truncado": False, "aviso": "", "erro": "", "conteudo": ""}
    try:
        arquivo = await ctx.dnit.baixar_anexo(
            contrato, nome_arquivo=ref["nome_arquivo"], id_arquivo=ref["id_arquivo"]
        )
        anexo["nome"] = anexo["nome"] or arquivo.nome
        extraido = await asyncio.to_thread(extrair_texto, arquivo.conteudo, arquivo.nome, arquivo.mime_type)
    except (ArquivoInvalido, FormatoNaoSuportado) as exc:
        logger.warning("Anexo %s não lido: %s", ref["id_arquivo"] or ref["nome_arquivo"], exc)
        anexo["erro"] = str(exc)
        return anexo
    anexo.update(
        formato=extraido.formato,
        caracteres=len(extraido.texto),
        truncado=extraido.truncado,
        aviso=extraido.aviso,
        conteudo=extraido.texto,
    )
    return anexo


def _rotulo(anexo: dict) -> str:
    return anexo["nome"] or anexo["nome_arquivo"] or f"arquivo {anexo['id_arquivo']}"


def _montar_user_content(texto: str, anexos: list[dict]) -> str:
    if not anexos:
        return texto
    blocos = []
    for n, anexo in enumerate(anexos, start=1):
        cabecalho = f"[Anexo {n}] {_rotulo(anexo)}"
        if anexo["erro"] or not anexo["conteudo"]:
            motivo = anexo["erro"] or anexo["aviso"] or "sem conteúdo"
            blocos.append(f"{cabecalho}\nNão foi possível ler o conteúdo deste anexo ({motivo}).")
            continue
        corpo = anexo["conteudo"]
        if anexo["truncado"]:
            corpo += "\n(conteúdo truncado: o anexo é maior que o limite de leitura)"
        blocos.append(f"{cabecalho}\n{corpo}\n[Fim do anexo {n}]")
    return f"{texto}\n\nANEXOS\n" + "\n\n".join(blocos)


async def processar_campo_anexos(
    cfg: TopicConfig,
    prompt_sistema: str,
    contrato: str,
    periodo_inicio: str,
    periodo_fim: str,
    ctx: ProcessingContext,
) -> TopicoResultado:
    """Fluxo: fetch seção → download + ETL de cada anexo → LLM com texto + bloco ANEXOS."""
    try:
        bruto = await ctx.dnit.buscar_secao(cfg.endpoint, contrato, periodo_inicio, periodo_fim)
        registros = _como_lista(bruto)
        texto = _textos(cfg, registros)

        # Em sequência: são poucos arquivos por seção e a SUPRA derruba rajadas de chamadas.
        anexos = [await _ler_anexo(ctx, contrato, ref) for ref in _referencias(registros)]

        user_content = _montar_user_content(texto, anexos)
        body = pedir_json({
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "messages": [
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": user_content},
            ],
        })
        resposta = await ctx.openai.chat(body)

        conteudo = interpretar_resposta(resposta, cfg.nome)
        conteudo["infos"] = {"texto": texto, "anexos": anexos}
        return TopicoResultado(topico=cfg.chave, ok=True, conteudo=conteudo)

    except Exception as exc:
        logger.exception("Falha ao processar tópico com anexos '%s'", cfg.chave)
        return TopicoResultado(topico=cfg.chave, ok=False, erro=str(exc))
