"""
Testes da API de configuração (fase 2b): /api/topicos, /api/prompts, /api/executar, /api/logs.

Casos NEGATIVOS primeiro (sem sessão, sem CSRF, fora de dev), depois o funcionamento. Nenhuma API
real é chamada: `processar_topico` é substituído por um falso e os clientes são mocks.
"""
from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest
import yaml
from fastapi.testclient import TestClient

import app.processing.execucao as execucao
from app.models import TopicoResultado
from app.topic_state import _cache
from app.topics import TOPICS
from tests.helpers import SENHA_ADMIN, fazer_app, fazer_settings

USUARIO = "lucas.meira"
BODY = {"contrato": "00 00493/2013", "periodo_inicio": "2025-10-01", "periodo_fim": "2025-10-31"}
YAML_PADRAO = "topicos:\n  justificativa: true\n  oaes: true\n  rpfo: false\n"

ROTAS_LEITURA = ["/api/topicos", "/api/prompts", "/api/prompts/justificativa", "/api/logs"]
ROTAS_ESCRITA = [
    ("put", "/api/topicos", {"json": {"topicos": {"rpfo": True}}}),
    ("put", "/api/prompts/justificativa", {"json": {"conteudo": "novo"}}),
    ("post", "/api/executar", {"json": BODY}),
    ("delete", "/api/prompts/justificativa", {}),
    ("post", "/api/topicos", {"json": {"chave": "novo_topico", "titulo": "Novo", "grupo": "G",
                                       "endpoint": "novo_topico"}}),
]


@pytest.fixture(autouse=True)
def _limpa_cache():
    _cache.clear()
    yield
    _cache.clear()


@pytest.fixture
def chamadas(monkeypatch):
    """Substitui processar_topico por um falso que também 'chama a LLM' via ctx.openai."""
    registro: list[tuple[str, str]] = []

    async def falso(cfg, prompt, contrato, ini, fim, ctx):
        registro.append((cfg.chave, prompt))
        logging.getLogger("teste.topico").info("processando %s", cfg.chave)
        resposta = await ctx.openai.chat({
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"dados de {cfg.chave}"},
            ],
        })
        return TopicoResultado(topico=cfg.chave, ok=True, conteudo={"resposta": resposta})

    monkeypatch.setattr(execucao, "processar_topico", falso)
    return registro


class Ambiente:
    def __init__(self, tmp_path, hash_admin, env="dev", yaml_texto=YAML_PADRAO):
        self.topicos = tmp_path / "topics.yaml"
        if yaml_texto is not None:
            self.topicos.write_text(yaml_texto, encoding="utf-8")
        self.prompts = tmp_path / "prompts"
        self.prompts.mkdir(exist_ok=True)
        self.extras = tmp_path / "topicos_extras.yaml"
        settings = fazer_settings(
            env=env,
            admin_users={USUARIO: hash_admin},
            cookie_secure=False,
            topics_file=str(self.topicos),
            prompts_dir=str(self.prompts),
            topicos_extras_file=str(self.extras),
        )
        self.app = fazer_app(settings)
        self.app.state.openai = AsyncMock()
        self.app.state.openai.chat.return_value = '{"conforme": "Conforme", "motivo": "ok"}'
        self.cliente = TestClient(self.app)
        self.csrf: str | None = None

    def login(self) -> "Ambiente":
        r = self.cliente.post("/api/auth/login", json={"usuario": USUARIO, "senha": SENHA_ADMIN})
        assert r.status_code == 200
        self.csrf = r.json()["csrf_token"]
        return self

    def escrever(self, metodo: str, rota: str, **kw):
        headers = {"X-CSRF-Token": self.csrf} if self.csrf else {}
        return getattr(self.cliente, metodo)(rota, headers=headers, **kw)

    def prompt(self, chave: str, texto: str) -> None:
        (self.prompts / f"{chave}.md").write_text(texto, encoding="utf-8")


@pytest.fixture
def amb(tmp_path, hash_admin) -> Ambiente:
    return Ambiente(tmp_path, hash_admin)


# ---------------------------------------------------------------------------
# Segurança: sem sessão, sem CSRF, fora de dev
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rota", ROTAS_LEITURA)
def test_leitura_sem_sessao_401(amb, rota):
    assert amb.cliente.get(rota).status_code == 401


@pytest.mark.parametrize("metodo,rota,kw", ROTAS_ESCRITA)
def test_escrita_sem_sessao_401_e_nada_muda(amb, chamadas, metodo, rota, kw):
    antes = amb.topicos.read_text(encoding="utf-8")
    assert getattr(amb.cliente, metodo)(rota, **kw).status_code == 401
    assert amb.topicos.read_text(encoding="utf-8") == antes
    assert not (amb.prompts / "justificativa.md").exists()
    assert not amb.extras.exists() and "novo_topico" not in TOPICS
    assert chamadas == []


@pytest.mark.parametrize("metodo,rota,kw", ROTAS_ESCRITA)
@pytest.mark.parametrize("csrf", [None, "token-errado"])
def test_escrita_sem_csrf_valido_403_e_nada_muda(amb, chamadas, metodo, rota, kw, csrf):
    amb.login()
    antes = amb.topicos.read_text(encoding="utf-8")
    headers = {"X-CSRF-Token": csrf} if csrf else {}
    assert getattr(amb.cliente, metodo)(rota, headers=headers, **kw).status_code == 403
    assert amb.topicos.read_text(encoding="utf-8") == antes
    assert not (amb.prompts / "justificativa.md").exists()
    assert not amb.extras.exists() and "novo_topico" not in TOPICS
    assert chamadas == []


@pytest.mark.parametrize("env", ["homolog", "prod"])
def test_rotas_de_configuracao_nao_existem_fora_de_dev(tmp_path, hash_admin, env):
    amb = Ambiente(tmp_path, hash_admin, env=env)
    for rota in ROTAS_LEITURA:
        assert amb.cliente.get(rota).status_code == 404
    for metodo, rota, kw in ROTAS_ESCRITA:
        assert getattr(amb.cliente, metodo)(rota, **kw).status_code == 404
    assert amb.app.state.logs is None  # nem o buffer de logs existe


def test_todas_as_rotas_do_router_admin_exigem_admin():
    """Garante que nenhuma rota nova do router nasça sem a dependência de admin."""
    from app.routers.admin import router
    from app.security.deps import exigir_admin

    assert any(d.dependency is exigir_admin for d in router.dependencies)


# ---------------------------------------------------------------------------
# /api/topicos
# ---------------------------------------------------------------------------

def test_listar_topicos_mostra_todos_com_estado(amb):
    amb.login()
    amb.prompt("oaes", "prompt oaes")
    r = amb.cliente.get("/api/topicos")
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["configuracao_valida"] is True
    por_chave = {t["chave"]: t for t in corpo["topicos"]}
    assert list(por_chave) == list(TOPICS)  # todos, na ordem de TOPICS
    assert por_chave["justificativa"]["ativo"] is True
    assert por_chave["rpfo"]["ativo"] is False
    assert por_chave["historico"]["ativo"] is False  # ausente do YAML = desligado
    assert por_chave["oaes"]["tem_prompt"] is True
    assert por_chave["justificativa"]["tem_prompt"] is False
    assert por_chave["mapa_situacao"]["custo"] == "alto"
    assert por_chave["justificativa"]["custo"] == "baixo"


def test_listar_topicos_com_yaml_invalido_avisa_sem_vazar_caminho(tmp_path, hash_admin):
    amb = Ambiente(tmp_path, hash_admin, yaml_texto="topicos:\n  justificativa: 'sim'\n").login()
    corpo = amb.cliente.get("/api/topicos").json()
    assert corpo["configuracao_valida"] is False
    assert corpo["mensagem"]
    assert str(tmp_path) not in amb.cliente.get("/api/topicos").text
    assert not any(t["ativo"] for t in corpo["topicos"])


def test_alterar_topicos_aplica_sobre_o_estado_atual(amb):
    amb.login()
    r = amb.escrever("put", "/api/topicos", json={"topicos": {"rpfo": True, "oaes": False}})
    assert r.status_code == 200
    ativos = {t["chave"] for t in r.json()["topicos"] if t["ativo"]}
    assert ativos == {"justificativa", "rpfo"}

    # O arquivo regravado lista TODOS os tópicos, só com booleanos.
    dados = yaml.safe_load(amb.topicos.read_text(encoding="utf-8"))["topicos"]
    assert set(dados) == set(TOPICS)
    assert all(isinstance(v, bool) for v in dados.values())
    assert {k for k, v in dados.items() if v} == {"justificativa", "rpfo"}


def test_alterar_topicos_conserta_yaml_invalido(tmp_path, hash_admin):
    amb = Ambiente(tmp_path, hash_admin, yaml_texto="topicos: [ quebrado").login()
    r = amb.escrever("put", "/api/topicos", json={"topicos": {"historico": True}})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["configuracao_valida"] is True
    # Base de um arquivo inválido é "tudo desligado" — nunca "tudo ligado".
    assert {t["chave"] for t in corpo["topicos"] if t["ativo"]} == {"historico"}


@pytest.mark.parametrize("corpo", [
    {"topicos": {"nao_existe": True}},
    {"topicos": {"../../.env": True}},
    {"topicos": {"justificativa": "false"}},   # string não é booleano
    {"topicos": {"justificativa": 1}},
    {"topicos": {}},
    {},
])
def test_alterar_topicos_invalido_422_e_arquivo_intacto(amb, corpo):
    amb.login()
    antes = amb.topicos.read_text(encoding="utf-8")
    assert amb.escrever("put", "/api/topicos", json=corpo).status_code == 422
    assert amb.topicos.read_text(encoding="utf-8") == antes


def test_alteracao_de_topicos_e_logada_com_usuario(amb, caplog):
    amb.login()
    with caplog.at_level(logging.INFO, logger="app.routers.admin"):
        amb.escrever("put", "/api/topicos", json={"topicos": {"rpfo": True}})
    assert any("Tópicos alterados" in m and USUARIO in m for m in caplog.messages)


# ---------------------------------------------------------------------------
# POST /api/topicos (criar tópico pela tela)
# ---------------------------------------------------------------------------

NOVO = {
    "chave": "sumario", "titulo": "Sumário", "grupo": "Relatório Principal", "endpoint": "secao_sumario",
    "estrategia": "campo", "campo_conteudo": "resumo", "html_fields": ["resumo"],
}


def test_criar_topico_nasce_desligado_e_aparece_na_lista(amb):
    amb.login()
    antes = amb.topicos.read_text(encoding="utf-8")
    r = amb.escrever("post", "/api/topicos", json=NOVO)
    assert r.status_code == 201
    por_chave = {t["chave"]: t for t in r.json()["topicos"]}
    assert list(por_chave)[-1] == "sumario"
    t = por_chave["sumario"]
    assert (t["titulo"], t["grupo"], t["endpoint"], t["estrategia"]) == (
        "Sumário", "Relatório Principal", "secao_sumario", "campo")
    assert t["ativo"] is False and t["tem_prompt"] is False and t["no_codigo"] is False
    assert t["html_fields"] == ["resumo"] and t["modelo"] == "gpt-4o-mini"
    assert por_chave["justificativa"]["no_codigo"] is True
    assert amb.topicos.read_text(encoding="utf-8") == antes  # ativação intacta
    assert "sumario" in yaml.safe_load(amb.extras.read_text(encoding="utf-8"))["topicos"]


def test_topico_criado_sobrevive_a_reinicializacao(amb, tmp_path, hash_admin):
    amb.login()
    assert amb.escrever("post", "/api/topicos", json=NOVO).status_code == 201
    outra = Ambiente(tmp_path, hash_admin).login()  # mesma pasta = mesmos arquivos
    chaves = [t["chave"] for t in outra.cliente.get("/api/topicos").json()["topicos"]]
    assert "sumario" in chaves


def test_topico_criado_liga_recebe_prompt_e_executa(amb):
    amb.login()
    amb.escrever("post", "/api/topicos", json=NOVO)
    assert amb.escrever("put", "/api/topicos", json={"topicos": {"sumario": True}}).status_code == 200
    assert yaml.safe_load(amb.topicos.read_text(encoding="utf-8"))["topicos"]["sumario"] is True
    assert amb.escrever("put", "/api/prompts/sumario", json={"conteudo": "Avalie."}).status_code == 200

    amb.app.state.dnit.buscar_secao = AsyncMock(return_value=[{"resumo": "<p>Texto do sumário</p>"}])
    r = amb.escrever("post", "/api/executar", json={**BODY, "topicos": ["sumario"], "dry_run": True})
    assert r.status_code == 200
    amb.app.state.dnit.buscar_secao.assert_awaited_once()
    assert amb.app.state.dnit.buscar_secao.await_args.args[0] == "secao_sumario"
    (chamada,) = r.json()["topicos"][0]["conteudo"]["chamadas_llm"]
    assert chamada["mensagens"] == [
        {"role": "system", "conteudo": "Avalie."},
        {"role": "user", "conteudo": "Texto do sumário"},
    ]


@pytest.mark.parametrize("chave", ["justificativa", "sumario"])
def test_criar_topico_com_chave_repetida_409(amb, chave):
    amb.login()
    amb.escrever("post", "/api/topicos", json=NOVO)
    antes = amb.extras.read_text(encoding="utf-8")
    r = amb.escrever("post", "/api/topicos", json={**NOVO, "chave": chave})
    assert r.status_code == 409
    assert chave in r.json()["detail"]
    assert amb.extras.read_text(encoding="utf-8") == antes


@pytest.mark.parametrize("mudanca", [
    {"chave": "../../.env"}, {"endpoint": "a/../b"}, {"estrategia": "imagem"},
    {"titulo": ""}, {"max_tokens": 10**6}, {"campo_extra": 1},
])
def test_criar_topico_invalido_422_e_nada_grava(amb, mudanca):
    amb.login()
    r = amb.escrever("post", "/api/topicos", json={**NOVO, **mudanca})
    assert r.status_code == 422
    assert not amb.extras.exists()
    assert "sumario" not in TOPICS


def test_criacao_de_topico_e_logada_com_usuario(amb, caplog):
    amb.login()
    with caplog.at_level(logging.INFO, logger="app.routers.admin"):
        amb.escrever("post", "/api/topicos", json=NOVO)
    assert "Tópico criado" in caplog.text and USUARIO in caplog.text and "sumario" in caplog.text


def test_executar_aceita_todos_os_topicos_mesmo_com_os_criados(amb, chamadas):
    amb.login()
    amb.escrever("post", "/api/topicos", json=NOVO)
    for chave in TOPICS:
        amb.prompt(chave, f"P-{chave}")
    r = amb.escrever("post", "/api/executar", json={**BODY, "topicos": list(TOPICS)})
    assert r.status_code == 200
    assert {c for c, _ in chamadas} == set(TOPICS)


# ---------------------------------------------------------------------------
# /api/prompts
# ---------------------------------------------------------------------------

def test_listar_prompts(amb):
    amb.login()
    amb.prompt("justificativa", "texto do prompt")
    corpo = amb.cliente.get("/api/prompts").json()
    por_chave = {p["chave"]: p for p in corpo["prompts"]}
    assert list(por_chave) == list(TOPICS)
    assert por_chave["justificativa"]["conteudo"] == "texto do prompt"
    assert por_chave["oaes"]["conteudo"] is None
    assert corpo["max_caracteres"] > 0


def test_obter_e_salvar_prompt(amb):
    amb.login()
    r = amb.escrever("put", "/api/prompts/justificativa", json={"conteudo": "Linha 1\r\nLinha 2\r\n"})
    assert r.status_code == 200
    assert r.json()["conteudo"] == "Linha 1\nLinha 2"
    assert (amb.prompts / "justificativa.md").read_bytes() == b"Linha 1\nLinha 2\n"
    assert amb.cliente.get("/api/prompts/justificativa").json()["conteudo"] == "Linha 1\nLinha 2"


@pytest.mark.parametrize("chave", ["nao_existe", "..%2F..%2F.env", "%2E%2E"])
def test_prompt_de_chave_desconhecida_404(amb, chave):
    amb.login()
    assert amb.cliente.get(f"/api/prompts/{chave}").status_code == 404
    assert amb.escrever("put", f"/api/prompts/{chave}", json={"conteudo": "x"}).status_code == 404
    assert list(amb.prompts.iterdir()) == []


@pytest.mark.parametrize("conteudo", ["", "   \n  ", "x" * 50_001], ids=["vazio", "espacos", "gigante"])
def test_prompt_vazio_ou_gigante_422(amb, conteudo):
    amb.login()
    r = amb.escrever("put", "/api/prompts/justificativa", json={"conteudo": conteudo})
    assert r.status_code == 422
    assert not (amb.prompts / "justificativa.md").exists()


@pytest.mark.parametrize("csrf", [None, "token-errado"])
def test_excluir_prompt_sem_sessao_ou_csrf_nao_apaga(amb, csrf):
    amb.prompt("justificativa", "texto")
    assert amb.cliente.delete("/api/prompts/justificativa").status_code == 401
    amb.login()
    headers = {"X-CSRF-Token": csrf} if csrf else {}
    assert amb.cliente.delete("/api/prompts/justificativa", headers=headers).status_code == 403
    assert (amb.prompts / "justificativa.md").exists()


def test_excluir_prompt(amb, caplog):
    amb.login()
    amb.prompt("justificativa", "texto")
    with caplog.at_level(logging.INFO, logger="app.routers.admin"):
        r = amb.escrever("delete", "/api/prompts/justificativa")
    assert r.status_code == 200
    assert r.json() == {"chave": "justificativa", "titulo": TOPICS["justificativa"].nome, "conteudo": None}
    assert not (amb.prompts / "justificativa.md").exists()
    assert "Prompt 'justificativa' excluído" in caplog.text and USUARIO in caplog.text
    por_chave = {t["chave"]: t for t in amb.cliente.get("/api/topicos").json()["topicos"]}
    assert por_chave["justificativa"]["tem_prompt"] is False

    # Idempotente: de novo, sem arquivo, continua 200.
    assert amb.escrever("delete", "/api/prompts/justificativa").status_code == 200


@pytest.mark.parametrize("chave", ["nao_existe", "..", "README"])
def test_excluir_prompt_de_chave_desconhecida_404(amb, chave):
    amb.login()
    (amb.prompts / "README.md").write_text("x", encoding="utf-8")
    assert amb.escrever("delete", f"/api/prompts/{chave}").status_code == 404
    assert (amb.prompts / "README.md").exists()


def test_topico_ativo_sem_prompt_depois_de_excluir_volta_erro(amb, chamadas):
    amb.login()
    amb.prompt("justificativa", "P1")
    amb.prompt("oaes", "P2")
    amb.escrever("delete", "/api/prompts/justificativa")
    r = amb.escrever("post", "/api/executar", json=BODY)
    topicos = {t["topico"]: t for t in r.json()["topicos"]}
    assert topicos["justificativa"]["ok"] is False and "sem prompt" in topicos["justificativa"]["erro"]
    assert [c for c, _ in chamadas] == ["oaes"]


# ---------------------------------------------------------------------------
# /api/executar
# ---------------------------------------------------------------------------

def test_executar_roda_os_ativos_do_yaml(amb, chamadas):
    amb.login()
    amb.prompt("justificativa", "P-arquivo")
    r = amb.escrever("post", "/api/executar", json={**BODY, "prompts": [{"topico": "oaes", "conteudo": "P-tela"}]})
    assert r.status_code == 200
    corpo = r.json()
    assert sorted(chamadas) == [("justificativa", "P-arquivo"), ("oaes", "P-tela")]
    assert {t["topico"] for t in corpo["topicos"]} == {"justificativa", "oaes"}
    assert corpo["dry_run"] is False
    assert len(corpo["execucao_id"]) == 12
    assert corpo["duracao_ms"] >= 0
    amb.app.state.openai.chat.assert_awaited()


def test_executar_topicos_avulsos_ignora_yaml_sem_alterar_estado(amb, chamadas):
    amb.login()
    amb.prompt("rpfo", "P-rpfo")  # rpfo está DESLIGADO no YAML
    antes = amb.topicos.read_text(encoding="utf-8")
    r = amb.escrever("post", "/api/executar", json={**BODY, "topicos": ["rpfo"]})
    assert r.status_code == 200
    assert chamadas == [("rpfo", "P-rpfo")]
    assert amb.topicos.read_text(encoding="utf-8") == antes


@pytest.mark.parametrize("topicos", [["nao_existe"], [], ["justificativa"] * (len(TOPICS) + 1)])
def test_executar_topicos_invalidos_422(amb, chamadas, topicos):
    amb.login()
    r = amb.escrever("post", "/api/executar", json={**BODY, "topicos": topicos})
    assert r.status_code == 422
    assert chamadas == []


def test_executar_dry_run_nao_chama_a_openai(amb, chamadas):
    amb.login()
    amb.prompt("justificativa", "P1")
    amb.prompt("oaes", "P2")
    r = amb.escrever("post", "/api/executar", json={**BODY, "dry_run": True})
    assert r.status_code == 200
    amb.app.state.openai.chat.assert_not_awaited()

    corpo = r.json()
    assert corpo["dry_run"] is True
    topicos = {t["topico"]: t for t in corpo["topicos"]}
    (chamada,) = topicos["justificativa"]["conteudo"]["chamadas_llm"]
    assert topicos["justificativa"]["conteudo"]["dry_run"] is True
    assert chamada["modelo"] == TOPICS["justificativa"].model
    assert chamada["mensagens"][0] == {"role": "system", "conteudo": "P1"}
    assert chamada["tokens_texto_estimados"] > 0


def test_executar_com_yaml_invalido_503_generico(tmp_path, hash_admin, chamadas):
    amb = Ambiente(tmp_path, hash_admin, yaml_texto=None).login()
    r = amb.escrever("post", "/api/executar", json=BODY)
    assert r.status_code == 503
    assert str(tmp_path) not in r.text
    assert chamadas == []


# ---------------------------------------------------------------------------
# /api/logs
# ---------------------------------------------------------------------------

@pytest.fixture
def logs_ligados(amb, caplog):
    """Liga o buffer no logger raiz (o lifespan, que faria isso, não roda nos testes)."""
    caplog.set_level(logging.INFO)
    raiz = logging.getLogger()
    raiz.addHandler(amb.app.state.logs)
    yield
    raiz.removeHandler(amb.app.state.logs)


def test_logs_filtrados_pela_execucao(amb, chamadas, logs_ligados):
    amb.login()
    amb.prompt("justificativa", "P1")
    execucao_id = amb.escrever("post", "/api/executar", json=BODY).json()["execucao_id"]
    amb.escrever("post", "/api/executar", json=BODY)  # outra execução, não deve aparecer

    linhas = amb.cliente.get("/api/logs", params={"execucao": execucao_id}).json()["linhas"]
    assert linhas
    assert all(linha["execucao"] == execucao_id for linha in linhas)
    # Logs emitidos DENTRO do tópico (tarefa do gather) herdam o id da execução.
    assert any(linha["mensagem"] == "processando justificativa" for linha in linhas)


def test_logs_filtro_de_nivel_e_sem_senha(amb, logs_ligados):
    amb.cliente.post("/api/auth/login", json={"usuario": USUARIO, "senha": "senha-errada-123"})
    amb.login()
    linhas = amb.cliente.get("/api/logs", params={"nivel": "WARNING"}).json()["linhas"]
    assert linhas and all(linha["nivel"] in ("WARNING", "ERROR", "CRITICAL") for linha in linhas)
    todas = amb.cliente.get("/api/logs", params={"nivel": "DEBUG"}).text
    assert "senha-errada-123" not in todas and SENHA_ADMIN not in todas


@pytest.mark.parametrize("params", [{"nivel": "TUDO"}, {"limite": 0}, {"limite": 5000}, {"apos": -1}])
def test_logs_parametros_invalidos_422(amb, params):
    amb.login()
    assert amb.cliente.get("/api/logs", params=params).status_code == 422
