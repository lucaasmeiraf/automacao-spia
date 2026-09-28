"""
Gravação atômica de arquivos de texto (usada pela API de configuração).

Escreve num arquivo temporário no MESMO diretório e troca com `os.replace` — que é atômico no
mesmo sistema de arquivos. Quem ler o arquivo durante a gravação vê a versão antiga inteira ou a
nova inteira, nunca um YAML/prompt pela metade.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def escrever_atomico(caminho: str | Path, texto: str) -> None:
    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=destino.parent, prefix=f".{destino.name}.", suffix=".tmp")
    try:
        # newline="\n": o arquivo sai igual em Windows e Linux (evita diffs só de fim de linha).
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(texto)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, destino)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
