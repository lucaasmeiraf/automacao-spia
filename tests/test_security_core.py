"""
Testes das peças de segurança isoladas: senhas (argon2), sessões e limitador de tentativas.
"""
from __future__ import annotations

import hashlib

import pytest

from app.security.passwords import gerar_hash, verificar, verificar_async
from app.security.sessions import SessionStore
from app.security.throttle import Limitador


class Relogio:
    """Relógio falso e controlável."""

    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def avancar(self, seg: float) -> None:
        self.t += seg


# ---------------------------------------------------------------------------
# Senhas
# ---------------------------------------------------------------------------

def test_hash_e_argon2id_e_nao_contem_a_senha(hash_admin):
    assert hash_admin.startswith("$argon2id$")
    assert "senha-de-teste" not in hash_admin


def test_hashes_da_mesma_senha_sao_diferentes_por_causa_do_sal():
    assert gerar_hash("mesma-senha-longa") != gerar_hash("mesma-senha-longa")


def test_verificar_senha_certa_e_errada(hash_admin):
    assert verificar(hash_admin, "senha-de-teste-bem-longa") is True
    assert verificar(hash_admin, "senha-de-teste-bem-longA") is False
    assert verificar(hash_admin, "") is False


@pytest.mark.parametrize("lixo", ["", "abc", "$argon2id$corrompido", "senha-em-texto-puro"])
def test_hash_invalido_nunca_autentica(lixo):
    assert verificar(lixo, "qualquer") is False


@pytest.mark.asyncio
async def test_verificar_async_usuario_inexistente_devolve_false():
    assert await verificar_async(None, "qualquer-coisa") is False


@pytest.mark.asyncio
async def test_verificar_async_usuario_existente(hash_admin):
    assert await verificar_async(hash_admin, "senha-de-teste-bem-longa") is True
    assert await verificar_async(hash_admin, "errada") is False


# ---------------------------------------------------------------------------
# Sessões
# ---------------------------------------------------------------------------

def _store(relogio, **kw):
    return SessionStore(inatividade_seg=600, duracao_max_seg=3600, relogio=relogio, **kw)


def test_sessao_criada_pode_ser_obtida_e_tem_csrf():
    s = _store(Relogio())
    token, sessao = s.criar("lucas")
    assert s.obter(token) is sessao
    assert sessao.usuario == "lucas" and sessao.perfil == "admin"
    assert len(sessao.csrf) >= 32 and sessao.csrf != token


def test_token_nao_e_guardado_em_claro():
    s = _store(Relogio())
    token, _ = s.criar("lucas")
    assert token not in s._sessoes
    assert hashlib.sha256(token.encode()).hexdigest() in s._sessoes


def test_tokens_e_csrf_sao_unicos():
    s = _store(Relogio())
    (t1, s1), (t2, s2) = s.criar("a"), s.criar("a")
    assert t1 != t2 and s1.csrf != s2.csrf


@pytest.mark.parametrize("token", [None, "", "inventado", "a" * 43])
def test_token_invalido_nao_da_sessao(token):
    assert _store(Relogio()).obter(token) is None


def test_expira_por_inatividade_mas_uso_renova():
    rel = Relogio()
    s = _store(rel)
    token, _ = s.criar("lucas")
    rel.avancar(500)
    assert s.obter(token) is not None      # ainda dentro de 600s; renova
    rel.avancar(500)
    assert s.obter(token) is not None      # 500s desde o último uso
    rel.avancar(601)
    assert s.obter(token) is None          # ficou inativa


def test_expira_por_duracao_absoluta_mesmo_com_uso_constante():
    rel = Relogio()
    s = _store(rel)
    token, _ = s.criar("lucas")
    for _ in range(7):                     # 7 x 500s = 3500s: sempre ativa
        rel.avancar(500)
        assert s.obter(token) is not None
    rel.avancar(500)                       # 4000s > 3600s absolutos
    assert s.obter(token) is None


def test_revogar_invalida_o_token():
    s = _store(Relogio())
    token, _ = s.criar("lucas")
    s.revogar(token)
    assert s.obter(token) is None
    s.revogar(None)  # não quebra


def test_teto_de_sessoes_descarta_a_mais_antiga():
    rel = Relogio()
    s = _store(rel, max_sessoes=3)
    tokens = []
    for i in range(4):
        rel.avancar(1)
        tokens.append(s.criar(f"u{i}")[0])
    assert s.obter(tokens[0]) is None
    assert all(s.obter(t) is not None for t in tokens[1:])


# ---------------------------------------------------------------------------
# Limitador de tentativas
# ---------------------------------------------------------------------------

def test_bloqueia_apos_max_falhas_e_libera_com_o_tempo():
    rel = Relogio()
    lim = Limitador(max_falhas=3, base_seg=10, relogio=rel)
    for _ in range(2):
        lim.falha("k")
    assert lim.espera("k") == 0
    lim.falha("k")                         # 3ª falha => bloqueio
    assert lim.espera("k") == 10
    rel.avancar(10)
    assert lim.espera("k") == 0


def test_bloqueio_dobra_a_cada_falha_ate_o_teto():
    rel = Relogio()
    lim = Limitador(max_falhas=2, base_seg=10, teto_seg=50, relogio=rel)
    esperas = []
    for _ in range(5):
        lim.falha("k")
        esperas.append(lim.espera("k"))
        rel.avancar(esperas[-1])           # espera o bloqueio passar e erra de novo
    assert esperas == [0, 10, 20, 40, 50]  # 10, 20, 40, e teto de 50


def test_sucesso_zera_a_chave():
    lim = Limitador(max_falhas=2, base_seg=10, relogio=Relogio())
    lim.falha("k")
    lim.falha("k")
    assert lim.espera("k") > 0
    lim.sucesso("k")
    assert lim.espera("k") == 0


def test_chaves_sao_independentes():
    lim = Limitador(max_falhas=1, base_seg=10, relogio=Relogio())
    lim.falha("ip:1.1.1.1")
    assert lim.espera("ip:1.1.1.1") > 0
    assert lim.espera("ip:2.2.2.2") == 0


def test_falhas_antigas_sao_esquecidas():
    rel = Relogio()
    lim = Limitador(max_falhas=3, base_seg=10, janela_seg=100, relogio=rel)
    lim.falha("k")
    lim.falha("k")
    rel.avancar(101)                       # fora da janela: contagem recomeça
    lim.falha("k")
    assert lim.espera("k") == 0


def test_poda_nao_deixa_o_dicionario_crescer_sem_limite():
    rel = Relogio()
    lim = Limitador(max_falhas=5, janela_seg=10, relogio=rel, max_chaves=50)
    for i in range(50):
        lim.falha(f"k{i}")
    rel.avancar(20)
    lim.falha("nova")                      # dispara a poda das antigas
    assert len(lim._estados) < 50
