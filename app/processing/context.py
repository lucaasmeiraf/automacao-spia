"""
Contexto de processamento — agrupa todos os clientes HTTP necessários para
executar os processors. Criado por requisição em main.py a partir do app.state.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.clients.dnit import DnitClient
from app.clients.nominatim import NominatimClient
from app.clients.openai_client import OpenAIClient
from app.clients.openmeteo import OpenMeteoClient


@dataclass
class ProcessingContext:
    dnit: DnitClient
    openai: OpenAIClient
    openmeteo: OpenMeteoClient
    nominatim: NominatimClient

    @classmethod
    def da_app(cls, state) -> ProcessingContext:
        """Monta o contexto a partir dos clientes guardados em `app.state` (lifespan)."""
        return cls(
            dnit=state.dnit,
            openai=state.openai,
            openmeteo=state.openmeteo,
            nominatim=state.nominatim,
        )
