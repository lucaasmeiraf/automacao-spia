"""
Testes do handler de imagem (`processar_imagem`) com clients mockados — nada real.

O metadado usa o formato REAL da SUPRA (confirmado em 2026-09-29 para mapa_situacao): `desc_arquivo`
(que vem como o texto "None" quando vazio), `nomeOriginalArquivo` e `ultima_alteracao`.
"""
from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.clients.dnit import ArquivoBaixado, ArquivoInvalido
from app.processing.image import processar_imagem
from app.topics import TOPICS

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 32

META_REAL = {
    "status": True,
    "mensagem": "",
    "resultado": [{
        "id_contrato_obra": "795",
        "roteiro": "12",
        "id_arquivo": "481468",
        "nome_arquivo": "573706884_795.jpg",
        "nomeOriginalArquivo": "Mapa Localização L1",
        "desc_arquivo": "None",
        "pasta_origem": "arquivo",
        "ultima_alteracao": "2024-04-23 14:33:25.000",
    }],
}

# Chaves iguais às do n8n ("Limpa Retorno Mapa de Situação") e às que o prompt pede.
RESPOSTA_IA = {
    "conforme": "Conforme",
    "motivo": "Mapa completo.",
    "elementos_cartograficos": {
        "mapa_brasil": "Presente", "mapa_regional": "Presente", "malha_viaria": "Presente",
        "corpos_dagua": "Presente", "folha_a4_rm2": "Presente",
    },
    "informacoes_legenda": {
        "rodovia": "BR-101", "trecho": "Div. SC/RS", "segmento": "km 0 ao km 50",
        "extensao": "50 km", "codigo_snv": "101BSC0010",
    },
}


def _ctx(meta=META_REAL, download=None, resposta_ia=json.dumps(RESPOSTA_IA)):
    ctx = MagicMock()
    ctx.dnit.buscar_secao = AsyncMock(return_value=meta)
    if isinstance(download, Exception):
        ctx.dnit.download_arquivo = AsyncMock(side_effect=download)
    else:
        ctx.dnit.download_arquivo = AsyncMock(return_value=download or ArquivoBaixado(JPEG, "image/jpeg"))
    ctx.openai.chat = AsyncMock(return_value=resposta_ia)
    return ctx


async def _rodar(ctx, chave="mapa_situacao"):
    return await processar_imagem(TOPICS[chave], "PROMPT", "00 00493/2013", "2025-10-01", "2025-10-31", ctx)


@pytest.mark.asyncio
async def test_fluxo_completo_com_formato_real_da_supra():
    ctx = _ctx()
    r = await _rodar(ctx)

    assert r.ok is True
    ctx.dnit.download_arquivo.assert_awaited_once_with("00 00493/2013", "573706884_795.jpg")

    body = ctx.openai.chat.await_args.args[0]
    assert body["model"] == "gpt-4o"
    imagem, texto = body["messages"][1]["content"]
    assert imagem["image_url"]["url"] == "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()
    assert "Mapa Localização L1" in texto["text"]
    assert "2024-04-23 14:33:25.000" in texto["text"]
    assert "None" not in texto["text"]  # "None" da SUPRA é tratado como vazio

    infos = r.conteudo["infos"]
    assert infos["nomeArquivo"] == "573706884_795.jpg"
    assert infos["nomeOriginal"] == "Mapa Localização L1"
    assert infos["descricao"] == ""
    assert infos["data"] == "2024-04-23 14:33:25.000"
    assert infos["mimeType"] == "image/jpeg"
    assert r.conteudo["conforme"] == "Conforme"
    assert r.conteudo["identificador"] == "Mapa de Situação"


@pytest.mark.asyncio
async def test_diagrama_ocorrencias_usa_o_mesmo_fluxo():
    r = await _rodar(_ctx(), chave="diagrama_ocorrencias")
    assert r.ok is True
    assert r.conteudo["identificador"] == "Diagrama de Ocorrências"


@pytest.mark.asyncio
async def test_download_invalido_vira_fallback_com_o_motivo():
    ctx = _ctx(download=ArquivoInvalido("Arquivo baixado não é JPEG, PNG, GIF nem WEBP."))
    r = await _rodar(ctx)
    assert r.ok is True
    assert r.conteudo["conforme"] == "Atenção"
    assert "não é JPEG" in r.conteudo["motivo"]
    ctx.openai.chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_status_false_na_secao_mostra_a_mensagem_da_supra():
    ctx = _ctx(meta={"status": False, "mensagem": "Nenhum arquivo cadastrado."})
    r = await _rodar(ctx)
    assert r.ok is True
    assert "Nenhum arquivo cadastrado." in r.conteudo["motivo"]
    ctx.dnit.download_arquivo.assert_not_awaited()


@pytest.mark.asyncio
async def test_sem_nome_arquivo_vira_fallback():
    ctx = _ctx(meta={"status": True, "resultado": [{"nome_arquivo": "None"}]})
    r = await _rodar(ctx)
    assert r.ok is True
    assert "não informado" in r.conteudo["motivo"]
    ctx.dnit.download_arquivo.assert_not_awaited()


@pytest.mark.asyncio
async def test_respostas_da_ia_com_chaves_do_n8n_sao_preservadas():
    r = await _rodar(_ctx())
    assert r.conteudo["elementos_cartograficos"] == RESPOSTA_IA["elementos_cartograficos"]
    assert r.conteudo["informacoes_legenda"] == RESPOSTA_IA["informacoes_legenda"]


@pytest.mark.asyncio
async def test_campo_ausente_vira_nao_identificado_e_extra_e_mantido():
    resposta = {"conforme": "Atenção", "motivo": "x",
                "elementos_cartograficos": {"mapa_brasil": "Presente", "escala": "1:50.000"}}
    r = await _rodar(_ctx(resposta_ia=json.dumps(resposta)))
    ec = r.conteudo["elementos_cartograficos"]
    assert ec["mapa_brasil"] == "Presente"
    assert ec["malha_viaria"] == "Não identificado"
    assert ec["escala"] == "1:50.000"
    assert r.conteudo["informacoes_legenda"]["codigo_snv"] == "Não identificado"


@pytest.mark.asyncio
async def test_resposta_em_bloco_markdown_json_e_interpretada():
    resposta = "```json\n" + json.dumps(RESPOSTA_IA, ensure_ascii=False) + "\n```"
    r = await _rodar(_ctx(resposta_ia=resposta))
    assert r.conteudo["conforme"] == "Conforme"
    assert r.conteudo["informacoes_legenda"]["rodovia"] == "BR-101"


@pytest.mark.asyncio
async def test_json_quebrado_recupera_campos_por_regex_como_o_n8n():
    quebrado = '{"conforme": "Não Conforme", "motivo": "Falta legenda", "mapa_brasil": "Ausente", '
    r = await _rodar(_ctx(resposta_ia=quebrado))
    assert r.conteudo["conforme"] == "Não Conforme"
    assert r.conteudo["motivo"] == "Falta legenda"
    assert r.conteudo["elementos_cartograficos"]["mapa_brasil"] == "Ausente"
    assert r.conteudo["elementos_cartograficos"]["mapa_regional"] == "Não identificado"


@pytest.mark.asyncio
async def test_resposta_da_ia_sem_json_vira_atencao_com_infos():
    r = await _rodar(_ctx(resposta_ia="desculpe, não consegui"))
    assert r.ok is True
    assert r.conteudo["conforme"] == "Atenção"
    assert r.conteudo["motivo"] == "Erro ao interpretar resposta da IA."
    assert r.conteudo["infos"]["nomeArquivo"] == "573706884_795.jpg"


@pytest.mark.asyncio
async def test_estrutura_do_diagrama_igual_a_do_n8n():
    r = await _rodar(_ctx(resposta_ia="{}"), chave="diagrama_ocorrencias")
    assert set(r.conteudo["pontos_passagem"]) == {
        "municipios", "travessias_urbanas", "entroncamentos", "oaes", "rios"}
    assert set(r.conteudo["ocorrencias_projeto"]) == {
        "jazidas_pedreiras", "usinas_canteiros", "areas_emprestimo_botafora"}
    assert set(r.conteudo["apresentacao"]) == {"diagrama_unifilar", "legenda", "quilometragem"}


@pytest.mark.asyncio
async def test_falha_de_rede_vira_ok_false_sem_levantar():
    ctx = _ctx(download=RuntimeError("SUPRA recusou o token"))
    r = await _rodar(ctx)
    assert r.ok is False
    assert "recusou o token" in r.erro
