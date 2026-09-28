"""
Gera a linha ADMIN_USERS do .env com o hash Argon2id das senhas dos administradores.

Uso (na raiz do projeto):
    python -m scripts.gerar_hash_senha lucas.meira
    python -m scripts.gerar_hash_senha lucas.meira outro.admin      # vários admins

A senha é digitada de forma oculta (não aparece na tela nem fica no histórico do terminal).
Copie a linha impressa para o `.env`. NUNCA coloque a senha em texto puro no .env.
"""
from __future__ import annotations

import getpass
import json
import sys

from app.security.passwords import gerar_hash

MIN_SENHA = 12


def _pedir_senha(usuario: str) -> str:
    while True:
        s1 = getpass.getpass(f"Senha para '{usuario}' (mín. {MIN_SENHA} caracteres): ")
        if len(s1) < MIN_SENHA:
            print(f"  Muito curta: use pelo menos {MIN_SENHA} caracteres.")
            continue
        s2 = getpass.getpass("  Repita a senha: ")
        if s1 != s2:
            print("  As senhas não conferem. Tente de novo.")
            continue
        return s1


def main(argv: list[str]) -> int:
    usuarios = [u.strip() for u in argv if u.strip()]
    if not usuarios:
        print(__doc__)
        return 1
    if len(set(usuarios)) != len(usuarios):
        print("Nomes de usuário repetidos.")
        return 1

    admins = {u: gerar_hash(_pedir_senha(u)) for u in usuarios}

    # Aspas simples: o hash contém '$', e assim nem o Docker Compose nem o dotenv o "expandem".
    print("\nCopie a linha abaixo para o seu .env (substitui a ADMIN_USERS existente):\n")
    print(f"ADMIN_USERS='{json.dumps(admins, ensure_ascii=False)}'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
