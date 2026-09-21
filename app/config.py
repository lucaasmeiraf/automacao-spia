"""
Configuração central da aplicação.

Lê as variáveis de ambiente (a partir do arquivo .env) e as expõe de forma
tipada. É o equivalente ao nó "Define Variáveis Globais" do n8n — porém com os
segredos FORA do código, carregados do ambiente.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # OpenAI
    openai_api_key: str
    openai_base_url: str = "https://api.openai.com/v1"

    # DNIT / SUPRA
    dnit_token: str
    dnit_base_url: str = (
        "https://supra.dnit.gov.br/index_cgcont_common.php/cgcont/ai"
    )

    # Legendas globais
    legendas: str = ""

    # Open-Meteo (dados meteorológicos históricos, sem autenticação)
    openmeteo_base_url: str = "https://archive-api.open-meteo.com/v1"

    # Nominatim / OpenStreetMap (geocodificação, sem autenticação)
    nominatim_base_url: str = "https://nominatim.openstreetmap.org"

    # Servidor
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    # Rede
    http_timeout: float = 120.0
    http_max_retries: int = 2


@lru_cache
def get_settings() -> Settings:
    """Retorna uma instância única (cacheada) das configurações."""
    return Settings()  # type: ignore[call-arg]
