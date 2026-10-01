"""
Testes do cliente SUPRA (`DnitClient`) com servidor simulado (httpx.MockTransport — nada real).

Cobrem a proteção contra "502 Proxy Error" (limite de simultaneidade + nova tentativa em
502/503/504) e, principalmente, que NADA mudou no que é enviado: URL, parâmetros (inclusive o
`periodo_inicio` — o antigo typo `periodo_incio` era ignorado pela SUPRA), headers e o JSON devolvido.
"""
from __future__ import annotations

import asyncio
import base64

import httpx
import pytest

from app.clients.dnit import ArquivoInvalido, DnitClient, SupraIndisponivel, SupraTokenRecusado
from tests.helpers import fazer_settings

BASE = "https://supra.teste/index_cgcont_common.php/cgcont/ai"

# Só as assinaturas importam para a detecção do tipo.
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00" + b"\x00" * 32
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def _cliente(handler, **kw) -> tuple[DnitClient, httpx.AsyncClient]:
    settings = fazer_settings(dnit_base_url=BASE, dnit_token="TOKEN-TESTE", dnit_retry_espera=0, **kw)
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return DnitClient(settings, http), http


def _roteiro(*respostas):
    """Handler que devolve as respostas em sequência e registra as requisições."""
    chamadas: list[httpx.Request] = []
    fila = list(respostas)

    async def handler(req: httpx.Request) -> httpx.Response:
        chamadas.append(req)
        status, corpo = fila.pop(0) if len(fila) > 1 else fila[0]
        return httpx.Response(status, json=corpo) if corpo is not None else httpx.Response(status, text="<html>erro</html>")

    return handler, chamadas


# ---------------------------------------------------------------------------
# Nada mudou no que é enviado
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_requisicao_identica_a_de_antes():
    handler, chamadas = _roteiro((200, {"status": True, "resultado": [{"resumo": "x"}]}))
    dnit, http = _cliente(handler)
    async with http:
        dados = await dnit.buscar_secao("justificativa", "00 00493/2013", "2025-10-01", "2025-10-31")

    assert dados == {"status": True, "resultado": [{"resumo": "x"}]}
    (req,) = chamadas
    assert req.method == "GET"
    assert req.url.path.endswith("/cgcont/ai/relatorio/secao_ws/justificativa")
    assert dict(req.url.params) == {
        "contrato": "00 00493/2013",
        "periodo_inicio": "2025-10-01",  # NÃO é "periodo_incio": a SUPRA ignorava o typo (2026-10-01)
        "periodo_fim": "2025-10-31",
    }
    assert req.headers["token"] == "TOKEN-TESTE"
    assert req.headers["accept"] == "application/json"


@pytest.mark.asyncio
async def test_resposta_status_false_passa_adiante_sem_nova_tentativa():
    # Recusa lógica da SUPRA (HTTP 200): o comportamento continua o mesmo — devolve o JSON.
    handler, chamadas = _roteiro((200, {"status": False, "mensagem": "Token inválido."}))
    dnit, http = _cliente(handler)
    async with http:
        dados = await dnit.buscar_secao("capa", "c", "a", "b")
    assert dados == {"status": False, "mensagem": "Token inválido."}
    assert len(chamadas) == 1


@pytest.mark.asyncio
async def test_download_arquivo_mesmos_parametros():
    handler, chamadas = _roteiro((200, {"status": True, "resultado": base64.b64encode(PNG).decode()}))
    dnit, http = _cliente(handler)
    async with http:
        await dnit.download_arquivo("00 00493/2013", "mapa.png")
    (req,) = chamadas
    assert req.url.path.endswith("/arquivo/download_ws")
    assert dict(req.url.params) == {"contrato": "00 00493/2013", "nome_arquivo": "mapa.png"}
    assert req.headers["token"] == "TOKEN-TESTE"


# ---------------------------------------------------------------------------
# Download: formatos aceitos (o formato real do download_ws ainda não foi confirmado)
# ---------------------------------------------------------------------------

def _download(resposta: httpx.Response):
    async def handler(req: httpx.Request) -> httpx.Response:
        return resposta
    return _cliente(handler)


@pytest.mark.asyncio
async def test_download_binario_vira_base64_no_python():
    dnit, http = _download(httpx.Response(200, content=JPEG, headers={"content-type": "image/jpeg"}))
    async with http:
        arquivo = await dnit.download_arquivo("c", "573706884_795.jpg")
    assert arquivo.conteudo == JPEG
    assert arquivo.mime_type == "image/jpeg"
    assert arquivo.data_uri == "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()


@pytest.mark.asyncio
async def test_download_binario_com_content_type_generico_e_detectado_pelos_bytes():
    dnit, http = _download(httpx.Response(200, content=PNG, headers={"content-type": "application/octet-stream"}))
    async with http:
        arquivo = await dnit.download_arquivo("c", "x")
    assert arquivo.mime_type == "image/png"


@pytest.mark.asyncio
async def test_download_no_formato_do_n8n():
    # Nó "Download das Imagens" (responseFormat=json) + "Payload Mapa de Situação": resultado.base64/mime_type.
    corpo = {"status": True, "resultado": {"base64": base64.b64encode(JPEG).decode(), "mime_type": "image/jpeg"}}
    dnit, http = _download(httpx.Response(200, json=corpo))
    async with http:
        arquivo = await dnit.download_arquivo("c", "573706884_795.jpg")
    assert arquivo.conteudo == JPEG
    assert arquivo.data_uri == "data:image/jpeg;base64," + corpo["resultado"]["base64"]


@pytest.mark.asyncio
@pytest.mark.parametrize("corpo", [
    {"status": True, "resultado": base64.b64encode(JPEG).decode()},
    {"status": True, "resultado": {"base64": base64.b64encode(JPEG).decode(), "mime_type": "image/png"}},
    {"status": True, "resultado": [{"arquivo": "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()}]},
])
async def test_download_json_com_base64(corpo):
    dnit, http = _download(httpx.Response(200, json=corpo))
    async with http:
        arquivo = await dnit.download_arquivo("c", "x")
    assert arquivo.conteudo == JPEG
    assert arquivo.mime_type == "image/jpeg"  # vale o que os bytes dizem, não o mime_type informado


@pytest.mark.asyncio
@pytest.mark.parametrize("resposta, trecho", [
    (httpx.Response(200, json={"status": False, "mensagem": "Arquivo não encontrado."}), "Arquivo não encontrado."),
    (httpx.Response(200, text="<html>erro</html>", headers={"content-type": "text/html"}), "text/html"),
    (httpx.Response(200, json={"status": True, "resultado": base64.b64encode(b"%PDF-1.4 ...").decode()}), "não é JPEG"),
    (httpx.Response(200, json={"status": True, "resultado": "!!!não é base64!!!"}), "base64"),
])
async def test_download_invalido_levanta_erro_claro(resposta, trecho):
    dnit, http = _download(resposta)
    async with http:
        with pytest.raises(ArquivoInvalido, match=trecho):
            await dnit.download_arquivo("c", "x")


# ---------------------------------------------------------------------------
# Token recusado: a SUPRA redireciona (307) para a página inicial
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("metodo", ["secao", "download"])
async def test_redirecionamento_vira_token_recusado_sem_nova_tentativa(metodo):
    chamadas = []

    async def handler(req: httpx.Request) -> httpx.Response:
        chamadas.append(req)
        return httpx.Response(307, headers={"location": "https://supra.dnit.gov.br/"})

    dnit, http = _cliente(handler)
    async with http:
        with pytest.raises(SupraTokenRecusado, match="DNIT_TOKEN"):
            if metodo == "secao":
                await dnit.buscar_secao("mapa_situacao", "c", "a", "b")
            else:
                await dnit.download_arquivo("c", "x")
    assert len(chamadas) == 1


# ---------------------------------------------------------------------------
# Nova tentativa em 502/503/504
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.parametrize("status", [502, 503, 504])
async def test_erro_de_gateway_e_repetido_e_depois_funciona(status):
    handler, chamadas = _roteiro((status, None), (200, {"status": True, "resultado": []}))
    dnit, http = _cliente(handler)
    async with http:
        dados = await dnit.buscar_secao("historico", "c", "a", "b")
    assert dados == {"status": True, "resultado": []}
    assert len(chamadas) == 2


@pytest.mark.asyncio
async def test_502_persistente_falha_depois_das_tentativas():
    handler, chamadas = _roteiro((502, None))
    dnit, http = _cliente(handler, dnit_retries=2)
    async with http:
        with pytest.raises(httpx.HTTPStatusError):
            await dnit.buscar_secao("rpfo", "c", "a", "b")
    assert len(chamadas) == 3  # 1 + 2 novas tentativas


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 401, 404, 500])
async def test_outros_erros_falham_na_hora_como_antes(status):
    handler, chamadas = _roteiro((status, {"erro": "x"}))
    dnit, http = _cliente(handler)
    async with http:
        with pytest.raises(httpx.HTTPStatusError):
            await dnit.buscar_secao("oaes", "c", "a", "b")
    assert len(chamadas) == 1


@pytest.mark.asyncio
async def test_conexao_derrubada_e_repetida_e_depois_funciona():
    chamadas = []

    async def handler(req: httpx.Request) -> httpx.Response:
        chamadas.append(req)
        if len(chamadas) < 3:
            raise httpx.ConnectError("[Errno 104] Connection reset by peer", request=req)
        return httpx.Response(200, json={"status": True, "resultado": []})

    dnit, http = _cliente(handler, dnit_retries=2)
    async with http:
        dados = await dnit.buscar_secao("historico", "c", "a", "b")
    assert dados == {"status": True, "resultado": []}
    assert len(chamadas) == 3


@pytest.mark.asyncio
async def test_conexao_derrubada_persistente_falha_depois_das_tentativas():
    chamadas = []

    async def handler(req: httpx.Request) -> httpx.Response:
        chamadas.append(req)
        raise httpx.ReadError("Connection reset by peer", request=req)

    dnit, http = _cliente(handler, dnit_retries=2)
    async with http:
        with pytest.raises(SupraIndisponivel, match="3 tentativa.*ReadError"):
            await dnit.buscar_secao("rpfo", "c", "a", "b")
    assert len(chamadas) == 3


@pytest.mark.asyncio
async def test_travamento_usa_o_timeout_da_supra_e_e_repetido():
    chamadas = []

    async def handler(req: httpx.Request) -> httpx.Response:
        chamadas.append(req)
        if len(chamadas) == 1:
            raise httpx.ReadTimeout("sem dados", request=req)
        return httpx.Response(200, json={"status": True, "resultado": []})

    dnit, http = _cliente(handler, dnit_timeout=15)
    async with http:
        await dnit.buscar_secao("mapa_situacao", "c", "a", "b")
    assert len(chamadas) == 2
    assert chamadas[0].extensions["timeout"] == {"connect": 10.0, "read": 15, "write": 15, "pool": 15}


@pytest.mark.asyncio
async def test_retries_zero_desliga_novas_tentativas():
    handler, chamadas = _roteiro((502, None))
    dnit, http = _cliente(handler, dnit_retries=0)
    async with http:
        with pytest.raises(httpx.HTTPStatusError):
            await dnit.buscar_secao("rpfo", "c", "a", "b")
    assert len(chamadas) == 1


# ---------------------------------------------------------------------------
# Limite de simultaneidade
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_maximo_n_requisicoes_simultaneas_e_todas_concluem():
    em_curso = 0
    pico = 0

    async def handler(req: httpx.Request) -> httpx.Response:
        nonlocal em_curso, pico
        em_curso += 1
        pico = max(pico, em_curso)
        await asyncio.sleep(0.02)
        em_curso -= 1
        return httpx.Response(200, json={"status": True, "endpoint": req.url.path.rsplit("/", 1)[-1]})

    dnit, http = _cliente(handler, dnit_max_concorrencia=4)
    endpoints = [f"secao{i}" for i in range(15)]
    async with http:
        resultados = await asyncio.gather(*(dnit.buscar_secao(e, "c", "a", "b") for e in endpoints))

    assert pico == 4
    assert [r["endpoint"] for r in resultados] == endpoints  # todas concluem, cada uma com o seu dado


def test_configuracao_invalida_e_recusada():
    for kw in ({"dnit_max_concorrencia": 0}, {"dnit_retries": -1}, {"dnit_retry_espera": -1},
               {"dnit_timeout": 1}):
        with pytest.raises(ValueError):
            fazer_settings(**kw)


# ---------------------------------------------------------------------------
# baixar_anexo — qualquer tipo de arquivo (anexos lidos por ETL)
# Formato real (2026-09-30): pdf/xlsx em binário com Content-Disposition; erro em JSON status=false.
# ---------------------------------------------------------------------------

XLSX_CT = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _servidor_de_arquivo(resposta: httpx.Response):
    chamadas: list[httpx.Request] = []

    async def handler(req: httpx.Request) -> httpx.Response:
        chamadas.append(req)
        return resposta

    return handler, chamadas


@pytest.mark.asyncio
async def test_baixar_anexo_binario_com_nome_original():
    resp = httpx.Response(200, content=b"PK\x03\x04planilha", headers={
        "content-type": XLSX_CT, "content-disposition": 'attachment; filename="Projeto Pavimento 493.xlsx"',
    })
    handler, chamadas = _servidor_de_arquivo(resp)
    dnit, http = _cliente(handler)
    async with http:
        arq = await dnit.baixar_anexo("00 00493/2013", nome_arquivo="397621236_795.xlsx")

    assert (arq.conteudo, arq.mime_type, arq.nome) == (b"PK\x03\x04planilha", XLSX_CT, "Projeto Pavimento 493.xlsx")
    (req,) = chamadas
    assert req.url.path.endswith("/cgcont/ai/arquivo/download_ws")
    assert dict(req.url.params) == {"contrato": "00 00493/2013", "nome_arquivo": "397621236_795.xlsx"}
    assert req.headers["token"] == "TOKEN-TESTE"


@pytest.mark.asyncio
async def test_baixar_anexo_por_id_arquivo_quando_nao_ha_nome():
    handler, chamadas = _servidor_de_arquivo(httpx.Response(200, content=b"%PDF-1.4", headers={"content-type": "application/pdf"}))
    dnit, http = _cliente(handler)
    async with http:
        arq = await dnit.baixar_anexo("00 00493/2013", id_arquivo="481468")

    assert arq.mime_type == "application/pdf" and arq.nome == ""
    assert dict(chamadas[0].url.params) == {"contrato": "00 00493/2013", "id_arquivo": "481468"}


@pytest.mark.asyncio
async def test_baixar_anexo_prefere_nome_arquivo():
    handler, chamadas = _servidor_de_arquivo(httpx.Response(200, content=b"x", headers={"content-type": "text/plain"}))
    dnit, http = _cliente(handler)
    async with http:
        await dnit.baixar_anexo("C", nome_arquivo="a.txt", id_arquivo="1")
    assert dict(chamadas[0].url.params) == {"contrato": "C", "nome_arquivo": "a.txt"}


@pytest.mark.asyncio
async def test_baixar_anexo_sem_identificacao_nao_chama_a_supra():
    handler, chamadas = _servidor_de_arquivo(httpx.Response(200))
    dnit, http = _cliente(handler)
    async with http:
        with pytest.raises(ValueError):
            await dnit.baixar_anexo("C")
    assert chamadas == []


@pytest.mark.asyncio
async def test_baixar_anexo_imagem_em_json_base64():
    corpo = {"status": True, "resultado": {"base64": base64.b64encode(PNG).decode(), "mime_type": "image/png"}}
    handler, _ = _servidor_de_arquivo(httpx.Response(200, json=corpo))
    dnit, http = _cliente(handler)
    async with http:
        arq = await dnit.baixar_anexo("C", nome_arquivo="foto.png")
    assert (arq.conteudo, arq.mime_type) == (PNG, "image/png")


@pytest.mark.asyncio
@pytest.mark.parametrize("resposta, trecho", [
    (httpx.Response(200, json={"status": False, "mensagem": "Arquivo não encontrado para este contrato (nome_arquivo).",
                               "resultado": None}), "Arquivo não encontrado"),
    (httpx.Response(200, content=b"", headers={"content-type": "application/pdf"}), "vazio"),
    (httpx.Response(200, json={"status": True, "resultado": {}}), "sem o conteúdo"),
])
async def test_baixar_anexo_erros_claros(resposta, trecho):
    handler, _ = _servidor_de_arquivo(resposta)
    dnit, http = _cliente(handler)
    async with http:
        with pytest.raises(ArquivoInvalido, match=trecho):
            await dnit.baixar_anexo("C", nome_arquivo="x")


@pytest.mark.asyncio
async def test_baixar_anexo_nome_utf8_no_content_disposition():
    resp = httpx.Response(200, content=b"%PDF", headers={
        "content-type": "application/pdf", "content-disposition": "attachment; filename*=UTF-8''Proj%C3%A9to.pdf",
    })
    handler, _ = _servidor_de_arquivo(resp)
    dnit, http = _cliente(handler)
    async with http:
        arq = await dnit.baixar_anexo("C", nome_arquivo="x")
    assert arq.nome == "Projéto.pdf"
