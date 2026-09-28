"""
Dependências do FastAPI para autenticação e autorização.

  - `exigir_chave_webhook`: protege o POST /webhook/relatorio (chave do sistema chamador);
  - `exigir_admin`: exige sessão válida de administrador. Em métodos que alteram estado
    (POST/PUT/PATCH/DELETE) exige TAMBÉM o token CSRF — assim é impossível "esquecer" o CSRF
    numa rota nova de configuração: basta usar `Depends(exigir_admin)`.

Erros sempre genéricos: nunca dizem POR QUE falhou (não ajudam quem está tentando invadir).
"""
from __future__ import annotations

import hmac
import logging

from fastapi import Depends, HTTPException, Request

from app.security.sessions import Sessao

logger = logging.getLogger(__name__)

METODOS_SEGUROS = frozenset({"GET", "HEAD", "OPTIONS"})


def ip_do_cliente(request: Request) -> str:
    return request.client.host if request.client else "desconhecido"


def nome_cookie(cookie_secure: bool) -> str:
    # O prefixo __Host- só é aceito pelo navegador com Secure; sem Secure usamos nome simples.
    return "__Host-supra_sessao" if cookie_secure else "supra_sessao"


def _iguais(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


async def exigir_chave_webhook(request: Request) -> None:
    settings = request.app.state.settings
    esperada = settings.webhook_api_key
    if not esperada:
        # Falha fechada: sem chave configurada, o webhook não responde a ninguém.
        logger.error("WEBHOOK_API_KEY não configurada: webhook indisponível.")
        raise HTTPException(status_code=503, detail="Serviço indisponível.")

    ip = ip_do_cliente(request)
    limitador = request.app.state.limitador
    chave_lim = f"webhook:{ip}"
    espera = limitador.espera(chave_lim)
    if espera:
        raise HTTPException(
            status_code=429, detail="Muitas tentativas.", headers={"Retry-After": str(espera)}
        )

    recebida = request.headers.get("x-api-key")
    if not recebida or not _iguais(recebida, esperada):
        limitador.falha(chave_lim)
        logger.warning("Webhook: chave de API ausente/inválida (ip=%s).", ip)
        raise HTTPException(status_code=401, detail="Não autorizado.")

    limitador.sucesso(chave_lim)


async def exigir_admin(request: Request) -> Sessao:
    settings = request.app.state.settings
    token = request.cookies.get(nome_cookie(settings.cookie_secure))
    sessao = request.app.state.sessoes.obter(token)
    if sessao is None:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    if sessao.perfil != "admin":
        raise HTTPException(status_code=403, detail="Acesso negado.")

    if request.method not in METODOS_SEGUROS:
        enviado = request.headers.get("x-csrf-token")
        if not enviado or not _iguais(enviado, sessao.csrf):
            logger.warning("CSRF inválido/ausente (usuario=%r).", sessao.usuario[:64])
            raise HTTPException(status_code=403, detail="Acesso negado.")

    return sessao


AdminDep = Depends(exigir_admin)
