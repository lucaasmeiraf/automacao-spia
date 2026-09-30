"""
Testes do handler "campo_anexos" (Resumo do Projeto) com clients mockados — nada real.

Registros no formato que a SUPRA vai devolver depois do pedido de 2026-09-30 (`id_arquivo` em cada item
do Resumo do Projeto) e no formato de hoje (sem `id_arquivo`).
"""
from __future__ import annotations

import io
import json
from unittest.mock import AsyncMock, MagicMock

import openpyxl
import pytest

from app.clients.dnit import ArquivoBaixado, ArquivoInvalido, SupraIndisponivel
from app.processing.campo_anexos import processar_campo_anexos
from app.processing.pipeline import processar_topico
from app.topics import TOPICS

CFG = TOPICS["resumo_projeto"]
RESPOSTA_IA = {"identificador": "Resumo do Projeto", "conforme": "Atenção", "motivo": "Extensão diverge."}


def _xlsx(*linhas) -> bytes:
    wb = openpyxl.Workbook()
    for linha in linhas:
        wb.active.append(linha)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


XLSX_NOVO = ArquivoBaixado(_xlsx(["Extensão", 5.1]), "application/vnd.ms-excel", "Projeto Pavimento 493.xlsx")
XLSX_EXIST = ArquivoBaixado(_xlsx(["km inicial", 324]), "application/octet-stream", "Pista Existente.xlsx")

REGISTROS_HOJE = {"status": True, "resultado": [
    {"id_contrato_obra": "795", "roteiro": "25", "resumo": "<p>O projeto&nbsp;executivo</p>\r\n", "r": "1"},
]}
REGISTROS_COM_ANEXO = {"status": True, "resultado": [
    {"roteiro": "25", "resumo": "<p>Resumo do projeto</p>", "id_arquivo": "900001"},
    {"roteiro": "25", "resumo": "<p>Resumo do projeto</p>", "id_arquivo": "900002"},
    {"roteiro": "25", "resumo": "<p>OAEs: viaduto</p>", "id_arquivo": "None"},  # OAEs: sem anexo
]}


def _ctx(secao=REGISTROS_COM_ANEXO, downloads=(XLSX_NOVO, XLSX_EXIST), resposta=json.dumps(RESPOSTA_IA)):
    ctx = MagicMock()
    ctx.dnit.buscar_secao = AsyncMock(side_effect=secao if isinstance(secao, Exception) else None,
                                      return_value=secao)
    ctx.dnit.baixar_anexo = AsyncMock(side_effect=list(downloads))
    ctx.openai.chat = AsyncMock(side_effect=resposta if isinstance(resposta, Exception) else None,
                                return_value=resposta)
    return ctx


async def _rodar(ctx):
    return await processar_campo_anexos(CFG, "PROMPT JSON", "00 00493/2013", "2025-10-01", "2025-10-31", ctx)


def _user_content(ctx) -> str:
    return ctx.openai.chat.await_args.args[0]["messages"][1]["content"]


# ---------------------------------------------------------------------------
# Montagem do conteúdo enviado à LLM
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_texto_e_bloco_anexos_com_um_anexo_por_id_arquivo():
    ctx = _ctx()
    r = await _rodar(ctx)

    assert r.ok is True
    assert [c.kwargs for c in ctx.dnit.baixar_anexo.await_args_list] == [
        {"nome_arquivo": "", "id_arquivo": "900001"},
        {"nome_arquivo": "", "id_arquivo": "900002"},
    ]
    assert _user_content(ctx) == (
        "Resumo do projeto\n\nOAEs: viaduto\n\n"  # texto repetido entre itens aparece uma vez só
        "ANEXOS\n"
        "[Anexo 1] Projeto Pavimento 493.xlsx\n### Aba: Sheet\nExtensão | 5.1\n[Fim do anexo 1]\n\n"
        "[Anexo 2] Pista Existente.xlsx\n### Aba: Sheet\nkm inicial | 324\n[Fim do anexo 2]"
    )
    body = ctx.openai.chat.await_args.args[0]
    assert body["model"] == CFG.model and body["max_tokens"] == CFG.max_tokens
    assert body["messages"][0] == {"role": "system", "content": "PROMPT JSON"}
    assert body["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_formato_de_hoje_sem_id_arquivo_igual_a_estrategia_campo():
    ctx = _ctx(secao=REGISTROS_HOJE, downloads=())
    r = await _rodar(ctx)

    assert r.ok is True
    ctx.dnit.baixar_anexo.assert_not_awaited()
    assert _user_content(ctx) == "O projeto executivo"  # sem bloco ANEXOS
    assert r.conteudo["infos"] == {"texto": "O projeto executivo", "anexos": []}


@pytest.mark.asyncio
async def test_nome_arquivo_tem_preferencia_e_mesmo_arquivo_nao_repete():
    secao = {"resultado": [
        {"resumo": "x", "id_arquivo": "1", "nome_arquivo": "111_795.xlsx", "nomeOriginalArquivo": "Pav Novo"},
        {"resumo": "y", "id_arquivo": "1", "nome_arquivo": "111_795.xlsx"},
    ]}
    ctx = _ctx(secao=secao, downloads=(XLSX_NOVO,))
    await _rodar(ctx)

    ctx.dnit.baixar_anexo.assert_awaited_once_with("00 00493/2013", nome_arquivo="111_795.xlsx", id_arquivo="1")
    assert "[Anexo 1] Pav Novo\n" in _user_content(ctx)  # nome da SUPRA prevalece sobre o do download


@pytest.mark.asyncio
async def test_secao_vazia_vai_vazia_para_o_prompt_tratar():
    ctx = _ctx(secao={"status": False, "mensagem": "Sem dados", "resultado": None}, downloads=())
    r = await _rodar(ctx)
    assert r.ok is True
    assert _user_content(ctx) == ""


# ---------------------------------------------------------------------------
# Falhas de anexo: o tópico segue e a LLM é avisada
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_anexo_que_nao_baixa_entra_como_nao_lido():
    ctx = _ctx(downloads=(ArquivoInvalido("Arquivo não encontrado"), XLSX_EXIST))
    r = await _rodar(ctx)

    assert r.ok is True
    conteudo = _user_content(ctx)
    assert "[Anexo 1] arquivo 900001\nNão foi possível ler o conteúdo deste anexo (Arquivo não encontrado)." in conteudo
    assert "[Anexo 2] Pista Existente.xlsx\n" in conteudo
    assert r.conteudo["infos"]["anexos"][0]["erro"] == "Arquivo não encontrado"


@pytest.mark.asyncio
async def test_formato_nao_suportado_e_pdf_escaneado():
    pdf_sem_texto = ArquivoBaixado(b"%PDF-1.4\nlixo", "application/pdf", "escaneado.pdf")
    xls_antigo = ArquivoBaixado(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 8, "application/vnd.ms-excel", "a.xls")
    ctx = _ctx(downloads=(pdf_sem_texto, xls_antigo))
    r = await _rodar(ctx)

    assert r.ok is True
    anexos = r.conteudo["infos"]["anexos"]
    assert "PDF ilegível" in anexos[0]["erro"]
    assert "formato antigo" in anexos[1]["erro"]
    assert _user_content(ctx).count("Não foi possível ler") == 2


@pytest.mark.asyncio
async def test_supra_fora_do_ar_no_download_derruba_so_este_topico():
    ctx = _ctx(downloads=(SupraIndisponivel("SUPRA indisponível"),))
    r = await _rodar(ctx)

    assert r.ok is False
    assert "SUPRA indisponível" in r.erro
    ctx.openai.chat.assert_not_awaited()


# ---------------------------------------------------------------------------
# Resposta da LLM e falhas de fetch/LLM
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resposta_json_valida_com_infos():
    r = await _rodar(_ctx())

    assert r.conteudo["conforme"] == "Atenção"
    assert r.conteudo["motivo"] == "Extensão diverge."
    anexo = r.conteudo["infos"]["anexos"][0]
    assert anexo["formato"] == "xlsx" and anexo["conteudo"] == "### Aba: Sheet\nExtensão | 5.1"
    assert anexo["caracteres"] == len(anexo["conteudo"]) and anexo["truncado"] is False


@pytest.mark.asyncio
async def test_resposta_em_texto_puro_vira_objeto_com_erro_parse():
    r = await _rodar(_ctx(resposta='Análise: "conforme": "Não Conforme", "motivo": "Falta tudo"'))

    assert r.ok is True
    assert r.conteudo["erro_parse"] is True
    assert r.conteudo["conforme"] == "Não Conforme"
    assert r.conteudo["identificador"] == "Resumo do Projeto"


@pytest.mark.asyncio
async def test_falha_no_fetch_devolve_ok_false_sem_levantar():
    r = await _rodar(_ctx(secao=RuntimeError("HTTP 500")))
    assert r.ok is False and "HTTP 500" in r.erro


@pytest.mark.asyncio
async def test_falha_na_llm_devolve_ok_false_sem_levantar():
    r = await _rodar(_ctx(resposta=RuntimeError("OpenAI 429")))
    assert r.ok is False and "OpenAI 429" in r.erro


@pytest.mark.asyncio
async def test_pipeline_roteia_resumo_projeto_para_campo_anexos():
    ctx = _ctx()
    r = await processar_topico(CFG, "PROMPT JSON", "00 00493/2013", "2025-10-01", "2025-10-31", ctx)
    assert r.ok is True
    assert ctx.dnit.baixar_anexo.await_count == 2
