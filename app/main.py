"""
Aplicação FastAPI — ponto de entrada (fábrica `create_app`).

Substitui o nó "Webhook" (+ "If" + "Separa Prompts" + "Respond to Webhook").
Recebe o POST, valida e delega a `app/processing/execucao.py`, que seleciona os tópicos
(`processing/selecao.py`: definidos em `app/topics.py`, ligados em `config/topics.yaml`, com
prompt do payload ou de `prompts/<chave>.md`) e os executa em paralelo. O botão "Executar" da
tela de dev (`POST /api/executar`, `app/routers/admin.py`) usa a mesma execução.

Segurança (docs/architecture.md §10.10):
  - o webhook exige a chave `X-API-Key` (WEBHOOK_API_KEY);
  - as rotas de administração só existem com ENV=dev e exigem login (sessão + CSRF);
  - /docs, /redoc e /openapi.json ficam desligados (só ligáveis em dev);
  - toda resposta leva cabeçalhos de segurança; erros de validação não devolvem o valor enviado.

Execução:  uvicorn app.main:create_app --factory
"""
from __future__ import annotations

import logging
import ssl
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.clients.dnit import DnitClient
from app.clients.nominatim import NominatimClient
from app.clients.openai_client import OpenAIClient
from app.clients.openmeteo import OpenMeteoClient
from app.config import Settings, get_settings
from app.log_buffer import BufferDeLogs, em_execucao
from app.logging_config import setup_logging
from app.models import RelatorioRequest, RelatorioResponse
from app.processing.context import ProcessingContext
from app.processing.execucao import (
    MSG_CONFIG_INDISPONIVEL,
    ConfiguracaoIndisponivel,
    executar_relatorio,
)
from app.routers import admin as admin_router
from app.routers import auth as auth_router
from app.security.deps import exigir_chave_webhook
from app.security.headers import aplicar_cabecalhos
from app.security.sessions import SessionStore
from app.security.throttle import Limitador

logger = logging.getLogger(__name__)


def _avisos_de_seguranca(settings: Settings) -> None:
    """Problemas de configuração que merecem aparecer já na inicialização."""
    if not settings.webhook_api_key:
        logger.error(
            "WEBHOOK_API_KEY não configurada: POST /webhook/relatorio responderá 503 "
            "até que uma chave seja definida no .env."
        )
    if settings.env == "dev" and not settings.admin_users:
        logger.warning("ENV=dev sem ADMIN_USERS: ninguém conseguirá fazer login na administração.")
    if settings.env != "dev" and not settings.cookie_secure:
        logger.warning(
            "COOKIE_SECURE=false fora de dev: cookies de sessão trafegariam sem TLS. Use HTTPS."
        )
    if settings.enable_docs and settings.env != "dev":
        logger.warning("ENABLE_DOCS ignorado: a documentação interativa só existe com ENV=dev.")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    docs_ligados = settings.env == "dev" and settings.enable_docs

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        setup_logging(settings.log_level)
        if app.state.logs is not None:
            logging.getLogger().addHandler(app.state.logs)
        _avisos_de_seguranca(settings)
        # Um único AsyncClient reaproveitado por toda a aplicação (connection pooling).
        # TLS verificado contra o repositório de certificados do SISTEMA (não o do certifi): a rede do
        # DNIT inspeciona HTTPS e reassina sites externos (ex.: api.openai.com) com a CA interna
        # "DNIT_SubCA_SSL", que o Windows conhece e o certifi não. Continua verificando tudo.
        # (o `verify` vai no transport: com `transport=` o httpx ignora o `verify` do client.)
        async with httpx.AsyncClient(
            timeout=settings.http_timeout,
            transport=httpx.AsyncHTTPTransport(
                retries=settings.http_max_retries,
                verify=ssl.create_default_context(),
            ),
        ) as client:
            app.state.dnit = DnitClient(settings, client)
            app.state.openai = OpenAIClient(settings, client)
            app.state.openmeteo = OpenMeteoClient(settings, client)
            app.state.nominatim = NominatimClient(settings, client)
            logger.info("Supra IA iniciada (ENV=%s).", settings.env)
            yield
        logger.info("Supra IA finalizada.")
        if app.state.logs is not None:
            logging.getLogger().removeHandler(app.state.logs)

    app = FastAPI(
        title="Supra IA",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if docs_ligados else None,
        redoc_url=None,
        openapi_url="/openapi.json" if docs_ligados else None,
    )

    # Estado compartilhado de segurança (memória do processo).
    app.state.settings = settings
    app.state.sessoes = SessionStore(
        inatividade_seg=settings.session_idle_minutes * 60,
        duracao_max_seg=settings.session_max_hours * 3600,
    )
    app.state.limitador = Limitador()
    # Painel de logs da tela de dev: só existe em dev (instalado no logger raiz pelo lifespan).
    app.state.logs = BufferDeLogs() if settings.env == "dev" else None

    @app.middleware("http")
    async def _cabecalhos_de_seguranca(request: Request, call_next):
        response = await call_next(request)
        aplicar_cabecalhos(response, request.url.path)
        return response

    @app.exception_handler(RequestValidationError)
    async def _validacao(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # O handler padrão devolve o campo `input` (o valor enviado) — numa tela de login isso
        # devolveria a senha digitada. Aqui só vão localização e mensagem.
        erros = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": erros})

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Checagem simples de saúde (útil para Docker/monitoramento)."""
        return {"status": "ok"}

    @app.post(
        "/webhook/relatorio",
        response_model=RelatorioResponse,
        dependencies=[Depends(exigir_chave_webhook)],
    )
    async def gerar_relatorio(req: RelatorioRequest, request: Request) -> RelatorioResponse:
        """
        Endpoint principal (exige `X-API-Key`). A validação de contrato/período é feita pelo
        modelo Pydantic (equivale ao nó 'If'); se algo faltar, devolve 422 sem entrar aqui.
        """
        st = request.app.state
        # Seleção (o "fio" do n8n) + execução paralela: app/processing/execucao.py.
        # Falha segura: configuração inválida => nada roda; o detalhe fica só no log.
        with em_execucao():
            try:
                return await executar_relatorio(req, ProcessingContext.da_app(st), st.settings)
            except ConfiguracaoIndisponivel:
                raise HTTPException(status_code=503, detail=MSG_CONFIG_INDISPONIVEL) from None

    # Rotas de administração: só existem em dev. Em homolog/prod => 404 (não revelam que existem).
    if settings.env == "dev":
        app.include_router(auth_router.router)
        app.include_router(admin_router.router)

    return app
