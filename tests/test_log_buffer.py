"""Testes do buffer de logs em memória (painel de logs da tela de dev)."""
from __future__ import annotations

import logging

import pytest

from app.log_buffer import BufferDeLogs, em_execucao, execucao_atual


@pytest.fixture
def logger_com_buffer():
    buffer = BufferDeLogs(capacidade=5)
    log = logging.getLogger("teste.buffer")
    log.setLevel(logging.DEBUG)
    log.propagate = False
    log.addHandler(buffer)
    yield log, buffer
    log.removeHandler(buffer)
    log.propagate = True


def test_capacidade_limitada_guarda_as_mais_recentes(logger_com_buffer):
    log, buffer = logger_com_buffer
    for i in range(8):
        log.info("linha %d", i)
    linhas = buffer.listar()
    assert [linha["mensagem"] for linha in linhas] == [f"linha {i}" for i in range(3, 8)]


def test_filtro_por_nivel_e_apos(logger_com_buffer):
    log, buffer = logger_com_buffer
    log.debug("d")
    log.info("i")
    log.warning("w")
    assert [linha["mensagem"] for linha in buffer.listar(nivel_minimo="INFO")] == ["i", "w"]
    ultimo_seq = buffer.listar()[-1]["seq"]
    log.error("e")
    assert [linha["mensagem"] for linha in buffer.listar(apos=ultimo_seq)] == ["e"]


def test_id_de_execucao_e_filtro(logger_com_buffer):
    log, buffer = logger_com_buffer
    log.info("fora")
    with em_execucao() as execucao_id:
        log.info("dentro")
    assert execucao_atual.get() is None
    linhas = buffer.listar(execucao=execucao_id)
    assert [linha["mensagem"] for linha in linhas] == ["dentro"]


def test_excecao_entra_sem_traceback(logger_com_buffer):
    log, buffer = logger_com_buffer
    try:
        raise ValueError("falhou")
    except ValueError:
        log.exception("erro no tópico")
    (linha,) = buffer.listar()
    assert linha["excecao"] == "ValueError: falhou"
    assert "Traceback" not in str(linha)
