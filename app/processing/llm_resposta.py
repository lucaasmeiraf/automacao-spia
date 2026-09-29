"""
Interpretação da resposta da LLM — um único lugar para todos os tópicos.

Equivale aos nós "Limpa Retorno …" do n8n (17 de 20 removiam ```json e recuperavam campos por regex),
com melhorias:
  - além de remover a cerca ```json, recorta o JSON do meio de um texto ("Segue a análise: {...}");
  - JSON quebrado/truncado: recupera `conforme`, `motivo` e os campos pedidos, campo a campo;
  - o resultado é SEMPRE um objeto com `identificador`, `conforme` e `motivo` (nunca texto solto),
    para quem consome a resposta não precisar tratar dois formatos;
  - `pedir_json()` liga o modo JSON da OpenAI quando o prompt pede JSON: a resposta vem como JSON
    válido na origem (menos falhas de parse, sem cercas markdown).
"""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable

logger = logging.getLogger(__name__)

_CERCA_RE = re.compile(r"```(?:json)?", re.IGNORECASE)

CONFORME_PADRAO = "Atenção"
MOTIVO_ERRO_PARSE = "Erro ao interpretar resposta da IA."


def pedir_json(body: dict) -> dict:
    """
    Liga `response_format: json_object` quando as mensagens mencionam JSON — exigência da OpenAI
    (sem a palavra "JSON" nas mensagens a API recusa o modo). Prompt que não pede JSON fica como está.
    """
    textos = []
    for msg in body.get("messages", []):
        conteudo = msg.get("content")
        if isinstance(conteudo, str):
            textos.append(conteudo)
        elif isinstance(conteudo, list):
            textos.extend(p.get("text", "") for p in conteudo if isinstance(p, dict))
    if any("json" in t.lower() for t in textos):
        body["response_format"] = {"type": "json_object"}
    return body


def extrair_json(texto: str | None) -> dict | list | None:
    """JSON contido na resposta (com ou sem ```json, com ou sem texto em volta), ou None."""
    limpo = _CERCA_RE.sub("", texto or "").strip()
    if not limpo:
        return None
    try:
        return json.loads(limpo)
    except json.JSONDecodeError:
        pass
    # Texto antes/depois do JSON: recorta do primeiro "{"/"[" ao último "}"/"]", começando pelo
    # delimitador que aparece primeiro (senão "[{...}]" viraria só o objeto de dentro).
    pares = sorted((("{", "}"), ("[", "]")), key=lambda p: (limpo.find(p[0]) < 0, limpo.find(p[0])))
    for abre, fecha in pares:
        ini, fim = limpo.find(abre), limpo.rfind(fecha)
        if 0 <= ini < fim:
            try:
                return json.loads(limpo[ini:fim + 1])
            except json.JSONDecodeError:
                continue
    return None


def campo_por_regex(texto: str | None, campo: str) -> str:
    """Valor texto de `"campo": "..."` num JSON quebrado (como o getField do n8n)."""
    m = re.search(rf'"{re.escape(campo)}"\s*:\s*"((?:[^"\\]|\\.)*)"', texto or "", re.DOTALL)
    if not m:
        return ""
    try:
        return json.loads(f'"{m.group(1)}"')  # desfaz escapes (\n, \", ç…)
    except json.JSONDecodeError:
        return m.group(1)


def interpretar_resposta(
    texto: str | None, identificador: str, campos_extras: Iterable[str] = ()
) -> dict:
    """
    Resposta da LLM → objeto com, no mínimo, `identificador`, `conforme` e `motivo`.

    - JSON objeto: mantido inteiro; `identificador` só é preenchido se a IA não mandou.
    - JSON lista: vai para `resultado`.
    - Sem JSON válido: recupera `conforme`, `motivo` e `campos_extras` por regex e marca `erro_parse`.
    """
    dados = extrair_json(texto)
    if isinstance(dados, dict):
        dados.setdefault("identificador", identificador)
        return dados
    if isinstance(dados, list):
        return {"identificador": identificador, "resultado": dados}

    logger.warning("Resposta da IA para '%s' não é JSON válido; recuperando campos por regex.", identificador)
    recuperado = {
        "identificador": identificador,
        "conforme": campo_por_regex(texto, "conforme") or CONFORME_PADRAO,
        "motivo": campo_por_regex(texto, "motivo") or MOTIVO_ERRO_PARSE,
        "erro_parse": True,
        "resposta_ia": (texto or "")[:4000],
    }
    for campo in campos_extras:
        valor = campo_por_regex(texto, campo)
        if valor:
            recuperado[campo] = valor
    return recuperado
