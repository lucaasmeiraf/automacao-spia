"""
Testes da seleção de tópicos: ativo (topics.yaml) + prompt (payload > arquivo).
"""
from __future__ import annotations

import pytest

from app.processing.selecao import selecionar_topicos
from app.topics import TOPICS


def _chaves(selecao) -> list[str]:
    return [cfg.chave for cfg, _ in selecao.executar]


@pytest.mark.asyncio
async def test_ativo_com_prompt_no_payload_executa(tmp_path):
    sel = await selecionar_topicos(frozenset({"justificativa"}), {"justificativa": "P"}, str(tmp_path))
    assert _chaves(sel) == ["justificativa"]
    assert sel.executar[0][1] == "P"
    assert sel.erros == [] and sel.ignorados == []


@pytest.mark.asyncio
async def test_prompt_do_payload_tem_prioridade_sobre_o_arquivo(tmp_path):
    (tmp_path / "justificativa.md").write_text("DO ARQUIVO", encoding="utf-8")
    sel = await selecionar_topicos(frozenset({"justificativa"}), {"justificativa": "DO PAYLOAD"}, str(tmp_path))
    assert sel.executar[0][1] == "DO PAYLOAD"


@pytest.mark.asyncio
async def test_usa_arquivo_quando_payload_nao_traz_prompt(tmp_path):
    (tmp_path / "justificativa.md").write_text("DO ARQUIVO", encoding="utf-8")
    sel = await selecionar_topicos(frozenset({"justificativa"}), {}, str(tmp_path))
    assert sel.executar[0][1] == "DO ARQUIVO"


@pytest.mark.asyncio
async def test_desligado_com_prompt_no_payload_e_ignorado(tmp_path):
    sel = await selecionar_topicos(frozenset(), {"justificativa": "P"}, str(tmp_path))
    assert sel.executar == []
    assert sel.erros == []  # não aparece na resposta
    assert sel.ignorados == ["justificativa"]


@pytest.mark.asyncio
async def test_desligado_nao_usa_nem_o_arquivo(tmp_path):
    (tmp_path / "justificativa.md").write_text("DO ARQUIVO", encoding="utf-8")
    sel = await selecionar_topicos(frozenset(), {}, str(tmp_path))
    assert sel.executar == [] and sel.erros == [] and sel.ignorados == []


@pytest.mark.asyncio
async def test_ativo_sem_nenhum_prompt_vira_erro_visivel(tmp_path):
    sel = await selecionar_topicos(frozenset({"justificativa"}), {}, str(tmp_path))
    assert sel.executar == []
    assert len(sel.erros) == 1
    assert sel.erros[0].topico == "justificativa" and sel.erros[0].ok is False
    assert "prompts/justificativa.md" in sel.erros[0].erro


@pytest.mark.asyncio
async def test_chave_desconhecida_no_payload_vira_erro(tmp_path):
    sel = await selecionar_topicos(frozenset(), {"nao_existe": "P"}, str(tmp_path))
    assert sel.executar == []
    assert [e.topico for e in sel.erros] == ["nao_existe"]
    assert sel.erros[0].ok is False


@pytest.mark.asyncio
async def test_executa_na_ordem_de_topics_e_nao_na_do_payload(tmp_path):
    ordem = list(TOPICS)
    a, b, c = ordem[2], ordem[0], ordem[5]
    payload = {c: "P", a: "P", b: "P"}  # ordem propositalmente embaralhada
    sel = await selecionar_topicos(frozenset({a, b, c}), payload, str(tmp_path))
    assert _chaves(sel) == [b, a, c]


def test_topics_yaml_do_repositorio_e_valido_e_cobre_todos_os_topicos():
    """O config/topics.yaml versionado precisa ser válido e listar todo tópico definido."""
    from pathlib import Path

    import yaml

    from app.topic_state import interpretar
    from app.topicos_extras import carregar

    raiz = Path(__file__).resolve().parent.parent
    # Como no create_app: os tópicos criados pela tela (versionados) também contam. O conftest
    # devolve TOPICS ao estado "só código" depois do teste.
    carregar(str(raiz / "config" / "topicos_extras.yaml"))
    dados = yaml.safe_load((raiz / "config" / "topics.yaml").read_text(encoding="utf-8"))
    estado = interpretar(dados)
    assert estado.erro is None
    assert estado.avisos == ()
    assert set(dados["topicos"]) == set(TOPICS)
