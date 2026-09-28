"""
Teste do endpoint POST /webhook/relatorio: seleção de tópicos + chave de API.

O lifespan NÃO é executado (TestClient sem `with`): os clientes são mocks e `processar_topico`
é substituído por um falso — nenhuma API real é chamada.

Cobre o teste de paralelismo do CLAUDE.md: ≥3 tópicos simultâneos, todos presentes em
`topicos`, e erro em um não derruba os demais.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.processing.execucao as execucao
from app.models import TopicoResultado
from app.topic_state import _cache
from tests.helpers import CHAVE_WEBHOOK, fazer_app, fazer_settings

BODY = {"contrato": "00 00493/2013", "periodo_inicio": "2025-10-01", "periodo_fim": "2025-10-31"}
CHAVE = {"X-API-Key": CHAVE_WEBHOOK}


@pytest.fixture(autouse=True)
def _limpa_cache():
    _cache.clear()
    yield
    _cache.clear()


@pytest.fixture
def chamadas(monkeypatch):
    """Substitui processar_topico por um falso e registra o que foi executado."""
    registro: list[tuple[str, str]] = []

    async def falso(cfg, prompt, contrato, ini, fim, ctx):
        registro.append((cfg.chave, prompt))
        if cfg.chave == "oaes":
            return TopicoResultado(topico=cfg.chave, ok=False, erro="falha simulada")
        return TopicoResultado(topico=cfg.chave, ok=True, conteudo={"conforme": "Conforme"})

    monkeypatch.setattr(execucao, "processar_topico", falso)
    return registro


def _cliente(tmp_path, yaml_texto: str | None, com_chave: bool = True, **settings_kw) -> TestClient:
    topicos = tmp_path / "topics.yaml"
    if yaml_texto is not None:
        topicos.write_text(yaml_texto, encoding="utf-8")
    prompts = tmp_path / "prompts"
    prompts.mkdir(exist_ok=True)

    settings = fazer_settings(env="dev", topics_file=str(topicos), prompts_dir=str(prompts), **settings_kw)
    return TestClient(fazer_app(settings), headers=CHAVE if com_chave else {})


# ---------------------------------------------------------------------------
# Seleção de tópicos
# ---------------------------------------------------------------------------

def test_tres_topicos_em_paralelo_erro_isolado(tmp_path, chamadas):
    cliente = _cliente(
        tmp_path,
        "topicos:\n  justificativa: true\n  oaes: true\n  historico: true\n  rpfo: false\n",
    )
    payload = {
        **BODY,
        "prompts": [
            {"topico": "justificativa", "conteudo": "P1"},
            {"topico": "oaes", "conteudo": "P2"},
            {"topico": "historico", "conteudo": "P3"},
        ],
    }
    resp = cliente.post("/webhook/relatorio", json=payload)
    assert resp.status_code == 200
    topicos = {t["topico"]: t for t in resp.json()["topicos"]}
    assert set(topicos) == {"justificativa", "oaes", "historico"}
    assert topicos["oaes"]["ok"] is False
    assert topicos["justificativa"]["ok"] is True and topicos["historico"]["ok"] is True


def test_topico_desligado_com_prompt_no_payload_nao_roda_nem_aparece(tmp_path, chamadas):
    cliente = _cliente(tmp_path, "topicos:\n  justificativa: true\n  rpfo: false\n")
    payload = {
        **BODY,
        "prompts": [
            {"topico": "justificativa", "conteudo": "P1"},
            {"topico": "rpfo", "conteudo": "P-desligado"},
        ],
    }
    resp = cliente.post("/webhook/relatorio", json=payload)
    assert resp.status_code == 200
    assert [t["topico"] for t in resp.json()["topicos"]] == ["justificativa"]
    assert [c[0] for c in chamadas] == ["justificativa"]  # a LLM nunca foi acionada p/ rpfo


def test_usa_prompt_do_arquivo_quando_payload_nao_traz(tmp_path, chamadas):
    cliente = _cliente(tmp_path, "topicos:\n  justificativa: true\n")
    (tmp_path / "prompts" / "justificativa.md").write_text("PROMPT DO ARQUIVO", encoding="utf-8")
    resp = cliente.post("/webhook/relatorio", json=BODY)  # sem prompts[]
    assert resp.status_code == 200
    assert chamadas == [("justificativa", "PROMPT DO ARQUIVO")]


def test_topico_ativo_sem_prompt_aparece_como_erro(tmp_path, chamadas):
    cliente = _cliente(tmp_path, "topicos:\n  justificativa: true\n")
    resp = cliente.post("/webhook/relatorio", json=BODY)
    assert resp.status_code == 200
    (t,) = resp.json()["topicos"]
    assert t["topico"] == "justificativa" and t["ok"] is False
    assert chamadas == []


def test_yaml_invalido_responde_503_sem_vazar_detalhes(tmp_path, chamadas):
    cliente = _cliente(tmp_path, "topicos:\n  justificativa: 'false'\n")  # string, não bool
    payload = {**BODY, "prompts": [{"topico": "justificativa", "conteudo": "P"}]}
    resp = cliente.post("/webhook/relatorio", json=payload)
    assert resp.status_code == 503
    corpo = resp.text
    assert "topics.yaml" not in corpo and str(tmp_path) not in corpo and "false" not in corpo
    assert chamadas == []  # falha segura: nada rodou


def test_arquivo_de_topicos_ausente_responde_503(tmp_path, chamadas):
    cliente = _cliente(tmp_path, None)
    resp = cliente.post("/webhook/relatorio", json=BODY)
    assert resp.status_code == 503
    assert chamadas == []


def test_validacao_de_campos_obrigatorios_continua_422(tmp_path, chamadas):
    cliente = _cliente(tmp_path, "topicos:\n  justificativa: true\n")
    resp = cliente.post("/webhook/relatorio", json={"contrato": "x"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Chave de API do webhook
# ---------------------------------------------------------------------------

def test_webhook_sem_chave_401_e_nada_executa(tmp_path, chamadas):
    cliente = _cliente(tmp_path, "topicos:\n  justificativa: true\n", com_chave=False)
    payload = {**BODY, "prompts": [{"topico": "justificativa", "conteudo": "P"}]}
    resp = cliente.post("/webhook/relatorio", json=payload)
    assert resp.status_code == 401
    assert chamadas == []


@pytest.mark.parametrize("chave", ["errada", "k" * 39, "k" * 41, CHAVE_WEBHOOK.upper()])
def test_webhook_chave_errada_401(tmp_path, chamadas, chave):
    cliente = _cliente(tmp_path, "topicos:\n  justificativa: true\n", com_chave=False)
    resp = cliente.post("/webhook/relatorio", json=BODY, headers={"X-API-Key": chave})
    assert resp.status_code == 401
    assert chamadas == []


def test_webhook_sem_chave_configurada_falha_fechada_503(tmp_path, chamadas):
    cliente = _cliente(tmp_path, "topicos:\n  justificativa: true\n", webhook_api_key=None)
    resp = cliente.post("/webhook/relatorio", json=BODY, headers=CHAVE)
    assert resp.status_code == 503
    assert chamadas == []


def test_webhook_bloqueia_apos_varias_chaves_erradas(tmp_path, chamadas):
    cliente = _cliente(tmp_path, "topicos:\n  justificativa: true\n", com_chave=False)
    for _ in range(5):
        assert cliente.post("/webhook/relatorio", json=BODY, headers={"X-API-Key": "x"}).status_code == 401
    # Depois do limite, até a chave CERTA é recusada temporariamente (não dá para testar chaves à vontade).
    resp = cliente.post("/webhook/relatorio", json=BODY, headers=CHAVE)
    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) > 0


def test_resposta_do_webhook_tem_cabecalhos_de_seguranca(tmp_path, chamadas):
    cliente = _cliente(tmp_path, "topicos:\n  justificativa: true\n")
    resp = cliente.post("/webhook/relatorio", json=BODY)
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]
