"""
Limite de tentativas (força bruta), em memória.

Depois de `max_falhas` falhas seguidas numa chave, ela fica bloqueada por um tempo que dobra a
cada nova falha (até `teto_seg`). Acerto zera a chave. Falhas antigas (fora de `janela_seg`)
são esquecidas.

As chaves são montadas por quem chama. O login usa duas: só o IP e o par IP+usuário — assim
um atacante não consegue trancar o admin a partir de OUTRO IP (o par inclui o IP dele).
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class _Estado:
    falhas: int = 0
    ultima_falha: float = 0.0
    bloqueado_ate: float = 0.0


class Limitador:
    def __init__(
        self,
        max_falhas: int = 5,
        base_seg: float = 5.0,
        teto_seg: float = 900.0,
        janela_seg: float = 900.0,
        relogio: Callable[[], float] = time.monotonic,
        max_chaves: int = 10_000,
    ):
        self._max_falhas = max_falhas
        self._base = base_seg
        self._teto = teto_seg
        self._janela = janela_seg
        self._agora = relogio
        self._max_chaves = max_chaves
        self._estados: dict[str, _Estado] = {}

    def espera(self, chave: str) -> int:
        """Segundos até poder tentar de novo (0 = liberado)."""
        estado = self._estados.get(chave)
        if estado is None:
            return 0
        restante = estado.bloqueado_ate - self._agora()
        return math.ceil(restante) if restante > 0 else 0

    def falha(self, chave: str) -> None:
        agora = self._agora()
        if len(self._estados) >= self._max_chaves:
            self._podar(agora)
        estado = self._estados.setdefault(chave, _Estado())
        if agora - estado.ultima_falha > self._janela:
            estado.falhas = 0
        estado.falhas += 1
        estado.ultima_falha = agora
        if estado.falhas >= self._max_falhas:
            atraso = min(self._base * (2 ** (estado.falhas - self._max_falhas)), self._teto)
            estado.bloqueado_ate = agora + atraso

    def sucesso(self, chave: str) -> None:
        self._estados.pop(chave, None)

    def _podar(self, agora: float) -> None:
        for k in [
            k for k, e in self._estados.items()
            if agora - e.ultima_falha > self._janela and e.bloqueado_ate < agora
        ]:
            del self._estados[k]
