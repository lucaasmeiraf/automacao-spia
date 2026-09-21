"""
Modelos de dados (Pydantic) para a entrada e a saída do webhook.

Equivale à validação do nó "If" do n8n (contrato / periodo_inicio /
periodo_fim obrigatórios) e à estrutura do array de prompts consumido pelo
nó "Separa Prompts".
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


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
