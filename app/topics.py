"""
Registro declarativo dos tópicos (DEFINIÇÃO: como cada tópico funciona).

No n8n, cada tópico era uma sequência de ~4 nós repetidos (fetch → payload →
LLM → limpa retorno). Aqui, cada tópico é UMA entrada de configuração, e o
`pipeline.py` executa a sequência genericamente. Adicionar um tópico novo =
adicionar uma entrada neste dicionário.

Estar aqui NÃO significa rodar: se o tópico roda ou não (o "fio" do n8n) é a
ATIVAÇÃO, definida em `config/topics.yaml` (ver `app/topic_state.py`).

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

from dataclasses import dataclass


@dataclass(frozen=True)
class TopicConfig:
    # chave do tópico (igual à usada no dicionário de prompts / "Separa Prompts"
    # e em config/topics.yaml e prompts/<chave>.md)
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
    # apresentação (usados pela tela de configuração/resultado)
    titulo: str = ""
    grupo: str = ""

    @property
    def nome(self) -> str:
        """Nome legível para exibição (cai para a chave se não houver título)."""
        return self.titulo or self.chave


GRUPO_PRINCIPAL = "Relatório Principal"
GRUPO_SUPERVISORA = "Apresentação Supervisora"


# ------------------------------------------------------------------
# Registro de tópicos DEFINIDOS. A ordem deste dicionário é a ordem de
# exibição e de resposta. Tópicos comentados = ainda não portados.
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
        titulo="Justificativa",
        grupo=GRUPO_PRINCIPAL,
    ),
    "resumo_projeto": TopicConfig(
        chave="resumo_projeto",
        endpoint="resumo_projeto",
        model="gpt-4o-mini",
        max_tokens=800,
        html_fields=("resumo", "descricao"),
        estrategia="campo",
        campo_conteudo="resumo",
        titulo="Resumo do Projeto",
        grupo=GRUPO_PRINCIPAL,
    ),
    "historico": TopicConfig(
        chave="historico",
        endpoint="historico",
        model="gpt-4o-mini",
        max_tokens=800,
        html_fields=("resumo", "descricao"),
        estrategia="campo",
        campo_conteudo="resumo",
        titulo="Histórico",
        grupo=GRUPO_PRINCIPAL,
    ),
    "introducao": TopicConfig(
        chave="introducao",
        endpoint="introducao",
        model="gpt-4o-mini",
        max_tokens=800,
        html_fields=("resumo", "descricao"),
        estrategia="campo",
        campo_conteudo="resumo",
        titulo="Introdução",
        grupo=GRUPO_PRINCIPAL,
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
        titulo="OAEs",
        grupo=GRUPO_PRINCIPAL,
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
        titulo="RPFO",
        grupo=GRUPO_PRINCIPAL,
    ),
    "mapa_situacao": TopicConfig(
        chave="mapa_situacao",
        endpoint="mapa_situacao",
        model="gpt-4o",
        max_tokens=800,
        estrategia="imagem",
        titulo="Mapa de Situação",
        grupo=GRUPO_PRINCIPAL,
    ),
    "diagrama_ocorrencias": TopicConfig(
        chave="diagrama_ocorrencias",
        endpoint="diagrama_ocorrencias",
        model="gpt-4o",
        max_tokens=800,
        estrategia="imagem",
        titulo="Diagrama de Ocorrências",
        grupo=GRUPO_PRINCIPAL,
    ),

    # ── Grupo 2 (Apresentação Supervisora) ─────────────────────────

    "info_contratuais_supervisora": TopicConfig(
        chave="info_contratuais_supervisora",
        endpoint="info_contratuais_supervisora",
        model="gpt-4o-mini",
        max_tokens=800,
        estrategia="contratuais",
        titulo="Informações Contratuais",
        grupo=GRUPO_SUPERVISORA,
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
        titulo="Termos Aditivos",
        grupo=GRUPO_SUPERVISORA,
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
        titulo="Responsáveis Técnicos",
        grupo=GRUPO_SUPERVISORA,
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
        titulo="Paralisação / Reinício",
        grupo=GRUPO_SUPERVISORA,
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
        titulo="Apostilas",
        grupo=GRUPO_SUPERVISORA,
    ),
    "controle_pluviometrico": TopicConfig(
        chave="controle_pluviometrico",
        endpoint="controle_pluviometrico",
        model="gpt-4o-mini",
        max_tokens=1500,
        estrategia="pluviometrico",
        titulo="Controle Pluviométrico",
        grupo=GRUPO_SUPERVISORA,
    ),

    # ── Ainda não portados (implementação futura ou alto custo) ────
    # "documentacao_fotografica": TopicConfig(
    #     chave="documentacao_fotografica",
    #     endpoint="documentacao_fotografica",
    #     model="gpt-4o",
    #     max_tokens=1200,
    #     estrategia="doc_fotografica",
    #     titulo="Documentação Fotográfica",
    #     grupo=GRUPO_PRINCIPAL,
    # ),
}


def topico_configurado(chave: str) -> TopicConfig | None:
    return TOPICS.get(chave)
