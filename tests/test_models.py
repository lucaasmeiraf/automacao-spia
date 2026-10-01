"""
Validação da entrada (`RelatorioRequest`), usada pelo webhook e pelo `POST /api/executar`.

Caso real (2026-10-01): a tela enviou "20226-07-01" (ano com 5 dígitos, aceito pelo campo de data do
navegador); a SUPRA recusou e o Resumo do Projeto saiu "não preenchido".
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import RelatorioRequest


def _req(inicio="2026-07-01", fim="2026-07-31"):
    return RelatorioRequest(contrato="00 00139/2014", periodo_inicio=inicio, periodo_fim=fim)


def test_datas_validas():
    r = _req(" 2026-07-01 ", "2026-07-31")
    assert (r.periodo_inicio, r.periodo_fim) == ("2026-07-01", "2026-07-31")


def test_mesmo_dia_e_aceito():
    assert _req("2026-07-01", "2026-07-01").periodo_fim == "2026-07-01"


@pytest.mark.parametrize("data", ["20226-07-01", "2026-7-1", "01/07/2026", "2026-02-30", "2026-13-01", "abc"])
def test_data_invalida_e_recusada(data):
    with pytest.raises(ValidationError, match="AAAA-MM-DD"):
        _req(inicio=data)
    with pytest.raises(ValidationError, match="AAAA-MM-DD"):
        _req(fim=data)


def test_inicio_depois_do_fim_e_recusado():
    with pytest.raises(ValidationError, match="anterior ou igual"):
        _req("2026-08-01", "2026-07-31")
