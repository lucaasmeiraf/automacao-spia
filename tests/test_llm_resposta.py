"""Testes da interpretação de respostas da LLM (`app/processing/llm_resposta.py`)."""
from __future__ import annotations

import pytest

from app.processing.llm_resposta import (
    MOTIVO_ERRO_PARSE,
    campo_por_regex,
    extrair_json,
    interpretar_resposta,
    pedir_json,
)


@pytest.mark.parametrize("texto", [
    '{"conforme": "Conforme"}',
    '```json\n{"conforme": "Conforme"}\n```',
    '```\n{"conforme": "Conforme"}\n```',
    'Segue a análise:\n{"conforme": "Conforme"}\nQualquer dúvida, estou à disposição.',
    '```JSON {"conforme": "Conforme"} ```',
])
def test_extrai_json_em_varios_formatos(texto):
    assert extrair_json(texto) == {"conforme": "Conforme"}


def test_extrai_lista():
    assert extrair_json('Resultado: [{"a": 1}]') == [{"a": 1}]


@pytest.mark.parametrize("texto", [None, "", "sem json aqui", '{"conforme": "Conf'])
def test_sem_json_valido_devolve_none(texto):
    assert extrair_json(texto) is None


def test_regex_desfaz_escapes():
    texto = '{"motivo": "Linha 1\\nLinha \\"2\\" com \\u00e7", "conforme": "Aten'
    assert campo_por_regex(texto, "motivo") == 'Linha 1\nLinha "2" com ç'
    assert campo_por_regex(texto, "conforme") == ""


def test_objeto_mantem_tudo_e_so_completa_identificador():
    r = interpretar_resposta('{"conforme": "Conforme", "extra": [1, 2]}', "OAEs")
    assert r == {"conforme": "Conforme", "extra": [1, 2], "identificador": "OAEs"}


def test_identificador_da_ia_e_respeitado():
    r = interpretar_resposta('{"identificador": "Dados Contratuais - Supervisora"}', "Informações Contratuais")
    assert r["identificador"] == "Dados Contratuais - Supervisora"


def test_lista_vai_para_resultado():
    r = interpretar_resposta('[{"item": 1}]', "RPFO")
    assert r == {"identificador": "RPFO", "resultado": [{"item": 1}]}


def test_json_truncado_recupera_campos():
    truncado = '{"conforme": "Não Conforme", "motivo": "Falta ART", "status_texto": "Irregular", "checklist": {'
    r = interpretar_resposta(truncado, "Pluviométrico", campos_extras=("status_texto", "ausente"))
    assert r["conforme"] == "Não Conforme"
    assert r["motivo"] == "Falta ART"
    assert r["status_texto"] == "Irregular"
    assert "ausente" not in r
    assert r["erro_parse"] is True
    assert r["resposta_ia"] == truncado


def test_texto_puro_vira_atencao():
    r = interpretar_resposta("Não consegui analisar.", "Histórico")
    assert r["identificador"] == "Histórico"
    assert r["conforme"] == "Atenção"
    assert r["motivo"] == MOTIVO_ERRO_PARSE


def test_pedir_json_olha_texto_e_partes_de_imagem():
    com = {"messages": [{"role": "user", "content": [{"type": "image_url"}, {"type": "text", "text": "retorne o JSON"}]}]}
    sem = {"messages": [{"role": "system", "content": "Responda em texto corrido."}]}
    assert pedir_json(com)["response_format"] == {"type": "json_object"}
    assert "response_format" not in pedir_json(sem)
