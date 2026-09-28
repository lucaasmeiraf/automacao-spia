"""
Buffer de logs em memória para o painel de logs da tela de dev (`GET /api/logs`).

É um `logging.Handler` que guarda as últimas N linhas (deque com tamanho máximo: memória
limitada). Cada linha leva o id da execução em curso (`execucao_atual`, um ContextVar), o que
permite filtrar "só os logs desta execução" — o contexto é copiado para as tarefas do
`asyncio.gather` e para `asyncio.to_thread`, então os logs dos handlers também herdam o id.

Só é instalado com ENV=dev (ver `create_app`). Os logs do app já não contêm segredos; exceções
entram só como "Tipo: mensagem" (sem traceback, que exporia caminhos internos).
"""
from __future__ import annotations

import logging
import threading
import uuid
from collections import deque
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Iterator

execucao_atual: ContextVar[str | None] = ContextVar("execucao_atual", default=None)


@contextmanager
def em_execucao() -> Iterator[str]:
    """Marca os logs emitidos dentro do bloco com um id de execução novo (e o devolve)."""
    execucao_id = uuid.uuid4().hex[:12]
    token = execucao_atual.set(execucao_id)
    try:
        yield execucao_id
    finally:
        execucao_atual.reset(token)

_MAX_MENSAGEM = 2000
_MAX_EXCECAO = 500


class BufferDeLogs(logging.Handler):
    def __init__(self, capacidade: int = 1000):
        super().__init__(level=logging.DEBUG)
        self._linhas: deque[dict] = deque(maxlen=capacidade)
        self._seq = 0
        self._trava = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            mensagem = record.getMessage()
        except Exception:  # argumentos de formatação inválidos não podem derrubar o log
            mensagem = str(record.msg)

        linha = {
            "hora": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "nivel": record.levelname,
            "origem": record.name,
            "mensagem": mensagem[:_MAX_MENSAGEM],
            "execucao": execucao_atual.get(),
        }
        if record.exc_info and record.exc_info[1] is not None:
            exc = record.exc_info[1]
            linha["excecao"] = f"{type(exc).__name__}: {exc}"[:_MAX_EXCECAO]

        with self._trava:
            self._seq += 1
            linha["seq"] = self._seq
            self._linhas.append(linha)

    def listar(
        self,
        nivel_minimo: str = "DEBUG",
        execucao: str | None = None,
        apos: int = 0,
        limite: int = 200,
    ) -> list[dict]:
        """Linhas mais recentes (em ordem cronológica), filtradas por nível, execução e `seq`."""
        minimo = logging.getLevelName(nivel_minimo)
        with self._trava:
            linhas = list(self._linhas)
        filtradas = [
            linha for linha in linhas
            if linha["seq"] > apos
            and logging.getLevelName(linha["nivel"]) >= minimo
            and (execucao is None or linha["execucao"] == execucao)
        ]
        return filtradas[-limite:]
