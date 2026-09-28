"""
Testes das rotas de autenticação do administrador (login / me / logout) e das proteções
de borda: CSRF, rotas por ambiente, /docs desligado, 422 sem eco de senha.

O TestClient usa http://testserver: cookies com a flag Secure não voltariam ao servidor.
Por isso o fluxo completo usa `cookie_secure=False`, e os atributos do cookie de PRODUÇÃO
(Secure, __Host-, HttpOnly, SameSite=Strict) são verificados à parte, no Set-Cookie.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tests.helpers import SENHA_ADMIN, fazer_app, fazer_settings

USUARIO = "lucas.meira"


def _cliente(hash_admin: str, **kw) -> TestClient:
    settings = fazer_settings(
        env=kw.pop("env", "dev"),
        admin_users={USUARIO: hash_admin},
        cookie_secure=kw.pop("cookie_secure", False),
        **kw,
    )
    return TestClient(fazer_app(settings))


def _login(cliente: TestClient, senha: str = SENHA_ADMIN, usuario: str = USUARIO):
    return cliente.post("/api/auth/login", json={"usuario": usuario, "senha": senha})


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def test_login_correto_devolve_csrf_e_seta_cookie(hash_admin):
    cliente = _cliente(hash_admin)
    r = _login(cliente)
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["usuario"] == USUARIO and corpo["perfil"] == "admin"
    assert len(corpo["csrf_token"]) >= 32
    assert "supra_sessao" in cliente.cookies
    assert SENHA_ADMIN not in r.text


def test_cookie_de_producao_tem_todos_os_atributos_de_seguranca(hash_admin):
    cliente = _cliente(hash_admin, cookie_secure=True)
    r = _login(cliente)
    assert r.status_code == 200
    set_cookie = r.headers["set-cookie"]
    assert set_cookie.startswith("__Host-supra_sessao=")
    baixo = set_cookie.lower()
    assert "httponly" in baixo and "secure" in baixo and "samesite=strict" in baixo
    assert "path=/" in baixo and "domain=" not in baixo   # exigências do prefixo __Host-
    assert "max-age" not in baixo and "expires" not in baixo  # cookie de sessão do navegador


@pytest.mark.parametrize("usuario,senha", [
    (USUARIO, "senha-errada"),
    ("nao.existe", SENHA_ADMIN),
    ("nao.existe", "qualquer"),
    (USUARIO.upper(), SENHA_ADMIN),   # usuário é sensível a maiúsculas/minúsculas
])
def test_login_invalido_da_a_mesma_resposta_generica(hash_admin, usuario, senha):
    cliente = _cliente(hash_admin)
    r = _login(cliente, senha=senha, usuario=usuario)
    assert r.status_code == 401
    assert r.json() == {"detail": "Usuário ou senha inválidos."}
    assert "set-cookie" not in r.headers


def test_login_sem_admins_configurados_nunca_entra():
    settings = fazer_settings(env="dev", cookie_secure=False)  # admin_users vazio
    cliente = TestClient(fazer_app(settings))
    assert _login(cliente).status_code == 401


def test_forca_bruta_bloqueia_ate_a_senha_certa(hash_admin):
    cliente = _cliente(hash_admin)
    for _ in range(5):
        assert _login(cliente, senha="errada").status_code == 401
    r = _login(cliente)  # senha CERTA, mas bloqueado
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0
    assert "supra_sessao" not in cliente.cookies


def test_erro_de_validacao_nao_devolve_a_senha_digitada(hash_admin):
    cliente = _cliente(hash_admin)
    r = cliente.post("/api/auth/login", json={"usuario": "", "senha": "MINHA-SENHA-SECRETA"})
    assert r.status_code == 422
    assert "MINHA-SENHA-SECRETA" not in r.text
    assert "input" not in r.text


def test_senha_gigante_e_rejeitada_sem_passar_pelo_argon2(hash_admin):
    cliente = _cliente(hash_admin)
    r = cliente.post("/api/auth/login", json={"usuario": USUARIO, "senha": "x" * 5000})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Sessão, /me e CSRF
# ---------------------------------------------------------------------------

def test_me_exige_login(hash_admin):
    cliente = _cliente(hash_admin)
    assert cliente.get("/api/auth/me").status_code == 401
    _login(cliente)
    r = cliente.get("/api/auth/me")
    assert r.status_code == 200 and r.json()["usuario"] == USUARIO


def test_cookie_forjado_nao_autentica(hash_admin):
    cliente = _cliente(hash_admin)
    cliente.cookies.set("supra_sessao", "token-inventado-por-um-atacante")
    assert cliente.get("/api/auth/me").status_code == 401


def test_logout_sem_csrf_e_recusado_e_a_sessao_continua(hash_admin):
    cliente = _cliente(hash_admin)
    _login(cliente)
    assert cliente.post("/api/auth/logout").status_code == 403
    assert cliente.post("/api/auth/logout", headers={"X-CSRF-Token": "errado"}).status_code == 403
    assert cliente.get("/api/auth/me").status_code == 200


def test_logout_com_csrf_revoga_a_sessao_de_verdade(hash_admin):
    cliente = _cliente(hash_admin)
    csrf = _login(cliente).json()["csrf_token"]
    token = cliente.cookies.get("supra_sessao")

    assert cliente.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
    assert cliente.get("/api/auth/me").status_code == 401

    # Mesmo que alguém tenha copiado o cookie antes, ele já não vale no servidor.
    outro = TestClient(cliente.app)
    outro.cookies.set("supra_sessao", token)
    assert outro.get("/api/auth/me").status_code == 401


def test_csrf_de_uma_sessao_nao_vale_em_outra(hash_admin):
    a, b = _cliente(hash_admin), _cliente(hash_admin)
    csrf_a = _login(a).json()["csrf_token"]
    _login(b)
    assert b.post("/api/auth/logout", headers={"X-CSRF-Token": csrf_a}).status_code == 403


# ---------------------------------------------------------------------------
# Superfície por ambiente
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("env", ["homolog", "prod"])
def test_rotas_de_administracao_nao_existem_fora_de_dev(hash_admin, env):
    cliente = _cliente(hash_admin, env=env)
    for metodo, rota in [("post", "/api/auth/login"), ("get", "/api/auth/me"), ("post", "/api/auth/logout")]:
        assert getattr(cliente, metodo)(rota).status_code == 404   # 404, não 403: nem revela que existe


@pytest.mark.parametrize("env,enable", [("dev", False), ("dev", None), ("homolog", True), ("prod", True)])
def test_docs_desligados_por_padrao_e_fora_de_dev(hash_admin, env, enable):
    kw = {} if enable is None else {"enable_docs": enable}
    cliente = _cliente(hash_admin, env=env, **kw)
    for rota in ("/docs", "/redoc", "/openapi.json"):
        assert cliente.get(rota).status_code == 404


def test_docs_so_ligam_em_dev_com_enable_docs(hash_admin):
    cliente = _cliente(hash_admin, env="dev", enable_docs=True)
    assert cliente.get("/docs").status_code == 200
    assert cliente.get("/openapi.json").status_code == 200


def test_cabecalhos_de_seguranca_em_rotas_da_api(hash_admin):
    cliente = _cliente(hash_admin)
    r = cliente.get("/api/auth/me")  # mesmo um 401 leva os cabeçalhos
    assert r.headers["Cache-Control"] == "no-store"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]


def test_health_continua_aberto_e_sem_detalhes(hash_admin):
    r = _cliente(hash_admin, env="prod").get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
