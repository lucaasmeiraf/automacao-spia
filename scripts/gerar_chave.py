"""
Gera uma chave aleatória forte para WEBHOOK_API_KEY.

Uso (na raiz do projeto):
    python -m scripts.gerar_chave

A chave é impressa UMA vez; copie para o .env e para o sistema que chama o webhook
(header `X-API-Key`). Para trocar a chave, gere outra e atualize os dois lados.
"""
from __future__ import annotations

import secrets


def main() -> int:
    print(f"WEBHOOK_API_KEY={secrets.token_urlsafe(48)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
