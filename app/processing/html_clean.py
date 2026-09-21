"""
Limpeza de HTML — porta fiel da função `stripHtml` usada nos nós "Payload" do n8n.

Remove tags, converte entidades HTML e normaliza espaços. Mantém a mesma tabela
de entidades do fluxo original para garantir saída idêntica.
"""
from __future__ import annotations

import html
import re

_TAG_RE = re.compile(r"<[^>]*>")
_WS_RE = re.compile(r"\s+")

# Mesma tabela de entidades do stripHtml original (n8n).
_ENTIDADES = {
    "&amp;": "&", "&lt;": "<", "&gt;": ">",
    "&Ccedil;": "Ç", "&ccedil;": "ç",
    "&Atilde;": "Ã", "&atilde;": "ã",
    "&Otilde;": "Õ", "&otilde;": "õ",
    "&eacute;": "é", "&Eacute;": "É",
    "&ecirc;": "ê", "&Ecirc;": "Ê",
    "&oacute;": "ó", "&ocirc;": "ô",
    "&iacute;": "í", "&aacute;": "á",
    "&uacute;": "ú", "&Aacute;": "Á",
    "&Iacute;": "Í", "&Uacute;": "Ú",
    "&ordm;": "º", "&ordf;": "ª",
    "&ndash;": "–", "&mdash;": "—",
    "&bull;": "•", "&sup2;": "²",
    "&sup3;": "³",
    "&Oslash;": "Ø", "&oslash;": "ø",
    "&acirc;": "â", "&Acirc;": "Â",
    "&ucirc;": "û", "&icirc;": "î",
}


def strip_html(value):
    """Remove HTML de uma string. Valores não-string são retornados como estão."""
    if not isinstance(value, str):
        return value

    texto = _TAG_RE.sub(" ", value)
    texto = texto.replace("&nbsp;", " ")

    for entidade, char in _ENTIDADES.items():
        texto = texto.replace(entidade, char)

    # Converte quaisquer entidades restantes (ex.: &#233;) que não estejam na tabela.
    texto = html.unescape(texto)

    return _WS_RE.sub(" ", texto).strip()


def limpar_campos(registro: dict, campos: list[str]) -> dict:
    """Retorna uma cópia do registro com os `campos` indicados limpos de HTML."""
    limpo = dict(registro)
    for campo in campos:
        if campo in limpo:
            limpo[campo] = strip_html(limpo.get(campo) or "")
    return limpo
