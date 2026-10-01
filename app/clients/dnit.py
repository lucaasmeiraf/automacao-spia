"""
Cliente da API do SUPRA/DNIT.

Equivale aos nós HTTP Request que buscam os dados de cada tópico
(ex.: .../secao_ws/justificativa) e ao download de imagens.

Proteção do servidor da SUPRA (2026-09-28): com ~15 chamadas simultâneas o proxy da SUPRA
devolve "502 Proxy Error" para algumas; uma a uma, todas funcionam. Por isso:
  - no máximo `dnit_max_concorrencia` requisições simultâneas à SUPRA (as demais aguardam a vez);
  - 502/503/504 são repetidos até `dnit_retries` vezes, com espera crescente. Só GETs de leitura:
    repetir não altera nada no SUPRA. Outros erros (401, 404, 500…) falham na hora, como antes.
Os dados, parâmetros e headers enviados são exatamente os mesmos de antes.

Conexão derrubada (2026-09-29): a partir da VPS, a SUPRA às vezes reseta a conexão já no handshake TLS
("Connection reset by peer"), em rajadas de alguns segundos, ou trava no meio da resposta. Falhas de
transporte também entram nas novas tentativas, com a mesma espera crescente; travamento é detectado por
`dnit_timeout` (segundos sem dados), bem menor que o HTTP_TIMEOUT geral. Esgotadas as tentativas, vira
`SupraIndisponivel` com mensagem clara.

Token recusado: a SUPRA não responde 401 — redireciona (307) para a página inicial, com corpo vazio.
Isso vira `SupraTokenRecusado`, com mensagem clara, em vez de um erro genérico de redirecionamento.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import logging
import re
from dataclasses import dataclass
from urllib.parse import unquote

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)

# Erros de gateway/proxy: indicam sobrecarga momentânea, não um problema na requisição.
_STATUS_REPETIVEIS = frozenset({502, 503, 504})

# Formatos aceitos pela visão da OpenAI, identificados pela assinatura (magic bytes) do arquivo.
_ASSINATURAS_IMAGEM: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)

# Campos onde o base64 pode vir, caso o download_ws responda em JSON.
_CAMPOS_BASE64 = ("base64", "arquivo", "conteudo", "content", "data", "file")


class SupraTokenRecusado(RuntimeError):
    """A SUPRA redirecionou para o login: o DNIT_TOKEN está vencido, inválido ou a senha mudou."""


class SupraIndisponivel(RuntimeError):
    """A SUPRA derrubou/travou a conexão em todas as tentativas."""


class ArquivoInvalido(ValueError):
    """O download_ws respondeu algo que não é uma imagem utilizável."""


@dataclass(frozen=True)
class ArquivoBaixado:
    conteudo: bytes
    mime_type: str
    # Nome original do arquivo (Content-Disposition), quando a SUPRA informa. Só em `baixar_anexo`.
    nome: str = ""

    @property
    def base64(self) -> str:
        return base64.b64encode(self.conteudo).decode("ascii")

    @property
    def data_uri(self) -> str:
        return f"data:{self.mime_type};base64,{self.base64}"


def detectar_mime_imagem(conteudo: bytes) -> str | None:
    """Tipo da imagem pela assinatura dos bytes (não confia no nome nem no Content-Type)."""
    for assinatura, mime in _ASSINATURAS_IMAGEM:
        if conteudo.startswith(assinatura):
            return mime
    if conteudo[:4] == b"RIFF" and conteudo[8:12] == b"WEBP":
        return "image/webp"
    return None


def _base64_do_json(dados: object) -> str | None:
    """Procura o base64 numa resposta JSON: `resultado` como texto ou como objeto com um campo conhecido."""
    if isinstance(dados, dict):
        if dados.get("status") is False:
            raise ArquivoInvalido(f"SUPRA recusou o download: {dados.get('mensagem') or 'sem mensagem'}")
        resultado = dados.get("resultado", dados)
    else:
        resultado = dados
    if isinstance(resultado, list) and resultado:
        resultado = resultado[0]
    if isinstance(resultado, str):
        return resultado
    if isinstance(resultado, dict):
        for campo in _CAMPOS_BASE64:
            valor = resultado.get(campo)
            if isinstance(valor, str) and valor:
                return valor
    return None


def interpretar_download(resp: httpx.Response) -> ArquivoBaixado:
    """
    Formato do download_ws (pelo fluxo n8n, nó "Download das Imagens" com responseFormat=json):
        {"resultado": {"base64": "...", "mime_type": "image/jpeg"}}
    Por tolerância, aceita também o arquivo binário cru e base64 como texto em `resultado` (com ou sem
    prefixo `data:...;base64,`). O tipo é sempre confirmado pelos bytes da imagem.
    """
    conteudo = resp.content
    if detectar_mime_imagem(conteudo) is None:
        try:
            dados = resp.json()
        except ValueError:
            dados = None
        texto = _base64_do_json(dados) if dados is not None else None
        if not texto:
            tipo = resp.headers.get("content-type", "desconhecido")
            raise ArquivoInvalido(f"download_ws não devolveu uma imagem (Content-Type: {tipo}).")
        if texto.startswith("data:") and "," in texto:
            texto = texto.split(",", 1)[1]
        try:
            conteudo = base64.b64decode(texto, validate=False)
        except (binascii.Error, ValueError) as exc:
            raise ArquivoInvalido("download_ws devolveu um base64 inválido.") from exc

    mime = detectar_mime_imagem(conteudo)
    if mime is None:
        raise ArquivoInvalido("Arquivo baixado não é JPEG, PNG, GIF nem WEBP.")
    return ArquivoBaixado(conteudo=conteudo, mime_type=mime)


_FILENAME_RE = re.compile(r"filename\*=(?:UTF-8'')?([^;]+)|filename=\"?([^\";]+)\"?", re.IGNORECASE)


def _nome_do_content_disposition(valor: str) -> str:
    """`attachment; filename="Projeto 493.xlsx"` → `Projeto 493.xlsx` (aceita também `filename*=UTF-8''...`)."""
    m = _FILENAME_RE.search(valor or "")
    if not m:
        return ""
    return unquote(m.group(1)).strip() if m.group(1) else m.group(2).strip()


def interpretar_download_anexo(resp: httpx.Response) -> ArquivoBaixado:
    """
    download_ws para QUALQUER tipo de arquivo (anexos lidos por ETL). Testado na SUPRA em 2026-09-30:
    pdf/xlsx vêm como binário com `Content-Disposition: attachment; filename="<nome original>"` e o
    Content-Type do arquivo; imagens vêm em JSON com base64; erro vem em JSON com `status: false`.
    """
    tipo = resp.headers.get("content-type", "").split(";")[0].strip().lower()
    nome = _nome_do_content_disposition(resp.headers.get("content-disposition", ""))
    if tipo == "application/json":
        try:
            dados = resp.json()
        except ValueError as exc:
            raise ArquivoInvalido("download_ws devolveu um JSON inválido.") from exc
        texto = _base64_do_json(dados)  # `status: false` vira ArquivoInvalido com a mensagem da SUPRA
        if not texto:
            raise ArquivoInvalido("download_ws respondeu JSON sem o conteúdo do arquivo.")
        mime = ""
        resultado = dados.get("resultado") if isinstance(dados, dict) else None
        if isinstance(resultado, dict):
            mime = str(resultado.get("mime_type") or "")
        if texto.startswith("data:") and "," in texto:
            cabecalho, texto = texto.split(",", 1)
            mime = mime or cabecalho[5:].split(";")[0]
        try:
            conteudo = base64.b64decode(texto, validate=False)
        except (binascii.Error, ValueError) as exc:
            raise ArquivoInvalido("download_ws devolveu um base64 inválido.") from exc
        tipo = mime or detectar_mime_imagem(conteudo) or "application/octet-stream"
    else:
        conteudo = resp.content
        tipo = tipo or "application/octet-stream"
    if not conteudo:
        raise ArquivoInvalido("download_ws devolveu um arquivo vazio.")
    return ArquivoBaixado(conteudo=conteudo, mime_type=tipo, nome=nome)


class DnitClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self._base_url = settings.dnit_base_url.rstrip("/")
        self._token = settings.dnit_token
        self._client = client
        self._semaforo = asyncio.Semaphore(settings.dnit_max_concorrencia)
        self._retries = settings.dnit_retries
        self._espera = settings.dnit_retry_espera
        # Conexão: 10 s; leitura/escrita: tempo máximo sem tráfego (detecta a SUPRA travada).
        self._timeout = httpx.Timeout(settings.dnit_timeout, connect=10.0)

    def _headers(self, accept: str = "application/json") -> dict[str, str]:
        return {"Accept": accept, "token": self._token}

    async def _get(
        self, url: str, params: dict[str, str], descricao: str, accept: str = "application/json"
    ) -> httpx.Response:
        """GET com limite de simultaneidade e nova tentativa em 502/503/504 e em conexão derrubada."""
        for tentativa in range(self._retries + 1):
            ultima = tentativa >= self._retries
            try:
                async with self._semaforo:
                    resp = await self._client.get(
                        url, params=params, headers=self._headers(accept), timeout=self._timeout
                    )
            except httpx.TransportError as exc:
                motivo = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
                if ultima:
                    raise SupraIndisponivel(
                        f"SUPRA indisponível em {descricao}: conexão derrubada ou sem resposta em "
                        f"{self._retries + 1} tentativa(s) (último erro: {motivo}). Tente de novo em instantes."
                    ) from exc
            else:
                if resp.status_code not in _STATUS_REPETIVEIS or ultima:
                    if resp.is_redirect:
                        raise SupraTokenRecusado(
                            f"SUPRA recusou o token em {descricao} (HTTP {resp.status_code}, redirecionou "
                            "para a página inicial). Gere um novo DNIT_TOKEN."
                        )
                    resp.raise_for_status()
                    return resp
                motivo = f"HTTP {resp.status_code}"

            espera = self._espera * (tentativa + 1)
            logger.warning(
                "SUPRA %s: %s, nova tentativa %d/%d em %.1f s",
                descricao, motivo, tentativa + 1, self._retries, espera,
            )
            await asyncio.sleep(espera)  # fora do semáforo: não segura a vaga de outro tópico
        raise AssertionError("inalcançável")  # o laço sempre retorna ou levanta

    async def _get_json(self, url: str, params: dict[str, str], descricao: str) -> dict | list:
        resp = await self._get(url, params, descricao)
        return resp.json()

    async def buscar_secao(
        self,
        endpoint: str,
        contrato: str,
        periodo_inicio: str,
        periodo_fim: str,
    ) -> dict | list:
        """
        GET .../relatorio/secao_ws/<endpoint>

        O parâmetro de início é `periodo_inicio` (documentação da SUPRA). O fluxo do n8n mandava
        `periodo_incio` (typo): a SUPRA ignorava o parâmetro e usava a data padrão antiga (2020-10-01),
        trazendo dados de 2020 até o fim do período. Confirmado no servidor em 2026-10-01 (ex.: diário de
        obra de mar/2026 → 4 arquivos de 2020 com o typo; 8 arquivos do mês com o nome correto).
        """
        url = f"{self._base_url}/relatorio/secao_ws/{endpoint}"
        params = {
            "contrato": contrato,
            "periodo_inicio": periodo_inicio,
            "periodo_fim": periodo_fim,
        }
        logger.info("DNIT GET secao_ws/%s (contrato=%s)", endpoint, contrato)
        return await self._get_json(url, params, f"secao_ws/{endpoint}")

    async def download_arquivo(self, contrato: str, nome_arquivo: str) -> ArquivoBaixado:
        """
        GET .../arquivo/download_ws — usado nos tópicos com análise de imagem.

        Devolve os bytes da imagem e o tipo já validados; `ArquivoBaixado.data_uri` monta o
        `data:<tipo>;base64,...` enviado à LLM.
        """
        url = f"{self._base_url}/arquivo/download_ws"
        params = {"contrato": contrato, "nome_arquivo": nome_arquivo}
        logger.info("DNIT GET arquivo/download_ws (contrato=%s, arquivo=%s)", contrato, nome_arquivo)
        resp = await self._get(url, params, "arquivo/download_ws", accept="*/*")
        return interpretar_download(resp)

    async def baixar_anexo(
        self, contrato: str, *, nome_arquivo: str = "", id_arquivo: str = ""
    ) -> ArquivoBaixado:
        """
        GET .../arquivo/download_ws — qualquer tipo de arquivo (pdf, xlsx…), para os anexos lidos por ETL.

        Prefere `nome_arquivo` (modo que a SUPRA aceita hoje). `id_arquivo` foi pedido à equipe da SUPRA
        em 2026-09-30 e ainda não é aceito — o nome do parâmetro é a CONFIRMAR quando publicarem.
        """
        if nome_arquivo:
            params = {"contrato": contrato, "nome_arquivo": nome_arquivo}
        elif id_arquivo:
            params = {"contrato": contrato, "id_arquivo": id_arquivo}
        else:
            raise ValueError("Informe nome_arquivo ou id_arquivo.")
        url = f"{self._base_url}/arquivo/download_ws"
        logger.info(
            "DNIT GET arquivo/download_ws (contrato=%s, arquivo=%s)", contrato, nome_arquivo or f"id {id_arquivo}"
        )
        resp = await self._get(url, params, "arquivo/download_ws", accept="*/*")
        return interpretar_download_anexo(resp)
