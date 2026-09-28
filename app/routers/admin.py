"""
API de configuração (fase 2b — docs/architecture.md §10.5). A tela de dev é só um cliente dela.

  GET  /api/topicos            lista os tópicos com estado (ativo) e metadados
  PUT  /api/topicos            liga/desliga tópicos: {"topicos": {chave: true|false}}
  GET  /api/prompts            todos os prompts (prompts/<chave>.md)
  GET  /api/prompts/{chave}    um prompt
  PUT  /api/prompts/{chave}    salva um prompt: {"conteudo": "..."}
  POST /api/executar           o botão "Executar" (mesma execução do webhook; `dry_run`, `topicos`)
  GET  /api/logs               últimas linhas de log (buffer em memória)

Só é registrado com ENV=dev (ver `create_app`). A autorização vale para o router INTEIRO
(`dependencies=[AdminDep]`): sessão de admin em tudo e CSRF nas escritas — uma rota nova aqui
não tem como nascer aberta. Toda alteração é logada com o usuário.
"""
from __future__ import annotations

import logging
import time
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field, StrictBool, field_validator

from app.log_buffer import em_execucao
from app.models import RelatorioRequest, RelatorioResponse
from app.processing.context import ProcessingContext
from app.processing.execucao import (
    MSG_CONFIG_INDISPONIVEL,
    ConfiguracaoIndisponivel,
    executar_relatorio,
)
from app.prompts_store import PROMPT_MAX_CARACTERES, carregar_prompt, salvar_prompt
from app.security.deps import AdminDep
from app.security.sessions import Sessao
from app.topic_state import ler_estado, salvar_estado
from app.topics import TOPICS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["admin"], dependencies=[AdminDep])

# Modelos de visão (imagem em alta resolução): custo bem maior por chamada.
_MODELOS_CAROS = frozenset({"gpt-4o"})


def _validar_chaves(chaves) -> None:
    desconhecidas = sorted(c for c in chaves if c not in TOPICS)
    if desconhecidas:
        nomes = ", ".join(repr(c[:64]) for c in desconhecidas[:5])
        raise ValueError(f"tópico(s) inexistente(s): {nomes}")


def _chave_ou_404(chave: str) -> str:
    if chave not in TOPICS:
        raise HTTPException(status_code=404, detail="Tópico não encontrado.")
    return chave


# ---------------------------------------------------------------------------
# Tópicos (ativação)
# ---------------------------------------------------------------------------

class TopicoInfo(BaseModel):
    chave: str
    titulo: str
    grupo: str
    estrategia: str
    modelo: str
    max_tokens: int
    endpoint: str
    custo: Literal["alto", "baixo"]
    ativo: bool
    implementado: bool
    tem_prompt: bool


class TopicosResponse(BaseModel):
    configuracao_valida: bool
    # Mensagem genérica quando o YAML está inválido (o detalhe, com caminho, fica só no log).
    mensagem: str | None = None
    topicos: list[TopicoInfo]


class TopicosUpdate(BaseModel):
    topicos: dict[str, StrictBool] = Field(min_length=1)

    @field_validator("topicos")
    @classmethod
    def _conhecidos(cls, v: dict[str, bool]) -> dict[str, bool]:
        _validar_chaves(v)
        return v


async def _listar_topicos(request: Request) -> TopicosResponse:
    settings = request.app.state.settings
    estado = await ler_estado(settings.topics_file)
    topicos = [
        TopicoInfo(
            chave=chave,
            titulo=cfg.nome,
            grupo=cfg.grupo,
            estrategia=cfg.estrategia,
            modelo=cfg.model,
            max_tokens=cfg.max_tokens,
            endpoint=cfg.endpoint,
            custo="alto" if cfg.model in _MODELOS_CAROS else "baixo",
            ativo=chave in estado.ativos,
            implementado=True,  # tudo que está em TOPICS tem execução; os não portados estão comentados
            tem_prompt=await carregar_prompt(chave, settings.prompts_dir) is not None,
        )
        for chave, cfg in TOPICS.items()
    ]
    return TopicosResponse(
        configuracao_valida=estado.erro is None,
        mensagem=(
            "config/topics.yaml inválido ou ausente: nenhum tópico roda. Salvar pela tela regrava o arquivo."
            if estado.erro else None
        ),
        topicos=topicos,
    )


@router.get("/topicos", response_model=TopicosResponse)
async def listar_topicos(request: Request) -> TopicosResponse:
    return await _listar_topicos(request)


@router.put("/topicos", response_model=TopicosResponse)
async def alterar_topicos(
    dados: TopicosUpdate, request: Request, sessao: Sessao = AdminDep
) -> TopicosResponse:
    await salvar_estado(request.app.state.settings.topics_file, dados.topicos)
    ligados = sorted(c for c, v in dados.topicos.items() if v)
    desligados = sorted(c for c, v in dados.topicos.items() if not v)
    logger.info(
        "Tópicos alterados (usuario=%r): ligados=%s desligados=%s",
        sessao.usuario[:64], ligados, desligados,
    )
    return await _listar_topicos(request)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

class PromptInfo(BaseModel):
    chave: str
    titulo: str
    conteudo: str | None  # None = não existe prompts/<chave>.md


class PromptsResponse(BaseModel):
    max_caracteres: int
    prompts: list[PromptInfo]


class PromptUpdate(BaseModel):
    conteudo: str = Field(min_length=1, max_length=PROMPT_MAX_CARACTERES)

    @field_validator("conteudo")
    @classmethod
    def _nao_vazio(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("o prompt não pode ser vazio")
        return v


async def _prompt_info(chave: str, prompts_dir: str) -> PromptInfo:
    return PromptInfo(
        chave=chave,
        titulo=TOPICS[chave].nome,
        conteudo=await carregar_prompt(chave, prompts_dir),
    )


@router.get("/prompts", response_model=PromptsResponse)
async def listar_prompts(request: Request) -> PromptsResponse:
    prompts_dir = request.app.state.settings.prompts_dir
    return PromptsResponse(
        max_caracteres=PROMPT_MAX_CARACTERES,
        prompts=[await _prompt_info(chave, prompts_dir) for chave in TOPICS],
    )


@router.get("/prompts/{chave}", response_model=PromptInfo)
async def obter_prompt(chave: str, request: Request) -> PromptInfo:
    return await _prompt_info(_chave_ou_404(chave), request.app.state.settings.prompts_dir)


@router.put("/prompts/{chave}", response_model=PromptInfo)
async def salvar_prompt_rota(
    chave: str, dados: PromptUpdate, request: Request, sessao: Sessao = AdminDep
) -> PromptInfo:
    chave = _chave_ou_404(chave)
    prompts_dir = request.app.state.settings.prompts_dir
    await salvar_prompt(chave, prompts_dir, dados.conteudo)
    logger.info(
        "Prompt '%s' salvo (usuario=%r, %d caracteres).",
        chave, sessao.usuario[:64], len(dados.conteudo),
    )
    return await _prompt_info(chave, prompts_dir)


# ---------------------------------------------------------------------------
# Executar (o botão da tela)
# ---------------------------------------------------------------------------

class ExecutarRequest(RelatorioRequest):
    # Roda exatamente estes tópicos, ignorando config/topics.yaml (sem alterar o estado salvo).
    topicos: list[str] | None = Field(default=None, min_length=1, max_length=len(TOPICS))
    # Faz fetch + montagem, mas não chama a OpenAI (nenhum token gasto).
    dry_run: bool = False

    @field_validator("topicos")
    @classmethod
    def _topicos_conhecidos(cls, v: list[str] | None) -> list[str] | None:
        if v is not None:
            _validar_chaves(v)
        return v


class ExecucaoResponse(RelatorioResponse):
    execucao_id: str
    dry_run: bool
    duracao_ms: int


@router.post("/executar", response_model=ExecucaoResponse)
async def executar(
    dados: ExecutarRequest, request: Request, sessao: Sessao = AdminDep
) -> ExecucaoResponse:
    st = request.app.state
    somente = frozenset(dados.topicos) if dados.topicos is not None else None

    with em_execucao() as execucao_id:
        logger.info(
            "Execução pela tela (usuario=%r, topicos=%s, dry_run=%s).",
            sessao.usuario[:64], sorted(somente) if somente else "config", dados.dry_run,
        )
        inicio = time.perf_counter()
        try:
            resposta = await executar_relatorio(
                dados, ProcessingContext.da_app(st), st.settings,
                somente=somente, dry_run=dados.dry_run,
            )
        except ConfiguracaoIndisponivel:
            raise HTTPException(status_code=503, detail=MSG_CONFIG_INDISPONIVEL) from None
        duracao_ms = round((time.perf_counter() - inicio) * 1000)
        logger.info("Execução concluída em %d ms.", duracao_ms)

    return ExecucaoResponse(
        **resposta.model_dump(),
        execucao_id=execucao_id,
        dry_run=dados.dry_run,
        duracao_ms=duracao_ms,
    )


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

class LogsResponse(BaseModel):
    linhas: list[dict]


@router.get("/logs", response_model=LogsResponse)
async def listar_logs(
    request: Request,
    nivel: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO",
    execucao: str | None = Query(default=None, max_length=32),
    apos: int = Query(default=0, ge=0),
    limite: int = Query(default=200, ge=1, le=1000),
) -> LogsResponse:
    buffer = request.app.state.logs
    if buffer is None:
        return LogsResponse(linhas=[])
    return LogsResponse(
        linhas=buffer.listar(nivel_minimo=nivel, execucao=execucao, apos=apos, limite=limite)
    )
