"""
Testes do modo dry-run: resumo da chamada, resultado devolvido e execução real do pipeline
genérico SEM chamar a OpenAI (clientes mockados).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import RelatorioRequest, TopicoResultado
from app.processing.context import ProcessingContext
from app.processing.dry_run import OpenAISimulado, resultado_dry_run, resumir_chamada
from app.processing.execucao import executar_relatorio
from tests.helpers import fazer_settings


def test_resumir_chamada_texto():
    resumo = resumir_chamada({
        "model": "gpt-4o-mini",
        "max_tokens": 800,
        "messages": [
            {"role": "system", "content": "abcd" * 10},   # 40 caracteres
            {"role": "user", "content": "x" * 2},
        ],
    })
    assert resumo["modelo"] == "gpt-4o-mini" and resumo["max_tokens"] == 800
    assert resumo["caracteres_texto"] == 42
    assert resumo["tokens_texto_estimados"] == 11
    assert resumo["imagens"] == 0
    assert resumo["mensagens"][1] == {"role": "user", "conteudo": "xx"}


def test_resumir_chamada_imagem_nao_devolve_base64():
    data_uri = "data:image/png;base64," + "A" * 10_000
    resumo = resumir_chamada({
        "model": "gpt-4o",
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_uri, "detail": "high"}},
                {"type": "text", "text": "analise"},
            ],
        }],
    })
    assert resumo["imagens"] == 1
    assert "AAAA" not in str(resumo)
    assert resumo["mensagens"][0]["conteudo"][0] == {"tipo": "imagem", "tamanho_base64": len(data_uri)}
    assert resumo["caracteres_texto"] == len("analise")


@pytest.mark.asyncio
async def test_openai_simulado_registra_e_devolve_json():
    sim = OpenAISimulado()
    resposta = await sim.chat({"model": "m", "messages": []})
    assert resposta == '{"dry_run": true}'
    assert len(sim.chamadas) == 1


def test_resultado_dry_run_mantem_falha():
    falha = TopicoResultado(topico="t", ok=False, erro="SUPRA fora do ar")
    assert resultado_dry_run(falha, []) is falha


def test_resultado_dry_run_sem_chamada_llm_explica():
    ok = TopicoResultado(topico="t", ok=True, conteudo={"conforme": "Atenção"})
    r = resultado_dry_run(ok, [])
    assert r.ok and r.conteudo["chamadas_llm"] == []
    assert r.conteudo["resultado"] == {"conforme": "Atenção"}
    assert "observacao" in r.conteudo


@pytest.mark.asyncio
async def test_executar_dry_run_pipeline_generico_nao_chama_openai(tmp_path):
    """Pipeline REAL (estratégia 'campo'): o fetch acontece, a OpenAI não."""
    (tmp_path / "topics.yaml").write_text("topicos:\n  justificativa: true\n", encoding="utf-8")
    settings = fazer_settings(topics_file=str(tmp_path / "topics.yaml"), prompts_dir=str(tmp_path))

    dnit = MagicMock()
    dnit.buscar_secao = AsyncMock(return_value=[{"resumo": "<p>Texto da justificativa</p>"}])
    openai = MagicMock()
    openai.chat = AsyncMock()
    ctx = ProcessingContext(dnit=dnit, openai=openai, openmeteo=MagicMock(), nominatim=MagicMock())

    req = RelatorioRequest(
        contrato="c", periodo_inicio="2025-10-01", periodo_fim="2025-10-31",
        prompts=[{"topico": "justificativa", "conteudo": "PROMPT"}],
    )
    resposta = await executar_relatorio(req, ctx, settings, dry_run=True)

    openai.chat.assert_not_awaited()
    dnit.buscar_secao.assert_awaited_once()
    (topico,) = resposta.topicos
    (chamada,) = topico.conteudo["chamadas_llm"]
    assert chamada["mensagens"][0] == {"role": "system", "conteudo": "PROMPT"}
    assert chamada["mensagens"][1]["conteudo"] == "Texto da justificativa"  # HTML já limpo


@pytest.mark.asyncio
async def test_executar_somente_ignora_yaml(tmp_path):
    # Sem topics.yaml: com `somente`, a execução não depende dele.
    settings = fazer_settings(topics_file=str(tmp_path / "nao_existe.yaml"), prompts_dir=str(tmp_path))
    dnit = MagicMock()
    dnit.buscar_secao = AsyncMock(return_value=[{"resumo": "x"}])
    ctx = ProcessingContext(dnit=dnit, openai=MagicMock(), openmeteo=MagicMock(), nominatim=MagicMock())
    req = RelatorioRequest(
        contrato="c", periodo_inicio="2025-10-01", periodo_fim="2025-10-31",
        prompts=[{"topico": "historico", "conteudo": "P"}, {"topico": "introducao", "conteudo": "P"}],
    )
    resposta = await executar_relatorio(req, ctx, settings, somente=frozenset({"historico"}), dry_run=True)
    assert [t.topico for t in resposta.topicos] == ["historico"]
