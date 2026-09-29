"""
Testes da tela de configuração (fase 3): rotas por ambiente e verificações estáticas de segurança
do front (sem inline — a CSP bloquearia —, sem innerHTML/eval, CSRF fora do localStorage) e de
consistência (toda rota /api usada pelo JS existe no servidor).
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.routers.ui import STATIC_DIR, UI_DIR
from tests.helpers import fazer_app, fazer_settings

HTML = (UI_DIR / "config.html").read_text(encoding="utf-8")
JS = (STATIC_DIR / "config.js").read_text(encoding="utf-8")
# Código sem comentários (os comentários citam justamente o que é proibido).
JS_CODIGO = re.sub(r"(?m)^\s*//.*$", "", re.sub(r"/\*.*?\*/", "", JS, flags=re.S))


def _cliente(env: str = "dev") -> TestClient:
    return TestClient(fazer_app(fazer_settings(env=env, cookie_secure=False)), follow_redirects=False)


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------

def test_tela_de_configuracao_em_dev():
    r = _cliente().get("/ui/config")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "script-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Cache-Control"] == "no-cache"


@pytest.mark.parametrize("arquivo,tipo", [("config.js", "javascript"), ("app.css", "text/css")])
def test_arquivos_estaticos_em_dev(arquivo, tipo):
    r = _cliente().get(f"/ui/static/{arquivo}")
    assert r.status_code == 200
    assert tipo in r.headers["content-type"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"


def test_raiz_redireciona_para_a_tela_em_dev():
    r = _cliente().get("/")
    assert r.status_code == 307 and r.headers["location"] == "/ui/config"


@pytest.mark.parametrize("env", ["homolog", "prod"])
@pytest.mark.parametrize("rota", ["/", "/ui/config", "/ui/static/config.js", "/ui/static/app.css"])
def test_tela_nao_existe_fora_de_dev(env, rota):
    assert _cliente(env).get(rota).status_code == 404


def test_static_nao_serve_arquivos_fora_da_pasta():
    cliente = _cliente()
    for rota in ("/ui/static/../config.html", "/ui/static/..%2F..%2Fconfig.py", "/ui/static/%2e%2e/%2e%2e/main.py"):
        r = cliente.get(rota)
        assert r.status_code == 404 or "create_app" not in r.text


# ---------------------------------------------------------------------------
# HTML: nada inline (a CSP bloquearia e seria vetor de XSS)
# ---------------------------------------------------------------------------

def test_html_sem_script_ou_estilo_inline():
    for tag in re.findall(r"<script\b[^>]*>", HTML, flags=re.I):
        assert 'src="/ui/static/' in tag, tag
    assert not re.search(r"<script\b[^>]*>\s*[^<\s]", HTML, flags=re.I), "script com corpo inline"
    assert "<style" not in HTML.lower()
    assert not re.search(r"\sstyle\s*=", HTML, flags=re.I)
    assert not re.search(r"\son[a-z]+\s*=", HTML, flags=re.I), "handler inline (onclick=...)"
    assert "javascript:" not in HTML.lower()


def test_html_so_referencia_arquivos_estaticos_existentes():
    refs = re.findall(r'(?:src|href)="/ui/static/([^"]+)"', HTML)
    assert refs
    for ref in refs:
        assert (STATIC_DIR / ref).is_file(), ref


def test_html_sem_recursos_externos():
    assert not re.search(r'(?:src|href)="(?:https?:)?//', HTML)


# ---------------------------------------------------------------------------
# JS: sem injeção de HTML, sem eval, CSRF só em memória
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("proibido", [
    "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function",
    "localStorage", "setTimeout(\"", "setInterval(\"",
])
def test_js_nao_usa_apis_perigosas(proibido):
    assert proibido not in JS_CODIGO, proibido


def test_js_so_chama_o_proprio_servidor():
    assert not re.search(r"fetch\(\s*['\"`]https?:", JS_CODIGO)
    assert "http://" not in JS_CODIGO and "https://" not in JS_CODIGO


def test_js_so_guarda_formulario_no_session_storage():
    # Único uso de armazenamento: contrato/período (nada de token/CSRF).
    assert re.findall(r"sessionStorage\.setItem\(([^,]+),", JS_CODIGO) == ["CHAVE_FORM"]
    trecho = JS_CODIGO.split("sessionStorage.setItem")[1].split("}));")[0]
    assert "csrf" not in trecho.lower()


def test_rotas_da_api_usadas_pelo_js_existem():
    """Toda rota /api citada no JS existe: sem login ela responde 401/405/422, nunca 404."""
    cliente = _cliente()
    usadas = set(re.findall(r"['\"`](/api/[a-z_/]+)", JS_CODIGO))
    assert {"/api/topicos", "/api/prompts", "/api/executar", "/api/logs", "/api/auth/me"} <= usadas
    if "`/api/prompts/${" in JS_CODIGO:
        usadas.add("/api/prompts/justificativa")
    for caminho in usadas:
        r = cliente.get(caminho.rstrip("/"))
        assert r.status_code != 404, caminho


# ---------------------------------------------------------------------------
# Modal "Novo Prompt": lista de tópicos do relatório (static/topicos_relatorio.js)
# ---------------------------------------------------------------------------

TOPICOS_RELATORIO_JS = (STATIC_DIR / "topicos_relatorio.js").read_text(encoding="utf-8")


def test_topicos_relatorio_apontam_para_topicos_existentes():
    from app.topicos_extras import _ler_arquivo
    from app.topics import TOPICOS_BASE

    # Tópicos do código + os criados pela tela (config/topicos_extras.yaml, versionado).
    extras = _ler_arquivo(str(UI_DIR.parents[1] / "config" / "topicos_extras.yaml"))
    chaves = re.findall(r'chave:\s*"([a-z0-9_]+)"', TOPICOS_RELATORIO_JS)
    assert chaves, "nenhum item ligado a um tópico"
    assert len(chaves) == len(set(chaves)), "dois itens apontam para o mesmo tópico"
    assert set(chaves) <= set(TOPICOS_BASE) | set(extras)
    assert set(TOPICOS_BASE) <= set(chaves), "tópico do sistema sem item na lista do relatório"


def test_topicos_relatorio_ids_unicos():
    ids = re.findall(r'\bid:\s*"([^"]+)"', TOPICOS_RELATORIO_JS)
    assert len(ids) == len(set(ids)) and len(ids) >= 40


@pytest.mark.parametrize("proibido", ["innerHTML", "outerHTML", "insertAdjacentHTML", "eval(", "fetch(", "Storage"])
def test_topicos_relatorio_e_so_dados(proibido):
    assert proibido not in TOPICOS_RELATORIO_JS
