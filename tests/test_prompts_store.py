"""
Testes dos prompts em arquivo (prompts/<chave>.md).

Cobre: leitura, arquivo ausente/vazio, e a defesa contra path traversal (a chave só vale se
for um tópico conhecido).
"""
from __future__ import annotations

import pytest

from app.prompts_store import PROMPT_MAX_CARACTERES, carregar_prompt, salvar_prompt


@pytest.mark.asyncio
async def test_carrega_prompt_existente_sem_espacos_nas_pontas(tmp_path):
    (tmp_path / "justificativa.md").write_text("\n  Você é um auditor.  \n", encoding="utf-8")
    assert await carregar_prompt("justificativa", str(tmp_path)) == "Você é um auditor."


@pytest.mark.asyncio
async def test_le_utf8_com_acentos(tmp_path):
    (tmp_path / "historico.md").write_text("Análise crítica — Atenção", encoding="utf-8")
    assert await carregar_prompt("historico", str(tmp_path)) == "Análise crítica — Atenção"


@pytest.mark.asyncio
async def test_arquivo_ausente_devolve_none(tmp_path):
    assert await carregar_prompt("justificativa", str(tmp_path)) is None


@pytest.mark.asyncio
async def test_arquivo_vazio_devolve_none(tmp_path):
    (tmp_path / "justificativa.md").write_text("  \n\n", encoding="utf-8")
    assert await carregar_prompt("justificativa", str(tmp_path)) is None


@pytest.mark.asyncio
async def test_diretorio_inexistente_devolve_none(tmp_path):
    assert await carregar_prompt("justificativa", str(tmp_path / "nao_existe")) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("chave", [
    "topico_que_nao_existe",
    "../segredo",
    "..\\segredo",
    "../../.env",
    "justificativa/../../segredo",
    "README",
    "",
])
async def test_chave_desconhecida_ou_traversal_nunca_le_arquivo(tmp_path, chave):
    # Existe um arquivo "vizinho" que jamais pode ser lido via chave maliciosa.
    (tmp_path.parent / "segredo.md").write_text("SEGREDO", encoding="utf-8")
    (tmp_path / "README.md").write_text("não é prompt", encoding="utf-8")
    assert await carregar_prompt(chave, str(tmp_path)) is None


# ---------------------------------------------------------------------------
# salvar_prompt (API de configuração)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_salvar_prompt_grava_e_normaliza(tmp_path):
    await salvar_prompt("justificativa", str(tmp_path), "  Linha 1\r\nLinha 2  \r\n")
    assert (tmp_path / "justificativa.md").read_bytes() == b"Linha 1\nLinha 2\n"
    assert await carregar_prompt("justificativa", str(tmp_path)) == "Linha 1\nLinha 2"
    # Gravação atômica: nenhum arquivo temporário sobra no diretório.
    assert [p.name for p in tmp_path.iterdir()] == ["justificativa.md"]


@pytest.mark.asyncio
async def test_salvar_prompt_cria_diretorio(tmp_path):
    await salvar_prompt("historico", str(tmp_path / "novo"), "P")
    assert (tmp_path / "novo" / "historico.md").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("chave", ["topico_que_nao_existe", "../segredo", "../../.env", ""])
async def test_salvar_prompt_chave_invalida_nunca_grava(tmp_path, chave):
    with pytest.raises(ValueError):
        await salvar_prompt(chave, str(tmp_path / "prompts"), "conteúdo")
    assert not any(tmp_path.rglob("*.md"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "texto", ["", "  \r\n ", "x" * (PROMPT_MAX_CARACTERES + 1)], ids=["vazio", "espacos", "gigante"]
)
async def test_salvar_prompt_vazio_ou_gigante(tmp_path, texto):
    with pytest.raises(ValueError):
        await salvar_prompt("justificativa", str(tmp_path), texto)
    assert not (tmp_path / "justificativa.md").exists()
