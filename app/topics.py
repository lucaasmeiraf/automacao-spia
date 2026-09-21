"""
Registro declarativo dos tópicos.

No n8n, cada tópico era uma sequência de ~4 nós repetidos (fetch → payload →
LLM → limpa retorno). Aqui, cada tópico é UMA linha de configuração, e o
`pipeline.py` executa a sequência genericamente. Adicionar um tópico novo =
adicionar uma entrada neste dicionário.

Estratégias disponíveis (campo `estrategia`):
  - "campo"        usa um único campo do registro (campo_conteudo) como user content.
  - "json"         serializa todo(s) o(s) registro(s) em JSON como user content.
                   Suporta campos_manter (filtro de colunas), html_fields (limpeza),
                   empty_as_array (envia [] se vazio) e campos_presenca (detecta vazio).
  - "imagem"       baixa imagem e analisa com gpt-4o (visão).
                   Delegado para app/processing/image.py.
  - "contratuais"  formata datas e valores monetários antes da LLM.
                   Delegado para app/processing/contratuais.py.
  - "pluviometrico" pipeline multi-fonte: SUPRA + Nominatim + Open-Meteo + LLM.
                   Delegado para app/processing/pluviometrico.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TopicConfig:
    # chave do tópico (igual à usada no dicionário de prompts / "Separa Prompts")
    chave: str
    # sufixo do endpoint: .../secao_ws/<endpoint>
    endpoint: str
    # modelo OpenAI (gpt-4o-mini p/ texto; gpt-4o p/ visão)
    model: str = "gpt-4o-mini"
    max_tokens: int = 1200
    # campos que contêm HTML e precisam de limpeza antes de enviar à LLM
    html_fields: tuple[str, ...] = ()
    # como montar o conteúdo do usuário para a LLM
    estrategia: str = "campo"
    # nome do campo usado quando estrategia == "campo"
    campo_conteudo: str = "resumo"
    # colunas a manter no registro (vazio = manter todas)
    campos_manter: tuple[str, ...] = ()
    # se True, envia [] à LLM quando não há dados reais
    empty_as_array: bool = False
    # campos cujo preenchimento indica que o registro tem dados reais
    campos_presenca: tuple[str, ...] = ()


# ------------------------------------------------------------------
# Registro de tópicos ativos.
# Tópicos comentados = ainda não portados ou desativados por padrão.
# ------------------------------------------------------------------
TOPICS: dict[str, TopicConfig] = {

    # ── Grupo 1 (Relatório Principal) ──────────────────────────────

    "justificativa": TopicConfig(
        chave="justificativa",
        endpoint="justificativa",
        model="gpt-4o-mini",
        max_tokens=1200,
        html_fields=("resumo", "descricao"),
        estrategia="campo",
        campo_conteudo="resumo",
    ),
    "resumo_projeto": TopicConfig(
        chave="resumo_projeto",
        endpoint="resumo_projeto",
        model="gpt-4o-mini",
        max_tokens=800,
        html_fields=("resumo", "descricao"),
        estrategia="campo",
        campo_conteudo="resumo",
    ),
    "historico": TopicConfig(
        chave="historico",
        endpoint="historico",
        model="gpt-4o-mini",
        max_tokens=800,
        html_fields=("resumo", "descricao"),
        estrategia="campo",
        campo_conteudo="resumo",
    ),
    "introducao": TopicConfig(
        chave="introducao",
        endpoint="introducao",
        model="gpt-4o-mini",
        max_tokens=800,
        html_fields=("resumo", "descricao"),
        estrategia="campo",
        campo_conteudo="resumo",
    ),
    "oaes": TopicConfig(
        chave="oaes",
        endpoint="oaes",
        model="gpt-4o-mini",
        max_tokens=1500,
        html_fields=("descricao",),
        estrategia="json",
        campos_manter=(
            "nome_oae", "tipo_oae", "tipo_intervencao", "estrutura_adotada",
            "concepcao_projeto", "vao_maximo", "extensao", "largura_plataforma",
            "km_inicial", "km_final", "coord_norte", "coord_leste",
            "gabarito_navegacao", "cota_na", "ano_estudo", "tipo_fundacao",
            "descricao",
        ),
    ),
    "rpfo": TopicConfig(
        chave="rpfo",
        endpoint="rpfo",
        model="gpt-4o-mini",
        max_tokens=1500,
        html_fields=("motivacao", "status_detalhado", "analista_responsavel"),
        estrategia="json",
        campos_manter=(
            "rpfo_numero", "rpfo_status", "local", "previsao",
            "analista_responsavel", "motivacao", "status_detalhado",
            "ultima_alteracao",
        ),
    ),
    "mapa_situacao": TopicConfig(
        chave="mapa_situacao",
        endpoint="mapa_situacao",
        model="gpt-4o",
        max_tokens=800,
        estrategia="imagem",
    ),
    "diagrama_ocorrencias": TopicConfig(
        chave="diagrama_ocorrencias",
        endpoint="diagrama_ocorrencias",
        model="gpt-4o",
        max_tokens=800,
        estrategia="imagem",
    ),

    # ── Grupo 2 (Apresentação Supervisora) ─────────────────────────

    "info_contratuais_supervisora": TopicConfig(
        chave="info_contratuais_supervisora",
        endpoint="info_contratuais_supervisora",
        model="gpt-4o-mini",
        max_tokens=800,
        estrategia="contratuais",
    ),
    "termos_aditivos_supervisora": TopicConfig(
        chave="termos_aditivos_supervisora",
        endpoint="termos_aditivos_supervisora",
        model="gpt-4o-mini",
        max_tokens=1200,
        html_fields=("objeto", "motivacao", "descricao", "observacao"),
        estrategia="json",
        empty_as_array=True,
        campos_presenca=("numero_termo", "numero", "num_termo"),
    ),
    "responsaveis_tecnicos_supervisora": TopicConfig(
        chave="responsaveis_tecnicos_supervisora",
        endpoint="responsaveis_tecnicos_supervisora",
        model="gpt-4o-mini",
        max_tokens=800,
        html_fields=("nome", "profissional", "observacao"),
        estrategia="json",
        empty_as_array=True,
        campos_presenca=("profissional", "nome", "nome_profissional"),
    ),
    "paralisacao_reinicio": TopicConfig(
        chave="paralisacao_reinicio",
        endpoint="paralisacao_reinicio",
        model="gpt-4o-mini",
        max_tokens=800,
        html_fields=("motivacao",),
        estrategia="json",
        campos_manter=(
            "numero_ordem", "tipo_documento", "data_emissao",
            "data_paralisacao_reinicio", "motivacao",
        ),
        empty_as_array=True,
        campos_presenca=("tipo_documento", "data_paralisacao_reinicio", "motivacao"),
    ),
    "apostilas_supervisora": TopicConfig(
        chave="apostilas_supervisora",
        endpoint="apostilas_supervisora",
        model="gpt-4o-mini",
        max_tokens=800,
        html_fields=("objeto", "reajustamento", "compensacao", "penalizacao", "observacao"),
        estrategia="json",
        campos_manter=(
            "numero_apostila", "data_assinatura", "objeto",
            "reajustamento", "compensacao", "penalizacao", "observacao",
        ),
        empty_as_array=True,
        campos_presenca=("numero_apostila", "numero", "num_apostila"),
    ),
    "controle_pluviometrico": TopicConfig(
        chave="controle_pluviometrico",
        endpoint="controle_pluviometrico",
        model="gpt-4o-mini",
        max_tokens=1500,
        estrategia="pluviometrico",
    ),

    # ── Desativados por padrão (implementação futura ou alto custo) ─
    # "documentacao_fotografica": TopicConfig(
    #     chave="documentacao_fotografica",
    #     endpoint="documentacao_fotografica",
    #     model="gpt-4o",
    #     max_tokens=1200,
    #     estrategia="doc_fotografica",
    # ),
}


def topico_configurado(chave: str) -> TopicConfig | None:
    return TOPICS.get(chave)
