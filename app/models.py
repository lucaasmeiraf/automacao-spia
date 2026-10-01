"""
Modelos de dados (Pydantic) para a entrada e a saída do webhook.

Equivale à validação do nó "If" do n8n (contrato / periodo_inicio /
periodo_fim obrigatórios) e à estrutura do array de prompts consumido pelo
nó "Separa Prompts".
"""
from __future__ import annotations

import re
from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator

# A SUPRA só aceita Y-m-d. O campo de data do navegador aceita anos com 5+ dígitos ("20226-07-01"), que a
# SUPRA recusa com status false — e a recusa chegava à LLM como seção vazia (2026-10-01).
_DATA_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class PromptItem(BaseModel):
    """Um prompt configurado na interface, para um tópico específico."""
    topico: str
    conteudo: str


class RelatorioRequest(BaseModel):
    """Corpo (body) esperado no POST do webhook."""
    contrato: str = Field(..., min_length=1)
    periodo_inicio: str = Field(..., min_length=1)
    periodo_fim: str = Field(..., min_length=1)
    prompts: list[PromptItem] = Field(default_factory=list)

    @field_validator("contrato", "periodo_inicio", "periodo_fim")
    @classmethod
    def _nao_vazio(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("campo obrigatório não pode ser vazio")
        return v.strip()

    @field_validator("periodo_inicio", "periodo_fim")
    @classmethod
    def _data_valida(cls, v: str) -> str:
        try:
            if not _DATA_RE.match(v):
                raise ValueError
            date.fromisoformat(v)
        except ValueError:
            raise ValueError("data inválida: use o formato AAAA-MM-DD (ex.: 2026-07-01)") from None
        return v

    @model_validator(mode="after")
    def _inicio_antes_do_fim(self) -> RelatorioRequest:
        if self.periodo_inicio > self.periodo_fim:  # AAAA-MM-DD: ordem de texto = ordem de data
            raise ValueError("periodo_inicio deve ser anterior ou igual a periodo_fim")
        return self

    def prompts_ativos(self) -> dict[str, str]:
        """
        Converte a lista de prompts em um dicionário {topico: conteudo}.
        É o equivalente direto do nó "Separa Prompts".
        """
        return {p.topico: p.conteudo for p in self.prompts if p.topico and p.conteudo}


class TopicoResultado(BaseModel):
    """Resultado do processamento de um tópico."""
    topico: str
    ok: bool
    conteudo: dict | list | str | None = None
    erro: str | None = None


class RelatorioResponse(BaseModel):
    """Resposta final devolvida pelo webhook (equivale ao Respond to Webhook)."""
    contrato: str
    periodo_inicio: str
    periodo_fim: str
    topicos: list[TopicoResultado]
