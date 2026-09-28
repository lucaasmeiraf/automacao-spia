"""
Testes do estado de ativação dos tópicos (config/topics.yaml).

Cobre: validação estrita (só booleanos), tópico ausente = desligado, chave desconhecida vira
aviso, FALHA SEGURA (arquivo ausente/YAML inválido => nenhum tópico ativo) e recarga por mtime.
"""
from __future__ import annotations

import pytest

import yaml

from app.topic_state import _cache, gerar_yaml, interpretar, ler_estado, salvar_estado
from app.topics import TOPICS

CONHECIDOS = frozenset({"a", "b", "c"})


# ---------------------------------------------------------------------------
# interpretar (função pura)
# ---------------------------------------------------------------------------

def test_interpretar_ativa_somente_true():
    estado = interpretar({"topicos": {"a": True, "b": False}}, CONHECIDOS)
    assert estado.erro is None
    assert estado.ativos == frozenset({"a"})


def test_interpretar_topico_ausente_fica_desligado():
    estado = interpretar({"topicos": {"a": True}}, CONHECIDOS)
    assert "b" not in estado.ativos and "c" not in estado.ativos


def test_interpretar_topicos_vazio_nada_ativo_sem_erro():
    for dados in ({"topicos": None}, {"topicos": {}}):
        estado = interpretar(dados, CONHECIDOS)
        assert estado.erro is None
        assert estado.ativos == frozenset()


def test_interpretar_chave_desconhecida_gera_aviso_e_e_ignorada():
    estado = interpretar({"topicos": {"a": True, "typo": True}}, CONHECIDOS)
    assert estado.erro is None
    assert estado.ativos == frozenset({"a"})
    assert any("typo" in aviso for aviso in estado.avisos)


@pytest.mark.parametrize("valor", ["false", "true", "yes", 1, 0, None, []])
def test_interpretar_valor_nao_booleano_invalida_tudo(valor):
    # "false" (string) seria truthy em Python: por segurança, nada roda.
    estado = interpretar({"topicos": {"a": True, "b": valor}}, CONHECIDOS)
    assert estado.erro is not None
    assert estado.ativos == frozenset()


@pytest.mark.parametrize("dados", [None, [], "texto", {"outra": 1}, {"topicos": ["a"]}, {"topicos": "a"}])
def test_interpretar_formato_invalido(dados):
    estado = interpretar(dados, CONHECIDOS)
    assert estado.erro is not None
    assert estado.ativos == frozenset()


def test_interpretar_chave_nao_string_invalida():
    estado = interpretar({"topicos": {1: True}}, CONHECIDOS)
    assert estado.erro is not None


# ---------------------------------------------------------------------------
# ler_estado (arquivo real em tmp_path)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _limpa_cache():
    _cache.clear()
    yield
    _cache.clear()


@pytest.mark.asyncio
async def test_ler_estado_arquivo_valido(tmp_path):
    f = tmp_path / "topics.yaml"
    f.write_text("topicos:\n  justificativa: true\n  oaes: false\n", encoding="utf-8")
    estado = await ler_estado(str(f))
    assert estado.erro is None
    assert estado.ativos == frozenset({"justificativa"})


@pytest.mark.asyncio
async def test_ler_estado_arquivo_ausente_falha_segura(tmp_path):
    estado = await ler_estado(str(tmp_path / "nao_existe.yaml"))
    assert estado.erro is not None
    assert estado.ativos == frozenset()


@pytest.mark.asyncio
async def test_ler_estado_yaml_invalido_falha_segura(tmp_path):
    f = tmp_path / "topics.yaml"
    f.write_text("topicos: [ isto não fecha", encoding="utf-8")
    estado = await ler_estado(str(f))
    assert estado.erro is not None
    assert estado.ativos == frozenset()


@pytest.mark.asyncio
async def test_ler_estado_recarrega_quando_arquivo_muda(tmp_path):
    f = tmp_path / "topics.yaml"
    f.write_text("topicos:\n  justificativa: true\n", encoding="utf-8")
    assert (await ler_estado(str(f))).ativos == frozenset({"justificativa"})

    f.write_text("topicos:\n  justificativa: false\n  historico: true\n", encoding="utf-8")
    assert (await ler_estado(str(f))).ativos == frozenset({"historico"})


@pytest.mark.asyncio
async def test_ler_estado_usa_cache_quando_arquivo_nao_muda(tmp_path, monkeypatch):
    f = tmp_path / "topics.yaml"
    f.write_text("topicos:\n  justificativa: true\n", encoding="utf-8")
    await ler_estado(str(f))

    import app.topic_state as ts

    def _nao_deveria_parsear(*_a, **_k):
        raise AssertionError("yaml.safe_load chamado apesar do cache")

    monkeypatch.setattr(ts.yaml, "safe_load", _nao_deveria_parsear)
    estado = await ler_estado(str(f))
    assert estado.ativos == frozenset({"justificativa"})


# ---------------------------------------------------------------------------
# Gravação (API de configuração)
# ---------------------------------------------------------------------------

def test_gerar_yaml_lista_todos_os_topicos_e_e_valido():
    texto = gerar_yaml({"justificativa", "oaes"})
    estado = interpretar(yaml.safe_load(texto))
    assert estado.erro is None and not estado.avisos
    assert estado.ativos == frozenset({"justificativa", "oaes"})
    assert set(yaml.safe_load(texto)["topicos"]) == set(TOPICS)


@pytest.mark.asyncio
async def test_salvar_estado_aplica_sobre_o_atual(tmp_path):
    f = tmp_path / "topics.yaml"
    f.write_text("topicos:\n  justificativa: true\n  oaes: true\n", encoding="utf-8")
    estado = await salvar_estado(str(f), {"oaes": False, "rpfo": True})
    assert estado.ativos == frozenset({"justificativa", "rpfo"})
    assert (await ler_estado(str(f))).ativos == frozenset({"justificativa", "rpfo"})
    assert [p.name for p in tmp_path.iterdir()] == ["topics.yaml"]  # sem temporários


@pytest.mark.asyncio
@pytest.mark.parametrize("conteudo", [None, "topicos: [ quebrado", "topicos:\n  justificativa: 'sim'\n"])
async def test_salvar_estado_sobre_arquivo_invalido_parte_de_tudo_desligado(tmp_path, conteudo):
    f = tmp_path / "topics.yaml"
    if conteudo is not None:
        f.write_text(conteudo, encoding="utf-8")
    estado = await salvar_estado(str(f), {"historico": True})
    assert estado.erro is None
    assert estado.ativos == frozenset({"historico"})


@pytest.mark.asyncio
async def test_salvar_estado_chave_desconhecida_nao_grava(tmp_path):
    f = tmp_path / "topics.yaml"
    f.write_text("topicos:\n  justificativa: true\n", encoding="utf-8")
    antes = f.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        await salvar_estado(str(f), {"nao_existe": True})
    assert f.read_text(encoding="utf-8") == antes
