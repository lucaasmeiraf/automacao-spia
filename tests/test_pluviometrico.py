"""
Testes da lógica do controle pluviométrico.

Cobre: inferência de status meteorológico e identificação de divergências.
Não requer I/O — testa apenas as funções puras do módulo.
"""
from __future__ import annotations

from app.processing.pluviometrico import (
    _identificar_divergencias,
    _inferir_status_openmeteo,
)


# ---------------------------------------------------------------------------
# _inferir_status_openmeteo
# ---------------------------------------------------------------------------

def test_inferir_status_bom():
    assert _inferir_status_openmeteo(0, 25, 10, 0) == "Bom"


def test_inferir_status_chuva_precipitacao_moderada():
    assert _inferir_status_openmeteo(3.5, 25, 10, 0) == "Chuva"


def test_inferir_status_instavel_precipitacao_leve():
    assert _inferir_status_openmeteo(0.5, 25, 10, 0) == "Instável"


def test_inferir_status_impraticavel_precipitacao_alta():
    assert _inferir_status_openmeteo(15, 25, 10, 0) == "Impraticável"


def test_inferir_status_impraticavel_tempestade():
    assert _inferir_status_openmeteo(0, 25, 10, 95) == "Impraticável"


def test_inferir_status_impraticavel_vento():
    assert _inferir_status_openmeteo(0, 25, 55, 0) == "Impraticável"


def test_inferir_status_impraticavel_temperatura_extrema():
    assert _inferir_status_openmeteo(0, 43, 10, 0) == "Impraticável"


def test_inferir_status_instavel_temperatura_alta():
    assert _inferir_status_openmeteo(0, 39, 10, 0) == "Instável"


# ---------------------------------------------------------------------------
# _identificar_divergencias
# ---------------------------------------------------------------------------

def _make_openmeteo(datas, precip, temp, vento, wcodes):
    return {
        "daily": {
            "time": datas,
            "precipitation_sum": precip,
            "temperature_2m_max": temp,
            "windspeed_10m_max": vento,
            "weathercode": wcodes,
        }
    }


def test_sem_divergencias_status_coincide():
    supra = [{"data": "2025-01-01T00:00:00", "legenda": 1}]  # Bom
    openmeteo = _make_openmeteo(["2025-01-01"], [0.0], [28.0], [10.0], [0])
    resultado = _identificar_divergencias(supra, openmeteo)
    assert resultado["total_divergencias"] == 0
    assert resultado["total_dias_analisados"] == 1
    assert resultado["resumo_diario"][0]["status_supra"] == "Bom"
    assert resultado["resumo_diario"][0]["status_esperado_openmeteo"] == "Bom"


def test_divergencia_detectada_supra_bom_meteo_chuva():
    supra = [{"data": "2025-01-02T00:00:00", "legenda": 1}]  # Bom
    openmeteo = _make_openmeteo(["2025-01-02"], [5.0], [25.0], [10.0], [0])  # Chuva
    resultado = _identificar_divergencias(supra, openmeteo)
    assert resultado["total_divergencias"] == 1
    divergencia = resultado["divergencias"][0]
    assert divergencia["status_supra"] == "Bom"
    assert divergencia["status_esperado_openmeteo"] == "Chuva"


def test_sem_divergencia_para_nao_informado():
    """Dia sem registro SUPRA não é divergência (status_supra = 'Não informado')."""
    supra = []
    openmeteo = _make_openmeteo(["2025-01-03"], [5.0], [25.0], [10.0], [0])
    resultado = _identificar_divergencias(supra, openmeteo)
    assert resultado["total_divergencias"] == 0
    assert resultado["resumo_diario"][0]["status_supra"] == "Não informado"


def test_multiplos_dias_contagem_correta():
    supra = [
        {"data": "2025-01-01T00:00:00", "legenda": 1},  # Bom == Bom → ok
        {"data": "2025-01-02T00:00:00", "legenda": 1},  # Bom ≠ Chuva → diverge
        {"data": "2025-01-03T00:00:00", "legenda": 3},  # Impraticável == Impraticável → ok
    ]
    openmeteo = _make_openmeteo(
        ["2025-01-01", "2025-01-02", "2025-01-03"],
        [0.0, 5.0, 12.0],
        [28.0, 25.0, 22.0],
        [10.0, 10.0, 10.0],
        [0, 0, 0],
    )
    resultado = _identificar_divergencias(supra, openmeteo)
    assert resultado["total_dias_analisados"] == 3
    assert resultado["total_divergencias"] == 1


def test_dados_openmeteo_vazios():
    resultado = _identificar_divergencias([], {"daily": {}})
    assert resultado["total_dias_analisados"] == 0
    assert resultado["total_divergencias"] == 0
    assert resultado["resumo_diario"] == []


# ---------------------------------------------------------------------------
# _expandir_registros_supra — formato real da SUPRA (um registro por mês, dias num texto)
# ---------------------------------------------------------------------------

from app.processing.pluviometrico import _expandir_registros_supra  # noqa: E402

RESUMO_REAL = (
    "Período: 01/03/2026 | Dia: 1, ID Status: 1, Legenda: BOM | Dia: 2, ID Status: 1, Legenda: BOM | "
    "Dia: 3, ID Status: 2, Legenda: CHUVOSO | Dia: 31, ID Status: 3, Legenda: IMPRATICÁVEL"
)


def test_expande_o_texto_mensal_em_dias():
    dias = _expandir_registros_supra([{"id_contrato_obra": "795", "resumo": RESUMO_REAL}])
    assert dias == [
        {"data": "2026-03-01", "legenda": 1},
        {"data": "2026-03-02", "legenda": 1},
        {"data": "2026-03-03", "legenda": 2},
        {"data": "2026-03-31", "legenda": 3},
    ]


def test_dia_inexistente_no_mes_e_ignorado():
    dias = _expandir_registros_supra([{"resumo": "Período: 01/04/2026 | Dia: 30, ID Status: 1 | Dia: 31, ID Status: 1"}])
    assert [d["data"] for d in dias] == ["2026-04-30"]


def test_registros_ja_diarios_e_lixo():
    diario = {"data": "2025-01-01T00:00:00", "legenda": 1}
    assert _expandir_registros_supra([diario, {"resumo": "sem período"}, None]) == [diario]


def test_formato_real_agora_gera_divergencia():
    """Antes da correção, o formato real nunca gerava divergência (todos os dias 'Não informado')."""
    dias = _expandir_registros_supra([{"resumo": RESUMO_REAL}])
    openmeteo = _make_openmeteo(["2026-03-01", "2026-03-02"], [0.0, 5.0], [25.0, 25.0], [10.0, 10.0], [0, 0])
    resultado = _identificar_divergencias(dias, openmeteo)
    assert resultado["resumo_diario"][0]["status_supra"] == "Bom"
    assert resultado["total_divergencias"] == 1  # dia 2: SUPRA "Bom" × chuva de 5 mm
    assert resultado["divergencias"][0]["data"] == "2026-03-02"
