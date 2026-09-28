"""
Login, logout e "quem sou eu" do administrador.

Só é registrado quando ENV=dev (ver `create_app`). Credenciais vêm de `ADMIN_USERS` (hashes
argon2 no .env). A resposta do login NÃO diferencia "usuário inexistente" de "senha errada".
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.security.deps import AdminDep, ip_do_cliente, nome_cookie
from app.security.passwords import verificar_async
from app.security.sessions import Sessao

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

_MSG_INVALIDO = "Usuário ou senha inválidos."


class LoginRequest(BaseModel):
    # Limites de tamanho: evitam usar o argon2 (caro) como vetor de negação de serviço.
    usuario: str = Field(min_length=1, max_length=64)
    senha: str = Field(min_length=1, max_length=256)


class SessaoResponse(BaseModel):
    usuario: str
    perfil: str
    csrf_token: str


def _cookie_kwargs(settings) -> dict:
    return dict(
        httponly=True,                 # JavaScript não consegue ler o cookie
        secure=settings.cookie_secure,
        samesite="strict",             # não é enviado em requisições vindas de outros sites
        path="/",
    )


@router.post("/login", response_model=SessaoResponse)
async def login(dados: LoginRequest, request: Request, response: Response) -> SessaoResponse:
    settings = request.app.state.settings
    limitador = request.app.state.limitador
    ip = ip_do_cliente(request)
    usuario = dados.usuario.strip()

    chave_ip = f"login-ip:{ip}"
    chave_par = f"login-par:{ip}:{usuario.lower()}"
    espera = max(limitador.espera(chave_ip), limitador.espera(chave_par))
    if espera:
        raise HTTPException(
            status_code=429,
            detail="Muitas tentativas. Aguarde e tente novamente.",
            headers={"Retry-After": str(espera)},
        )

    hash_armazenado = settings.admin_users.get(usuario)
    ok = await verificar_async(hash_armazenado, dados.senha)

    if not ok:
        limitador.falha(chave_ip)
        limitador.falha(chave_par)
        # %r + corte de tamanho: neutraliza quebra de linha/log injection no campo digitado.
        logger.warning("Login falhou (usuario=%r, ip=%s).", usuario[:64], ip)
        raise HTTPException(status_code=401, detail=_MSG_INVALIDO)

    limitador.sucesso(chave_ip)
    limitador.sucesso(chave_par)
    token, sessao = request.app.state.sessoes.criar(usuario, perfil="admin")
    response.set_cookie(nome_cookie(settings.cookie_secure), token, **_cookie_kwargs(settings))
    logger.info("Login ok (usuario=%r, ip=%s).", usuario[:64], ip)
    return SessaoResponse(usuario=sessao.usuario, perfil=sessao.perfil, csrf_token=sessao.csrf)


@router.get("/me", response_model=SessaoResponse)
async def me(sessao: Sessao = AdminDep) -> SessaoResponse:
    """Usado pelo front ao carregar a página: confirma a sessão e entrega o token CSRF."""
    return SessaoResponse(usuario=sessao.usuario, perfil=sessao.perfil, csrf_token=sessao.csrf)


@router.post("/logout")
async def logout(request: Request, response: Response, sessao: Sessao = AdminDep) -> dict[str, bool]:
    settings = request.app.state.settings
    nome = nome_cookie(settings.cookie_secure)
    request.app.state.sessoes.revogar(request.cookies.get(nome))
    response.delete_cookie(nome, **_cookie_kwargs(settings))
    logger.info("Logout (usuario=%r).", sessao.usuario[:64])
    return {"ok": True}
