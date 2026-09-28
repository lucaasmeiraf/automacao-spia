"""
Telas (HTML + CSS + JS puro, sem build) servidas pelo próprio FastAPI — fase 3 (§10.6).

  GET /             → redireciona para /ui/config
  GET /ui/config    → tela de configuração
  /ui/static/...    → CSS/JS (montado em `create_app` com StaticFiles)

Só é registrado com ENV=dev (ver `create_app`). A página em si é pública (é só o "casco", sem
dados nem segredos): ela mostra o login e tudo o que carrega passa pela API, que exige a sessão de
admin. A autorização continua sendo 100% do servidor — esconder a tela não é proteção.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, RedirectResponse

UI_DIR = Path(__file__).resolve().parent.parent / "ui"
STATIC_DIR = UI_DIR / "static"

router = APIRouter(include_in_schema=False)


@router.get("/")
async def raiz() -> RedirectResponse:
    return RedirectResponse("/ui/config", status_code=307)


@router.get("/ui/config")
async def tela_configuracao() -> FileResponse:
    return FileResponse(UI_DIR / "config.html", media_type="text/html; charset=utf-8")
