"""
Sessões no servidor (em memória).

O cookie carrega só um token opaco e aleatório; o servidor guarda o SHA-256 dele. Assim:
  - logout revoga de verdade (apagar a entrada invalida o token);
  - vazar o estado do servidor não entrega tokens válidos;
  - não há nada assinado/decodificável no cliente.

Cada sessão tem um token CSRF próprio e expira por inatividade e por tempo absoluto.

Limitação assumida: memória do processo. Reiniciar o servidor desloga todo mundo, e a aplicação
deve rodar com UM processo (o Dockerfile já faz isso). É adequado para a ferramenta de
administração; se um dia houver vários processos, troque por SQLite/Redis.
"""
from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class Sessao:
    usuario: str
    csrf: str
    criada_em: float
    ultimo_uso: float
    perfil: str = "admin"


def _chave(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class SessionStore:
    def __init__(
        self,
        inatividade_seg: float,
        duracao_max_seg: float,
        relogio: Callable[[], float] = time.monotonic,
        max_sessoes: int = 200,
    ):
        self._inatividade = inatividade_seg
        self._duracao_max = duracao_max_seg
        self._agora = relogio
        self._max = max_sessoes
        self._sessoes: dict[str, Sessao] = {}

    def _expirada(self, s: Sessao, agora: float) -> bool:
        return (agora - s.ultimo_uso > self._inatividade) or (agora - s.criada_em > self._duracao_max)

    def _limpar(self, agora: float) -> None:
        for k in [k for k, s in self._sessoes.items() if self._expirada(s, agora)]:
            del self._sessoes[k]
        while len(self._sessoes) >= self._max:  # teto: descarta a mais antiga
            mais_antiga = min(self._sessoes, key=lambda k: self._sessoes[k].criada_em)
            del self._sessoes[mais_antiga]

    def criar(self, usuario: str, perfil: str = "admin") -> tuple[str, Sessao]:
        """Devolve (token para o cookie, sessão). O token só existe aqui — não é guardado em claro."""
        agora = self._agora()
        self._limpar(agora)
        token = secrets.token_urlsafe(32)
        sessao = Sessao(
            usuario=usuario,
            csrf=secrets.token_urlsafe(32),
            criada_em=agora,
            ultimo_uso=agora,
            perfil=perfil,
        )
        self._sessoes[_chave(token)] = sessao
        return token, sessao

    def obter(self, token: str | None) -> Sessao | None:
        if not token:
            return None
        chave = _chave(token)
        sessao = self._sessoes.get(chave)
        if sessao is None:
            return None
        agora = self._agora()
        if self._expirada(sessao, agora):
            del self._sessoes[chave]
            return None
        sessao.ultimo_uso = agora  # inatividade deslizante
        return sessao

    def revogar(self, token: str | None) -> None:
        if token:
            self._sessoes.pop(_chave(token), None)
