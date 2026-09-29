"""
Configuração central da aplicação.

Lê as variáveis de ambiente (a partir do arquivo .env) e as expõe de forma
tipada. É o equivalente ao nó "Define Variáveis Globais" do n8n — porém com os
segredos FORA do código, carregados do ambiente.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # Erros de validação NÃO podem imprimir o valor recebido (pode ser um segredo).
        hide_input_in_errors=True,
    )

    # Ambiente de execução. O padrão é "prod" de propósito (falha fechada): se a
    # variável ENV for esquecida, nenhuma rota/tela de configuração é exposta.
    env: Literal["dev", "homolog", "prod"] = "prod"

    # Ativação dos tópicos (o "fio" do n8n) e prompts por tópico.
    topics_file: str = "config/topics.yaml"
    prompts_dir: str = "prompts"
    # Tópicos criados pela tela (campo/json), somados aos de app/topics.py.
    topicos_extras_file: str = "config/topicos_extras.yaml"

    # --- Segurança ---
    # Chave que o SISTEMA CHAMADOR envia no header `X-API-Key` do POST /webhook/relatorio.
    # Ausente => o webhook fica indisponível (503): nunca aberto por esquecimento.
    webhook_api_key: str | None = None

    # Administradores (login da tela de configuração): {"usuario": "<hash argon2>"}.
    # Guarda só o HASH da senha, nunca a senha. Gere com `python -m scripts.gerar_hash_senha`.
    admin_users: dict[str, str] = {}

    # Cookie de sessão com flag Secure (só trafega em HTTPS). Deixe true; em http puro
    # (sem TLS) o navegador descarta o cookie e o login não funciona — use um proxy HTTPS.
    cookie_secure: bool = True
    # Expiração da sessão: por inatividade e absoluta.
    session_idle_minutes: int = 30
    session_max_hours: int = 8

    # /docs, /redoc e /openapi.json ficam DESLIGADOS. Só é possível ligar com ENV=dev.
    enable_docs: bool = False

    @field_validator("webhook_api_key", mode="before")
    @classmethod
    def _chave_webhook(cls, v: object) -> object:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None  # linha em branco no .env = não configurada
        if isinstance(v, str) and len(v.strip()) < 32:
            raise ValueError(
                "WEBHOOK_API_KEY curta demais (mínimo 32 caracteres). "
                "Gere uma com `python -m scripts.gerar_chave`."
            )
        return v.strip() if isinstance(v, str) else v

    @field_validator("admin_users")
    @classmethod
    def _admins(cls, v: dict[str, str]) -> dict[str, str]:
        for usuario, senha_hash in v.items():
            if not usuario.strip():
                raise ValueError("ADMIN_USERS: nome de usuário vazio.")
            if not senha_hash.startswith("$argon2"):
                raise ValueError(
                    f"ADMIN_USERS: o valor de '{usuario}' não é um hash argon2. "
                    "Gere com `python -m scripts.gerar_hash_senha` (nunca coloque a senha em texto)."
                )
        return v

    # OpenAI
    openai_api_key: str
    openai_base_url: str = "https://api.openai.com/v1"

    # DNIT / SUPRA
    dnit_token: str
    dnit_base_url: str = (
        "https://supra.dnit.gov.br/index_cgcont_common.php/cgcont/ai"
    )
    # Proteção do servidor da SUPRA: muitas chamadas simultâneas geram "502 Proxy Error".
    dnit_max_concorrencia: int = Field(default=4, ge=1, le=20)   # requisições simultâneas
    dnit_retries: int = Field(default=2, ge=0, le=5)             # novas tentativas em 502/503/504
    dnit_retry_espera: float = Field(default=1.0, ge=0, le=30)   # segundos (cresce a cada tentativa)

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
