"""
Modo `dry_run` do `POST /api/executar`: roda o tópico de verdade (fetch SUPRA, Nominatim,
Open-Meteo, montagem do payload) mas NÃO chama a OpenAI — nenhum token é gasto.

Funciona para qualquer estratégia sem mexer nos handlers: o `ctx.openai` do tópico é trocado por
`OpenAISimulado`, que só registra o corpo que SERIA enviado. Cada tópico recebe o seu simulador
(os tópicos rodam em paralelo), e o resultado devolvido ao cliente é o resumo dessas chamadas.
"""
from __future__ import annotations

import json
import math

from app.models import TopicoResultado


def resumir_chamada(body: dict) -> dict:
    """Resumo legível de um corpo de Chat Completions: modelo, tamanho e mensagens (sem base64)."""
    caracteres = 0
    imagens = 0
    mensagens = []
    for msg in body.get("messages", []):
        conteudo = msg.get("content")
        if isinstance(conteudo, str):
            caracteres += len(conteudo)
            mensagens.append({"role": msg.get("role"), "conteudo": conteudo})
            continue

        partes = []
        for parte in conteudo or []:
            if parte.get("type") == "text":
                texto = parte.get("text", "")
                caracteres += len(texto)
                partes.append({"tipo": "texto", "conteudo": texto})
            elif parte.get("type") == "image_url":
                imagens += 1
                url = (parte.get("image_url") or {}).get("url", "")
                # A imagem vai em base64 (pode ter MBs): só o tamanho interessa aqui.
                partes.append({"tipo": "imagem", "tamanho_base64": len(url)})
        mensagens.append({"role": msg.get("role"), "conteudo": partes})

    return {
        "modelo": body.get("model"),
        "max_tokens": body.get("max_tokens"),
        "caracteres_texto": caracteres,
        # Estimativa grosseira (~4 caracteres por token); imagens não entram na conta.
        "tokens_texto_estimados": math.ceil(caracteres / 4),
        "imagens": imagens,
        "mensagens": mensagens,
    }


class OpenAISimulado:
    """Substituto do OpenAIClient: registra a chamada e devolve um JSON mínimo."""

    def __init__(self) -> None:
        self.chamadas: list[dict] = []

    async def chat(self, body: dict) -> str:
        self.chamadas.append(resumir_chamada(body))
        return json.dumps({"dry_run": True})


def resultado_dry_run(resultado: TopicoResultado, chamadas: list[dict]) -> TopicoResultado:
    """Troca a "resposta da IA" (que não existiu) pelo resumo do que seria enviado."""
    if not resultado.ok:
        return resultado  # falha de fetch/montagem: é exatamente o que o dry-run deve mostrar

    conteudo: dict = {"dry_run": True, "chamadas_llm": chamadas}
    if not chamadas:
        conteudo["observacao"] = "o tópico terminou sem chamar a LLM"
        conteudo["resultado"] = resultado.conteudo
    return TopicoResultado(topico=resultado.topico, ok=True, conteudo=conteudo)
