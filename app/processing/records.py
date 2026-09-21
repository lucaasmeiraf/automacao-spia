"""
Utilitários para normalização e limpeza de registros da API SUPRA.

Concentra a lógica dos nós "Limpa HTML", "Filtra Campos" e "Sem Dados?"
que se repetiam em múltiplas chains do n8n.
"""
from __future__ import annotations

import re

from app.processing.html_clean import strip_html

_CRLF_RE = re.compile(r"[\r\n]+")


def limpar_registro(
    registro: dict,
    campos_manter: tuple[str, ...] = (),
    html_fields: tuple[str, ...] = (),
) -> dict:
    """
    Filtra colunas, limpa HTML nos campos indicados e remove \\r\\n de strings.
    Ordem: filtro → HTML → \\r\\n.
    """
    if campos_manter:
        resultado = {k: registro.get(k) for k in campos_manter}
    else:
        resultado = dict(registro)

    for campo in html_fields:
        if campo in resultado:
            resultado[campo] = strip_html(resultado.get(campo) or "")

    for key, val in resultado.items():
        if isinstance(val, str):
            resultado[key] = _CRLF_RE.sub(" ", val).strip()

    return resultado


def detectar_vazio(
    registros: list[dict],
    campos_presenca: tuple[str, ...] = (),
) -> bool:
    """
    Retorna True quando não há dados reais na resposta da API.

    Cobre dois padrões do n8n:
      - API retornou {status: false} (endpoint sem dados para o período)
      - Todos os registros não têm nenhum dos `campos_presenca` preenchidos
        (ex.: aditivos sem numero_termo/numero/num_termo)
    """
    if not registros:
        return True
    if registros[0].get("status") is False:
        return True
    if campos_presenca:
        return all(
            not any(r.get(c) for c in campos_presenca)
            for r in registros
        )
    return False
