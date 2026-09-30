"""
ETL dos anexos: bytes de um arquivo (xlsx, pdf, csv/txt) → texto para a LLM.

Usado pela estratégia "campo_anexos" (ver docs/architecture.md §4 "Anexos lidos por ETL").
Funções síncronas (CPU): o handler as chama com `asyncio.to_thread` para não travar o loop.

O formato é identificado pelos BYTES (assinatura), não pelo nome nem pelo Content-Type da SUPRA.
Formato sem suporte, PDF escaneado etc. viram `FormatoNaoSuportado` / `aviso` — nunca texto inventado.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, time

# Teto por anexo: a planilha padrão do Resumo do Projeto tem ~5 mil caracteres; um PDF de projeto pode
# ter centenas de páginas. 40 mil caracteres ≈ 10 mil tokens.
LIMITE_CARACTERES = 40_000

_ASSINATURA_PDF = b"%PDF"
_ASSINATURA_ZIP = b"PK\x03\x04"
_ASSINATURA_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"  # .xls/.doc antigos (Office 97-2003)
_ESPACOS_RE = re.compile(r"[ \t\r\f\v\xa0]+")


class FormatoNaoSuportado(ValueError):
    """O arquivo não é xlsx, pdf nem texto — ou não pôde ser lido."""


@dataclass(frozen=True)
class TextoExtraido:
    texto: str
    formato: str  # "xlsx" | "pdf" | "texto"
    truncado: bool = False
    aviso: str = ""


def detectar_formato(conteudo: bytes, nome: str = "", mime_type: str = "") -> str:
    """Formato pelos bytes; nome/Content-Type só desempatam o que não tem assinatura (csv/txt)."""
    if conteudo.startswith(_ASSINATURA_PDF):
        return "pdf"
    if conteudo.startswith(_ASSINATURA_ZIP):
        try:
            with zipfile.ZipFile(io.BytesIO(conteudo)) as z:
                nomes = set(z.namelist())
        except zipfile.BadZipFile as exc:
            raise FormatoNaoSuportado("arquivo compactado corrompido") from exc
        if "xl/workbook.xml" in nomes:
            return "xlsx"
        if "word/document.xml" in nomes:
            raise FormatoNaoSuportado("documento Word (.docx) ainda não é lido")
        raise FormatoNaoSuportado("arquivo compactado que não é planilha xlsx")
    if conteudo.startswith(_ASSINATURA_OLE):
        raise FormatoNaoSuportado("formato antigo do Office (.xls/.doc) — salvar como .xlsx ou .pdf")
    nome_min = nome.lower()
    if mime_type.startswith("text/") or nome_min.endswith((".csv", ".txt")):
        return "texto"
    raise FormatoNaoSuportado(f"formato não suportado ({mime_type or 'tipo desconhecido'})")


def _limpar_linha(texto: str) -> str:
    return _ESPACOS_RE.sub(" ", texto).strip()


def _formatar_numero(valor: float) -> str:
    if float(valor).is_integer():
        return str(int(valor))
    return f"{round(valor, 6):f}".rstrip("0").rstrip(".")


def _formatar_celula(valor, formato_numero: str = "") -> str:
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return "Sim" if valor else "Não"
    if isinstance(valor, datetime):
        return valor.date().isoformat() if valor.time() == time(0) else valor.isoformat(" ", "minutes")
    if isinstance(valor, (date, time)):
        return valor.isoformat()
    if isinstance(valor, (int, float)):
        if "%" in (formato_numero or ""):
            return _formatar_numero(valor * 100) + "%"
        return _formatar_numero(valor)
    return " ".join(str(valor).split())  # quebras de linha dentro da célula viram espaço


def _extrair_xlsx(conteudo: bytes, limite: int) -> tuple[str, bool]:
    import openpyxl  # importado aqui: só quem lê anexos precisa da dependência

    try:
        wb = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl levanta vários tipos para arquivo inválido
        raise FormatoNaoSuportado(f"planilha ilegível ({type(exc).__name__})") from exc
    partes: list[str] = []
    total = 0
    try:
        for ws in wb.worksheets:
            linhas: list[str] = []
            for linha in ws.iter_rows():
                celulas = [
                    _formatar_celula(c.value, getattr(c, "number_format", "")) for c in linha
                ]
                celulas = [c for c in celulas if c]
                if celulas:
                    linhas.append(" | ".join(celulas))
                    total += len(linhas[-1]) + 1
                if total > limite:
                    break
            if linhas:
                partes.append(f"### Aba: {ws.title}\n" + "\n".join(linhas))
            if total > limite:
                break
    finally:
        wb.close()
    return "\n\n".join(partes), total > limite


def _extrair_pdf(conteudo: bytes, limite: int) -> tuple[str, bool]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        leitor = PdfReader(io.BytesIO(conteudo))
        if leitor.is_encrypted:
            leitor.decrypt("")  # PDF com senha só de "proprietário" abre com senha vazia
        paginas = leitor.pages
    except (PdfReadError, ValueError, KeyError) as exc:
        raise FormatoNaoSuportado(f"PDF ilegível ({type(exc).__name__})") from exc
    partes: list[str] = []
    total = 0
    for numero, pagina in enumerate(paginas, start=1):
        try:
            bruto = pagina.extract_text() or ""
        except Exception:  # página corrompida não derruba as demais
            continue
        linhas = [_limpar_linha(l) for l in bruto.splitlines()]
        texto = "\n".join(l for l in linhas if l)
        if texto:
            partes.append(f"### Página {numero}\n{texto}")
            total += len(partes[-1]) + 2
        if total > limite:
            break
    return "\n\n".join(partes), total > limite


def _extrair_texto_puro(conteudo: bytes) -> str:
    for codificacao in ("utf-8-sig", "cp1252"):
        try:
            texto = conteudo.decode(codificacao)
            break
        except UnicodeDecodeError:
            continue
    else:
        texto = conteudo.decode("latin-1")
    linhas = [_limpar_linha(l) for l in texto.splitlines()]
    return "\n".join(l for l in linhas if l)


def extrair_texto(
    conteudo: bytes, nome: str = "", mime_type: str = "", limite: int = LIMITE_CARACTERES
) -> TextoExtraido:
    """Texto do anexo (no máximo `limite` caracteres). Levanta `FormatoNaoSuportado`."""
    formato = detectar_formato(conteudo, nome, mime_type)
    aviso = ""
    if formato == "xlsx":
        texto, truncado = _extrair_xlsx(conteudo, limite)
    elif formato == "pdf":
        texto, truncado = _extrair_pdf(conteudo, limite)
        if not texto:
            aviso = "PDF sem texto extraível (provavelmente digitalizado); OCR não é feito."
    else:
        texto = _extrair_texto_puro(conteudo)
        truncado = len(texto) > limite

    if len(texto) > limite:
        texto, truncado = texto[:limite], True
    if not texto and not aviso:
        aviso = "Arquivo sem conteúdo legível."
    return TextoExtraido(texto=texto, formato=formato, truncado=truncado, aviso=aviso)
