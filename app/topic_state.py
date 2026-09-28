"""
Estado de ativação dos tópicos — o "fio" do n8n.

Lê `config/topics.yaml` (chave do tópico → true/false). Quem define COMO um tópico
funciona é `app/topics.py`; aqui só se define SE ele roda.

Regras:
  - o arquivo é relido a cada requisição, com cache por (mtime, tamanho): editar o
    arquivo tem efeito imediato, sem reiniciar o servidor e sem custo de parse repetido;
  - tópico ausente do arquivo = desligado;
  - valores precisam ser booleanos de verdade (`true`/`false`). Uma string como "false"
    seria "verdadeira" em Python — por isso qualquer valor não booleano invalida o arquivo;
  - FALHA SEGURA: arquivo ausente, YAML inválido ou formato errado => NENHUM tópico ativo e
    `erro` preenchido. Nunca "liga tudo" por engano (cada tópico ativo pode gerar custo de API);
  - chave que não existe em `TOPICS` (ex.: erro de digitação) é ignorada, mas gera aviso.

Gravação (API de configuração, só em dev): `salvar_estado` aplica as alterações sobre o estado
atual e regrava o arquivo INTEIRO a partir de `TOPICS` (todos os tópicos listados, agrupados), de
forma atômica. Se o arquivo atual estiver inválido, a base é "tudo desligado" — salvar o conserta.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import yaml

from app.arquivos import escrever_atomico
from app.topics import TOPICS

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EstadoTopicos:
    ativos: frozenset[str] = frozenset()
    # Preenchido quando o arquivo não pôde ser usado (então `ativos` é vazio).
    erro: str | None = None
    # Problemas não fatais (ex.: chave desconhecida).
    avisos: tuple[str, ...] = ()


def interpretar(dados: object, conhecidos: frozenset[str] | None = None) -> EstadoTopicos:
    """Valida o conteúdo já carregado do YAML e devolve o estado (função pura)."""
    conhecidos = frozenset(TOPICS) if conhecidos is None else conhecidos

    if not isinstance(dados, dict) or "topicos" not in dados:
        return EstadoTopicos(erro="formato inválido: esperado um mapa com a chave 'topicos'")

    mapa = dados["topicos"]
    if mapa is None:
        mapa = {}
    if not isinstance(mapa, dict):
        return EstadoTopicos(erro="formato inválido: 'topicos' deve ser um mapa chave: true/false")

    ativos: set[str] = set()
    avisos: list[str] = []
    for chave, valor in mapa.items():
        if not isinstance(chave, str):
            return EstadoTopicos(erro=f"chave inválida em 'topicos': {chave!r}")
        if not isinstance(valor, bool):
            return EstadoTopicos(
                erro=f"valor inválido para '{chave}': use true ou false (recebido {valor!r})"
            )
        if chave not in conhecidos:
            avisos.append(f"tópico '{chave}' não existe em app/topics.py (ignorado)")
            continue
        if valor:
            ativos.add(chave)

    return EstadoTopicos(ativos=frozenset(ativos), avisos=tuple(avisos))


# caminho -> ((mtime_ns, tamanho), estado)
_cache: dict[str, tuple[tuple[int, int], EstadoTopicos]] = {}


def _ler_estado_sync(caminho: str) -> EstadoTopicos:
    path = Path(caminho)
    try:
        st = path.stat()
    except FileNotFoundError:
        return EstadoTopicos(erro=f"arquivo de tópicos não encontrado: {caminho}")
    except OSError as exc:
        return EstadoTopicos(erro=f"não foi possível acessar {caminho}: {exc}")

    assinatura = (st.st_mtime_ns, st.st_size)
    em_cache = _cache.get(caminho)
    if em_cache and em_cache[0] == assinatura:
        return em_cache[1]

    try:
        dados = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        estado = EstadoTopicos(erro=f"YAML ilegível em {caminho}: {exc}")
    else:
        estado = interpretar(dados)

    if estado.erro:
        logger.error("Configuração de tópicos inválida: %s", estado.erro)
    for aviso in estado.avisos:
        logger.warning("Configuração de tópicos: %s", aviso)

    _cache[caminho] = (assinatura, estado)
    return estado


async def ler_estado(caminho: str) -> EstadoTopicos:
    """Lê o estado de ativação (I/O em thread, para não bloquear o event loop)."""
    return await asyncio.to_thread(_ler_estado_sync, caminho)


_CABECALHO_YAML = """\
# Ativação dos tópicos — o "fio" do n8n.
#
#   true  = o tópico roda (desde que exista em app/topics.py e tenha prompt);
#   false = o tópico é ignorado, mesmo que o payload traga o prompt dele.
#
# Tópico ausente deste arquivo = desligado. Use SEMPRE true/false (sem aspas).
# Este arquivo é relido a cada requisição: não precisa reiniciar o servidor.
# Se ele estiver inválido, NENHUM tópico roda (a API responde 503) — nunca liga tudo.
# Também é gravado pela API de configuração (ENV=dev): edições manuais de comentário se perdem.
#
# Atenção a custo: mapa_situacao e diagrama_ocorrencias usam gpt-4o com visão (bem mais caro).
"""


def gerar_yaml(ativos: frozenset[str] | set[str]) -> str:
    """Conteúdo completo de topics.yaml: todos os tópicos de TOPICS, na ordem, por grupo."""
    linhas = [_CABECALHO_YAML, "topicos:"]
    numero_grupo = 0
    grupo_atual: str | None = None
    for chave, cfg in TOPICS.items():
        if cfg.grupo != grupo_atual:
            grupo_atual = cfg.grupo
            numero_grupo += 1
            if numero_grupo > 1:
                linhas.append("")
            if grupo_atual:
                linhas.append(f"  # Grupo {numero_grupo} — {grupo_atual}")
        linhas.append(f"  {chave}: {'true' if chave in ativos else 'false'}")
    return "\n".join(linhas) + "\n"


# Serializa ler → alterar → gravar (duas gravações simultâneas não perdem alterações).
_trava_escrita = threading.Lock()


def _salvar_estado_sync(caminho: str, alteracoes: dict[str, bool]) -> EstadoTopicos:
    desconhecidos = sorted(set(alteracoes) - set(TOPICS))
    if desconhecidos:
        raise ValueError(f"tópicos inexistentes: {', '.join(desconhecidos)}")

    with _trava_escrita:
        atual = _ler_estado_sync(caminho)
        ativos = set() if atual.erro else set(atual.ativos)
        for chave, ligado in alteracoes.items():
            (ativos.add if ligado else ativos.discard)(chave)

        escrever_atomico(caminho, gerar_yaml(ativos))
        _cache.pop(caminho, None)
        return _ler_estado_sync(caminho)


async def salvar_estado(caminho: str, alteracoes: dict[str, bool]) -> EstadoTopicos:
    """Aplica `{chave: ligado}` sobre o estado atual e grava o YAML de forma atômica."""
    return await asyncio.to_thread(_salvar_estado_sync, caminho, alteracoes)
