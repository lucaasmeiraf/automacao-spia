"""
Tópicos criados pela tela de configuração (ENV=dev): `config/topicos_extras.yaml`.

`app/topics.py` define os tópicos em código (`TOPICOS_BASE`). Este módulo acrescenta a `TOPICS`, em
tempo de execução, os tópicos criados pela tela, que ficam num arquivo versionado. Como o arquivo vai
para a imagem junto com `config/`, os tópicos criados em dev valem também em homolog/prod depois do
commit.

Regras:
  - só as estratégias do fluxo genérico (`campo`, `json`): as demais precisam de handler em código;
  - chave, endpoint e nomes de campos têm formato restrito (a chave vira nome de arquivo em
    `prompts/<chave>.md` e o endpoint vira caminho de URL da SUPRA);
  - a chave não pode repetir a de outro tópico (do código ou do arquivo);
  - o tópico nasce DESLIGADO (fica fora de `config/topics.yaml` até ser ligado na tela);
  - FALHA SEGURA na leitura: arquivo ausente = nenhum extra; arquivo ilegível = nenhum extra (com
    erro no log); entrada inválida = só ela é ignorada. Os tópicos do código nunca são afetados.

O arquivo é lido na criação da app (`create_app`) e regravado inteiro, de forma atômica, a cada
tópico criado. Edição manual do arquivo só vale depois de reiniciar o servidor.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from app.arquivos import escrever_atomico
from app.topics import TOPICOS_BASE, TOPICS, TopicConfig

logger = logging.getLogger(__name__)

# Nome de campo de um registro da SUPRA (ex.: "resumo", "numero_termo").
NomeCampo = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9_]{1,64}$")]
ListaCampos = Annotated[list[NomeCampo], Field(max_length=50)]
Texto = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class TopicoNovo(BaseModel):
    """Definição de um tópico criado pela tela (mesmos campos de `TopicConfig`, com validação)."""

    model_config = ConfigDict(extra="forbid")

    chave: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z][a-z0-9_]{1,63}$")]
    titulo: Texto
    grupo: Texto
    # sufixo do endpoint: .../secao_ws/<endpoint>
    endpoint: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9_]{1,80}$")]
    modelo: Literal["gpt-4o-mini", "gpt-4o"] = "gpt-4o-mini"
    max_tokens: int = Field(default=1200, ge=50, le=4096)
    estrategia: Literal["campo", "json"] = "campo"
    campo_conteudo: NomeCampo = "resumo"
    html_fields: ListaCampos = []
    campos_manter: ListaCampos = []
    empty_as_array: bool = False
    campos_presenca: ListaCampos = []

    def para_config(self) -> TopicConfig:
        return TopicConfig(
            chave=self.chave,
            endpoint=self.endpoint,
            model=self.modelo,
            max_tokens=self.max_tokens,
            html_fields=tuple(self.html_fields),
            estrategia=self.estrategia,
            campo_conteudo=self.campo_conteudo,
            campos_manter=tuple(self.campos_manter),
            empty_as_array=self.empty_as_array,
            campos_presenca=tuple(self.campos_presenca),
            titulo=self.titulo,
            grupo=self.grupo,
        )


class ChaveRepetida(ValueError):
    """Já existe um tópico com esta chave."""


def _ler_arquivo(caminho: str) -> dict[str, TopicoNovo]:
    """Entradas válidas do arquivo, na ordem. Falha segura: nunca levanta exceção."""
    path = Path(caminho)
    try:
        texto = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as exc:
        logger.error("Tópicos extras: não foi possível ler %s: %s", caminho, exc)
        return {}

    try:
        dados = yaml.safe_load(texto)
    except yaml.YAMLError as exc:
        logger.error("Tópicos extras: YAML ilegível em %s: %s", caminho, exc)
        return {}
    if dados is None:
        return {}
    mapa = dados.get("topicos", dados) if isinstance(dados, dict) else dados
    if mapa is None:
        mapa = {}
    if not isinstance(mapa, dict) or mapa is dados:
        logger.error("Tópicos extras: formato inválido em %s (esperado 'topicos: {chave: {...}}')", caminho)
        return {}

    extras: dict[str, TopicoNovo] = {}
    for chave, definicao in mapa.items():
        if not isinstance(definicao, dict):
            logger.error("Tópicos extras: '%s' ignorado (definição não é um mapa).", chave)
            continue
        try:
            novo = TopicoNovo(chave=chave, **definicao)
        except (ValidationError, TypeError) as exc:
            logger.error("Tópicos extras: '%s' ignorado (inválido): %s", chave, exc)
            continue
        if novo.chave in TOPICOS_BASE:
            logger.error("Tópicos extras: '%s' ignorado (já existe em app/topics.py).", novo.chave)
            continue
        extras[novo.chave] = novo
    return extras


def aplicar(extras: dict[str, TopicoNovo]) -> None:
    """Reconstrói `TOPICS` NO LUGAR (quem importou o dicionário vê a mudança): código + extras."""
    TOPICS.clear()
    TOPICS.update(TOPICOS_BASE)
    TOPICS.update({chave: novo.para_config() for chave, novo in extras.items()})


def carregar(caminho: str) -> None:
    """Lê o arquivo e aplica os extras a `TOPICS` (usado por `create_app`)."""
    extras = _ler_arquivo(caminho)
    aplicar(extras)
    if extras:
        logger.info("Tópicos extras carregados de %s: %s", caminho, ", ".join(extras))


_CABECALHO_YAML = """\
# Tópicos criados pela tela de configuração (ENV=dev) — ver app/topicos_extras.py.
#
# Complementa app/topics.py: mesmos campos de TopicConfig, só as estratégias "campo" e "json".
# Ligar/desligar continua em config/topics.yaml (tópico novo nasce desligado); o prompt fica em
# prompts/<chave>.md. Regravado pela API a cada tópico criado: edições manuais de comentário se
# perdem, e editar à mão só vale depois de reiniciar o servidor.
"""


def gerar_yaml(extras: dict[str, TopicoNovo]) -> str:
    corpo = {
        "topicos": {
            chave: novo.model_dump(exclude={"chave"}) for chave, novo in extras.items()
        }
    }
    return _CABECALHO_YAML + yaml.safe_dump(corpo, allow_unicode=True, sort_keys=False)


# Serializa ler → acrescentar → gravar (duas criações simultâneas não se perdem).
_trava_escrita = threading.Lock()


def _criar_sync(caminho: str, novo: TopicoNovo) -> TopicConfig:
    with _trava_escrita:
        if novo.chave in TOPICS:
            raise ChaveRepetida(novo.chave)
        extras = _ler_arquivo(caminho)
        if novo.chave in extras:  # arquivo editado à mão depois da carga
            raise ChaveRepetida(novo.chave)
        extras[novo.chave] = novo
        escrever_atomico(caminho, gerar_yaml(extras))
        cfg = novo.para_config()
        TOPICS[novo.chave] = cfg
        return cfg


async def criar(caminho: str, novo: TopicoNovo) -> TopicConfig:
    """Grava o tópico em `config/topicos_extras.yaml` e o acrescenta a `TOPICS`."""
    return await asyncio.to_thread(_criar_sync, caminho, novo)
