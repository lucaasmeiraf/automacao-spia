"""
Hash e verificação de senhas com Argon2id (biblioteca `argon2-cffi`).

- O hash guarda algoritmo, parâmetros e sal: basta armazenar a string inteira.
- A verificação é CPU-intensiva de propósito (dificulta força bruta) — por isso, dentro de
  rotas async, chame via `asyncio.to_thread` (ver `verificar_async`).
- Para usuário inexistente verificamos contra um hash fictício, para que o tempo de resposta
  não revele se o usuário existe.
"""
from __future__ import annotations

import asyncio
from functools import lru_cache

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()  # padrões atuais do argon2-cffi (Argon2id)


def gerar_hash(senha: str) -> str:
    return _hasher.hash(senha)


def verificar(hash_armazenado: str, senha: str) -> bool:
    """True só se a senha confere. Qualquer hash inválido/corrompido => False."""
    try:
        return _hasher.verify(hash_armazenado, senha)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


@lru_cache
def hash_ficticio() -> str:
    """Hash de uma senha aleatória descartada, usado para igualar o tempo quando o usuário não existe."""
    return _hasher.hash("descartavel-" + "x" * 24)


async def verificar_async(hash_armazenado: str | None, senha: str) -> bool:
    """
    Verifica sem bloquear o event loop. Se `hash_armazenado` for None (usuário inexistente),
    gasta o mesmo trabalho contra o hash fictício e devolve False.
    """
    if hash_armazenado is None:
        await asyncio.to_thread(verificar, hash_ficticio(), senha)
        return False
    return await asyncio.to_thread(verificar, hash_armazenado, senha)
