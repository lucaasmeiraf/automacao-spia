"""
Prompts de sistema por tópico, guardados em arquivos versionados: `prompts/<chave>.md`.

Precedência (quem manda no texto do prompt):
  1. o prompt enviado no payload da requisição (`prompts[]`), se vier;
  2. o arquivo `prompts/<chave>.md`.

Segurança: a chave só é aceita se for um tópico conhecido (`TOPICS`). Isso impede que um valor
como "../../.env" vire caminho de arquivo. Como defesa extra, o caminho resolvido precisa
ficar dentro do diretório de prompts.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.arquivos import escrever_atomico
from app.topics import TOPICS

logger = logging.getLogger(__name__)

# Limite de tamanho de um prompt salvo pela API (os atuais têm poucos KB).
PROMPT_MAX_CARACTERES = 50_000


def _caminho_prompt(chave: str, diretorio: str) -> Path | None:
    """Caminho de `prompts/<chave>.md`, ou None se a chave não for um tópico conhecido."""
    if chave not in TOPICS:
        return None

    base = Path(diretorio).resolve()
    arquivo = (base / f"{chave}.md").resolve()
    if base not in arquivo.parents:
        logger.error("Prompt fora do diretório permitido: %s", chave)
        return None
    return arquivo


def _ler_prompt_sync(chave: str, diretorio: str) -> str | None:
    arquivo = _caminho_prompt(chave, diretorio)
    if arquivo is None:
        return None

    try:
        texto = arquivo.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        logger.error("Não foi possível ler o prompt de '%s': %s", chave, exc)
        return None

    return texto or None


async def carregar_prompt(chave: str, diretorio: str) -> str | None:
    """Devolve o texto de `prompts/<chave>.md`, ou None se não existir/estiver vazio."""
    return await asyncio.to_thread(_ler_prompt_sync, chave, diretorio)


def _salvar_prompt_sync(chave: str, diretorio: str, texto: str) -> None:
    arquivo = _caminho_prompt(chave, diretorio)
    if arquivo is None:
        raise ValueError("tópico desconhecido")
    texto = texto.replace("\r\n", "\n").strip()
    if not texto:
        raise ValueError("prompt vazio")
    if len(texto) > PROMPT_MAX_CARACTERES:
        raise ValueError(f"prompt maior que {PROMPT_MAX_CARACTERES} caracteres")
    escrever_atomico(arquivo, texto + "\n")


async def salvar_prompt(chave: str, diretorio: str, texto: str) -> None:
    """Grava `prompts/<chave>.md` de forma atômica. Só aceita chaves de TOPICS."""
    await asyncio.to_thread(_salvar_prompt_sync, chave, diretorio, texto)


def _excluir_prompt_sync(chave: str, diretorio: str) -> bool:
    arquivo = _caminho_prompt(chave, diretorio)
    if arquivo is None:
        raise ValueError("tópico desconhecido")
    try:
        arquivo.unlink()
    except FileNotFoundError:
        return False
    return True


async def excluir_prompt(chave: str, diretorio: str) -> bool:
    """Apaga `prompts/<chave>.md`. Devolve False se não havia arquivo. Só aceita chaves de TOPICS."""
    return await asyncio.to_thread(_excluir_prompt_sync, chave, diretorio)
