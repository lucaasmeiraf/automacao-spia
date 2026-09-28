"""
Seleção dos tópicos que rodam numa requisição (o "quais fios estão ligados" do n8n).

Um tópico roda quando as TRÊS condições valem:
  1. existe em `TOPICS` (app/topics.py);
  2. está ativo em `config/topics.yaml` (decisão do dev);
  3. há um prompt disponível: o do payload (`prompts[]`) tem prioridade; senão `prompts/<chave>.md`.

Só o dev decide o que a LLM analisa: tópico desligado é ignorado mesmo que o payload traga o
prompt dele (fica apenas registrado em log e NÃO aparece na resposta, como uma cadeia sem fio
no n8n).

Tópico ativo, porém sem nenhum prompt, é erro de configuração e aparece na resposta como
`ok=False` — silenciar isso esconderia o problema.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.models import TopicoResultado
from app.prompts_store import carregar_prompt
from app.topics import TOPICS, TopicConfig

logger = logging.getLogger(__name__)


@dataclass
class Selecao:
    # (config do tópico, prompt de sistema) na ordem de TOPICS
    executar: list[tuple[TopicConfig, str]] = field(default_factory=list)
    # Resultados de erro que já nascem prontos (sem prompt / tópico desconhecido)
    erros: list[TopicoResultado] = field(default_factory=list)
    # Chaves com prompt no payload que foram ignoradas por estarem desligadas
    ignorados: list[str] = field(default_factory=list)


async def selecionar_topicos(
    ativos: frozenset[str],
    prompts_payload: dict[str, str],
    prompts_dir: str,
) -> Selecao:
    selecao = Selecao()

    for chave, cfg in TOPICS.items():
        if chave not in ativos:
            if chave in prompts_payload:
                selecao.ignorados.append(chave)
                logger.info("Tópico '%s' desligado em topics.yaml: ignorado.", chave)
            continue

        prompt = prompts_payload.get(chave) or await carregar_prompt(chave, prompts_dir)
        if not prompt:
            logger.warning("Tópico '%s' ativo, mas sem prompt (payload ou arquivo).", chave)
            selecao.erros.append(
                TopicoResultado(
                    topico=chave,
                    ok=False,
                    erro=f"sem prompt: envie em prompts[] ou crie prompts/{chave}.md",
                )
            )
            continue

        selecao.executar.append((cfg, prompt))

    for chave in prompts_payload:
        if chave not in TOPICS:
            selecao.erros.append(
                TopicoResultado(
                    topico=chave,
                    ok=False,
                    erro="tópico ainda não configurado em app/topics.py",
                )
            )

    return selecao
