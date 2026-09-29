"""
Tópicos criados pela tela (`config/topicos_extras.yaml`): validação, leitura com falha segura,
gravação e integração com `TOPICS` / `topics.yaml`.
"""
from __future__ import annotations

import logging

import pytest
import yaml
from pydantic import ValidationError

from app.topic_state import gerar_yaml as gerar_yaml_ativacao
from app.topic_state import interpretar
from app.topicos_extras import ChaveRepetida, TopicoNovo, carregar, criar, gerar_yaml
from app.topics import GRUPO_PRINCIPAL, TOPICOS_BASE, TOPICS

NOVO = {"chave": "sumario", "titulo": "Sumário", "grupo": GRUPO_PRINCIPAL, "endpoint": "sumario"}


def _novo(**kw) -> TopicoNovo:
    return TopicoNovo(**{**NOVO, **kw})


# ---------------------------------------------------------------------------
# Validação
# ---------------------------------------------------------------------------

def test_padroes_iguais_aos_de_topicconfig():
    cfg = _novo().para_config()
    assert (cfg.chave, cfg.endpoint, cfg.titulo, cfg.grupo) == ("sumario", "sumario", "Sumário", GRUPO_PRINCIPAL)
    assert (cfg.model, cfg.max_tokens, cfg.estrategia, cfg.campo_conteudo) == ("gpt-4o-mini", 1200, "campo", "resumo")
    assert cfg.html_fields == () and cfg.campos_manter == () and cfg.campos_presenca == ()


def test_listas_viram_tuplas_e_espacos_sao_removidos():
    cfg = _novo(
        titulo="  Sumário  ", estrategia="json", html_fields=[" descricao "],
        campos_manter=["a", "b"], campos_presenca=["a"], empty_as_array=True,
    ).para_config()
    assert cfg.titulo == "Sumário"
    assert cfg.html_fields == ("descricao",) and cfg.campos_manter == ("a", "b")
    assert cfg.campos_presenca == ("a",) and cfg.empty_as_array is True


@pytest.mark.parametrize("campo,valor", [
    ("chave", "Sumario"),              # maiúscula
    ("chave", "../../.env"),           # vira caminho de prompts/<chave>.md
    ("chave", "a"),                    # curta demais
    ("endpoint", "secao/../outra"),    # vira caminho de URL da SUPRA
    ("endpoint", "sumario?x=1"),
    ("estrategia", "imagem"),          # precisa de handler em código
    ("estrategia", "pluviometrico"),
    ("modelo", "gpt-5"),
    ("max_tokens", 0),
    ("max_tokens", 100_000),
    ("titulo", "   "),
    ("grupo", "x" * 81),
    ("html_fields", ["campo com espaço"]),
    ("campos_manter", ["a"] * 51),
    ("campo_conteudo", "a.b"),
    ("inesperado", True),              # campo desconhecido
])
def test_valores_invalidos(campo, valor):
    with pytest.raises(ValidationError):
        _novo(**{campo: valor})


# ---------------------------------------------------------------------------
# Leitura (falha segura)
# ---------------------------------------------------------------------------

def test_arquivo_ausente_so_os_do_codigo(tmp_path):
    carregar(str(tmp_path / "nao_existe.yaml"))
    assert dict(TOPICS) == dict(TOPICOS_BASE)


@pytest.mark.parametrize("texto", [
    "topicos: [1, 2", "- lista\n- solta\n", "topicos: 3\n", "sumario: {titulo: S, grupo: G, endpoint: s}\n",
])
def test_arquivo_invalido_ignora_extras_e_loga(tmp_path, caplog, texto):
    f = tmp_path / "extras.yaml"
    f.write_text(texto, encoding="utf-8")
    with caplog.at_level(logging.ERROR):
        carregar(str(f))
    assert dict(TOPICS) == dict(TOPICOS_BASE)
    assert "Tópicos extras" in caplog.text


def test_entrada_invalida_ou_repetida_e_ignorada_sem_afetar_as_outras(tmp_path, caplog):
    f = tmp_path / "extras.yaml"
    f.write_text(
        "topicos:\n"
        "  sumario: {titulo: Sumário, grupo: G, endpoint: sumario}\n"
        "  quebrado: {titulo: X, grupo: G, endpoint: '../x'}\n"
        "  justificativa: {titulo: Outra, grupo: G, endpoint: outra}\n"   # já existe no código
        "  lista: [1, 2]\n",
        encoding="utf-8",
    )
    with caplog.at_level(logging.ERROR):
        carregar(str(f))
    assert set(TOPICS) - set(TOPICOS_BASE) == {"sumario"}
    assert TOPICS["justificativa"] is TOPICOS_BASE["justificativa"]
    for chave in ("quebrado", "justificativa", "lista"):
        assert f"'{chave}' ignorado" in caplog.text


def test_carregar_de_novo_substitui_os_extras_anteriores(tmp_path):
    f = tmp_path / "extras.yaml"
    f.write_text("topicos:\n  sumario: {titulo: S, grupo: G, endpoint: sumario}\n", encoding="utf-8")
    carregar(str(f))
    assert "sumario" in TOPICS
    carregar(str(tmp_path / "outro.yaml"))
    assert "sumario" not in TOPICS


# ---------------------------------------------------------------------------
# Gravação
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_criar_grava_e_acrescenta_no_fim_de_topics(tmp_path):
    f = tmp_path / "config" / "extras.yaml"
    cfg = await criar(str(f), _novo(estrategia="json", campos_manter=["a"]))
    assert list(TOPICS)[-1] == "sumario" and TOPICS["sumario"] == cfg

    # O arquivo gravado é lido de volta igual (numa nova inicialização).
    carregar(str(tmp_path / "vazio.yaml"))
    assert "sumario" not in TOPICS
    carregar(str(f))
    assert TOPICS["sumario"] == cfg


@pytest.mark.asyncio
async def test_criar_mantem_os_extras_ja_gravados(tmp_path):
    f = tmp_path / "extras.yaml"
    await criar(str(f), _novo())
    await criar(str(f), _novo(chave="anexos", titulo="Anexos", endpoint="anexos"))
    assert list(yaml.safe_load(f.read_text(encoding="utf-8"))["topicos"]) == ["sumario", "anexos"]


@pytest.mark.asyncio
@pytest.mark.parametrize("chave", ["justificativa", "sumario"])
async def test_criar_chave_repetida_nao_grava(tmp_path, chave):
    f = tmp_path / "extras.yaml"
    await criar(str(f), _novo())
    antes = f.read_text(encoding="utf-8")
    with pytest.raises(ChaveRepetida):
        await criar(str(f), _novo(chave=chave))
    assert f.read_text(encoding="utf-8") == antes
    assert TOPICS["justificativa"] is TOPICOS_BASE["justificativa"]


def test_yaml_gerado_tem_cabecalho_e_acentos_legiveis():
    texto = gerar_yaml({"sumario": _novo()})
    assert texto.startswith("# Tópicos criados pela tela")
    assert "Sumário" in texto
    assert yaml.safe_load(texto)["topicos"]["sumario"]["endpoint"] == "sumario"


# ---------------------------------------------------------------------------
# Integração com a ativação (config/topics.yaml)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_topics_yaml_coloca_o_extra_no_proprio_grupo_sem_repetir_cabecalho(tmp_path):
    await criar(str(tmp_path / "extras.yaml"), _novo())
    await criar(str(tmp_path / "extras.yaml"), _novo(chave="anexos", titulo="A", grupo="Grupo Novo", endpoint="anexos"))
    texto = gerar_yaml_ativacao({"sumario"})

    assert texto.count(f"— {GRUPO_PRINCIPAL}") == 1
    assert "# Grupo 3 — Grupo Novo" in texto
    principal = texto.split(f"— {GRUPO_PRINCIPAL}")[1].split("# Grupo 2")[0]
    assert "sumario: true" in principal

    estado = interpretar(yaml.safe_load(texto))
    assert estado.erro is None and not estado.avisos
    assert estado.ativos == frozenset({"sumario"})


def test_topics_yaml_sem_extras_nao_muda():
    """A regra de agrupamento nova gera o mesmo arquivo para os tópicos do código."""
    texto = gerar_yaml_ativacao({"justificativa"})
    cabecalhos = [linha.strip() for linha in texto.splitlines() if linha.strip().startswith("# Grupo")]
    grupos = list(dict.fromkeys(cfg.grupo for cfg in TOPICOS_BASE.values()))
    assert cabecalhos == [f"# Grupo {i} — {g}" for i, g in enumerate(grupos, start=1)]
