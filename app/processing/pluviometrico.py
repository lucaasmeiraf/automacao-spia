"""
Handler do tópico 'controle_pluviometrico'.

Pipeline: SUPRA /capa → SUPRA /controle_pluviometrico → Nominatim (geocode) →
Open-Meteo (histórico) → identifica divergências → LLM → limpa retorno.

É o tópico mais complexo — envolve 4 fontes de dados.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date

from app.models import TopicoResultado
from app.processing.context import ProcessingContext
from app.processing.llm_resposta import MOTIVO_ERRO_PARSE, interpretar_resposta, pedir_json
from app.topics import TopicConfig

logger = logging.getLogger(__name__)

# Centroides geográficos aproximados de cada UF (lat, lon).
# Usado como fallback quando o Nominatim não retorna resultado.
_CENTROIDES: dict[str, tuple[float, float]] = {
    "AC": (-9.0238, -70.812),
    "AL": (-9.5713, -36.782),
    "AM": (-3.4168, -65.856),
    "AP": (1.413, -51.768),
    "BA": (-12.0538, -41.609),
    "CE": (-5.4984, -39.321),
    "DF": (-15.7801, -47.929),
    "ES": (-19.1834, -40.308),
    "GO": (-15.827, -49.836),
    "MA": (-5.422, -45.444),
    "MG": (-18.512, -44.555),
    "MS": (-20.7722, -54.785),
    "MT": (-12.6819, -56.921),
    "PA": (-3.4168, -52.233),
    "PB": (-7.2399, -36.782),
    "PE": (-8.8137, -36.954),
    "PI": (-7.718, -42.728),
    "PR": (-24.8213, -51.082),
    "RJ": (-22.3105, -42.736),
    "RN": (-5.8127, -36.593),
    "RO": (-10.9391, -62.826),
    "RR": (1.9905, -61.332),
    "RS": (-29.715, -53.809),
    "SC": (-27.4506, -50.947),
    "SE": (-10.5741, -37.385),
    "SP": (-22.1875, -48.793),
    "TO": (-10.1753, -48.298),
}

# Legenda SUPRA: id → descrição (campo `legenda` de cada registro)
_LEGENDA_SUPRA: dict[int, str] = {
    1: "Bom",
    2: "Chuva",
    3: "Impraticável",
    4: "Não houveram atividades",
    5: "Instável",
}


def _como_lista(resultado) -> list[dict]:
    if isinstance(resultado, list):
        return resultado
    if isinstance(resultado, dict) and "resultado" in resultado:
        r = resultado["resultado"]
        return r if isinstance(r, list) else [r]
    return [resultado]


_PERIODO_RE = re.compile(r"Per[íi]odo:\s*(\d{1,2})/(\d{1,2})/(\d{4})", re.IGNORECASE)
_DIA_RE = re.compile(r"Dia:\s*(\d{1,2})\s*,\s*ID Status:\s*(\d+)", re.IGNORECASE)


def _expandir_registros_supra(registros: list[dict]) -> list[dict]:
    """
    Um registro por dia (`data` + `legenda`), como `_identificar_divergencias` espera.

    Formato REAL da SUPRA (confirmado em 2026-10-01): um registro por MÊS, com os dias num texto:
        {"resumo": "Período: 01/03/2026 | Dia: 1, ID Status: 1, Legenda: BOM | Dia: 2, ID Status: 2, ..."}
    Antes desta função, nenhum dia era reconhecido (tudo "Não informado" → zero divergências sempre).
    Registros já diários (`data`/`legenda`) passam como estão.
    """
    dias: list[dict] = []
    for reg in registros:
        if not isinstance(reg, dict):
            continue
        if reg.get("data"):
            dias.append(reg)
            continue
        texto = str(reg.get("resumo") or "")
        periodo = _PERIODO_RE.search(texto)
        if not periodo:
            continue
        mes, ano = int(periodo.group(2)), int(periodo.group(3))
        for dia, status in _DIA_RE.findall(texto):
            try:
                data = date(ano, mes, int(dia))
            except ValueError:  # dia inexistente no mês (ex.: 31/04): ignora
                continue
            dias.append({"data": data.isoformat(), "legenda": int(status)})
    return dias


def _inferir_status_openmeteo(
    prec: float,
    temp: float,
    vento: float,
    weathercode: int,
) -> str:
    """
    Infere o status de trabalho esperado a partir dos dados meteorológicos.
    Espelha a função `inferirStatusOpenMeteo` do nó "Identifica Divergências" do n8n.
    """
    if prec >= 10 or weathercode >= 95 or vento >= 50:
        return "Impraticável"
    if temp >= 42:
        return "Impraticável"
    if temp >= 38:
        return "Instável"
    if prec >= 1:
        return "Chuva"
    if prec >= 0.1:
        return "Instável"
    return "Bom"


def _identificar_divergencias(
    registros_supra: list[dict],
    openmeteo_data: dict,
) -> dict:
    """
    Cruza os registros diários do SUPRA com os dados do Open-Meteo.
    Retorna divergencias, total e resumo_diario.
    """
    daily = openmeteo_data.get("daily") or {}
    datas = daily.get("time") or []
    precip = daily.get("precipitation_sum") or []
    temp_max = daily.get("temperature_2m_max") or []
    vento_max = daily.get("windspeed_10m_max") or []
    weathercodes = daily.get("weathercode") or []

    # Índice SUPRA por data (remove parte do horário se houver)
    supra_por_data: dict[str, dict] = {}
    for reg in registros_supra:
        data_raw = reg.get("data") or ""
        data_key = data_raw[:10]
        if data_key:
            supra_por_data[data_key] = reg

    divergencias: list[dict] = []
    resumo: list[dict] = []

    for i, data in enumerate(datas):
        prec = precip[i] if i < len(precip) else 0.0
        temp = temp_max[i] if i < len(temp_max) else 0.0
        vento = vento_max[i] if i < len(vento_max) else 0.0
        wcode = weathercodes[i] if i < len(weathercodes) else 0

        status_esperado = _inferir_status_openmeteo(
            float(prec or 0),
            float(temp or 0),
            float(vento or 0),
            int(wcode or 0),
        )

        supra_dia = supra_por_data.get(data)
        legenda_id = supra_dia.get("legenda") if supra_dia else None
        status_supra = _LEGENDA_SUPRA.get(int(legenda_id), "Não informado") if legenda_id else "Não informado"

        entrada = {
            "data": data,
            "status_supra": status_supra,
            "status_esperado_openmeteo": status_esperado,
            "precipitacao_mm": round(float(prec or 0), 2),
            "temperatura_max": round(float(temp or 0), 1),
            "vento_kmh": round(float(vento or 0), 1),
            "weathercode": int(wcode or 0),
        }

        resumo.append(entrada)
        if status_supra != status_esperado and status_supra != "Não informado":
            divergencias.append(entrada)

    return {
        "divergencias": divergencias,
        "total_dias_analisados": len(datas),
        "total_divergencias": len(divergencias),
        "resumo_diario": resumo,
    }


async def processar_pluviometrico(
    cfg: TopicConfig,
    prompt_sistema: str,
    contrato: str,
    periodo_inicio: str,
    periodo_fim: str,
    ctx: ProcessingContext,
) -> TopicoResultado:
    """Pipeline completo do controle pluviométrico."""
    try:
        # 1. Busca SUPRA: controle pluviométrico e capa (localização)
        bruto_pluvi, bruto_capa = await _buscar_dados_supra(
            ctx, contrato, periodo_inicio, periodo_fim
        )

        registros_pluvi = _expandir_registros_supra(_como_lista(bruto_pluvi))
        registros_capa = _como_lista(bruto_capa)
        capa = registros_capa[0] if registros_capa else {}

        br = capa.get("br") or ""
        uf = capa.get("uf") or ""
        municipio = capa.get("municipio") or ""

        # 2. Geocodifica a localização da obra
        lat, lon, fonte = await _geocodificar(ctx, br, uf, municipio)

        # 3. Busca dados meteorológicos históricos
        openmeteo_data = await ctx.openmeteo.buscar_historico(
            lat, lon, periodo_inicio, periodo_fim
        )

        # 4. Identifica divergências entre SUPRA e Open-Meteo
        divergencias_info = _identificar_divergencias(registros_pluvi, openmeteo_data)

        # 5. Monta payload para a LLM
        user_content = json.dumps(
            {
                "localizacao": {"br": br, "uf": uf, "municipio": municipio},
                "periodo": {"inicio": periodo_inicio, "fim": periodo_fim},
                **divergencias_info,
            },
            ensure_ascii=False,
        )

        body = pedir_json({
            "model": cfg.model,
            "max_tokens": cfg.max_tokens,
            "messages": [
                {"role": "system", "content": prompt_sistema},
                {"role": "user", "content": user_content},
            ],
        })

        # 6. Chama a LLM
        resposta = await ctx.openai.chat(body)

        # 7. Limpa retorno — mantém TUDO o que a IA respondeu (distribuicao_dias, conformidade_in51,
        #    analise_impacto, checklist… como no n8n) e garante os campos mínimos.
        parsed = interpretar_resposta(
            resposta, "Controle Pluviométrico",
            campos_extras=("status_texto", "texto", "percentual_impacto"),
        )
        if parsed.get("erro_parse"):
            parsed["motivo"] = parsed["motivo"] if parsed["motivo"] != MOTIVO_ERRO_PARSE else (
                "Não foi possível analisar o controle pluviométrico."
            )

        conteudo = {
            **parsed,
            "identificador": "Controle Pluviométrico",
            "conforme": parsed.get("conforme") or "Atenção",
            "motivo": (
                parsed.get("motivo")
                or parsed.get("analise")
                or "Não foi possível analisar o controle pluviométrico."
            ),
            "analise_detalhada": parsed.get("analise_detalhada") or parsed.get("details"),
            "infos": {
                "total_dias_analisados": divergencias_info["total_dias_analisados"],
                "total_divergencias": divergencias_info["total_divergencias"],
                "resumo_diario": divergencias_info["resumo_diario"],
                "fonte_geodados": fonte,
            },
        }

        return TopicoResultado(topico=cfg.chave, ok=True, conteudo=conteudo)

    except Exception as exc:
        logger.exception("Falha ao processar tópico '%s'", cfg.chave)
        return TopicoResultado(topico=cfg.chave, ok=False, erro=str(exc))


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

async def _buscar_dados_supra(
    ctx: ProcessingContext,
    contrato: str,
    periodo_inicio: str,
    periodo_fim: str,
):
    """Busca controle_pluviometrico e capa em paralelo."""
    import asyncio
    return await asyncio.gather(
        ctx.dnit.buscar_secao("controle_pluviometrico", contrato, periodo_inicio, periodo_fim),
        ctx.dnit.buscar_secao("capa", contrato, periodo_inicio, periodo_fim),
    )


async def _geocodificar(
    ctx: ProcessingContext,
    br: str,
    uf: str,
    municipio: str,
) -> tuple[float, float, str]:
    """
    Geocodifica a localização da obra via Nominatim.
    Se não encontrar resultado, usa o centroide da UF como fallback.
    Retorna (lat, lon, fonte).
    """
    query = f"{br}, {municipio}, {uf}, Brasil"
    try:
        resultados = await ctx.nominatim.search(query)
    except Exception:
        logger.warning("Nominatim falhou para query=%r, usando centroide", query)
        resultados = []

    if resultados and resultados[0].get("lat"):
        lat = float(resultados[0]["lat"])
        lon = float(resultados[0]["lon"])
        return lat, lon, "nominatim"

    centroide = _CENTROIDES.get(uf.upper(), (-15.78, -47.93))
    logger.warning("Nominatim sem resultado para '%s'; fallback centroide %s", query, uf)
    return centroide[0], centroide[1], "fallback_uf"
