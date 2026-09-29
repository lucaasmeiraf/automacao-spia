/*
 * Supra IA — tópicos do relatório (IN_51/2021) para o modal "Novo Prompt".
 *
 * Só dados. `chave` liga o item ao tópico do sistema (TOPICS / prompts/<chave>.md); item sem `chave`
 * ainda não existe como tópico e aparece desabilitado ("em breve").
 */
"use strict";

window.TOPICOS_RELATORIO = Object.freeze([
  { grupo: "ANÁLISE DE RELATÓRIO", itens: [
    { id: "1", label: "1 - Justificativa e Apresentação do Empreendimento", chave: "justificativa" },
    { id: "2", label: "2 - Mapa de Situação", chave: "mapa_situacao" },
    { id: "3", label: "3 - Resumo do Projeto", chave: "resumo_projeto" },
    { id: "3.3", label: "3.3 - OAEs", chave: "oaes" },
    { id: "3.4", label: "3.4 - RPFO", chave: "rpfo" },
    { id: "4", label: "4 - Diagrama de Ocorrências e Pontos de Passagem", chave: "diagrama_ocorrencias" },
    { id: "5", label: "5 - Histórico", chave: "historico" },
    { id: "6", label: "6 - Introdução", chave: "introducao" },
  ]},
  { grupo: "EMPRESA SUPERVISORA", itens: [
    { id: "7.1", label: "7.1 - Informações Contratuais - Supervisora", chave: "info_contratuais_supervisora" },
    { id: "7.2", label: "7.2 - Aditivos - Supervisora", chave: "termos_aditivos_supervisora" },
    { id: "7.3", label: "7.3 - Responsáveis Técnicos - Supervisora", chave: "responsaveis_tecnicos_supervisora" },
    { id: "7.4", label: "7.4 - Paralisação/Reinício", chave: "paralisacao_reinicio" },
    { id: "7.5", label: "7.5 - Apostilas", chave: "apostilas_supervisora" },
    { id: "7.6", label: "7.6 - Relação de Mobilização da Supervisora", chave: "mobilizacao_supervisora" },
    { id: "7.7", label: "7.7 - Atividades Executadas pela Supervisora", chave: "atividades_supervisora" },
  ]},
  { grupo: "EMPRESA CONSTRUTORA", itens: [
    { id: "8.1", label: "8.1 - Informações Contratuais - Construtora", chave: "info_contratuais_construtora" },
    { id: "8.2", label: "8.2 - Aditivos - Construtora", chave: "termos_aditivos_construtora" },
    { id: "8.3", label: "8.3 - Apostilas - Construtora", chave: "apostilas_construtora" },
    { id: "8.4", label: "8.4 - Relação de Mobilização da Construtora", chave: "mobilizacao_construtora" },
    { id: "8.5", label: "8.5 - Atividades Executadas pela Construtora", chave: "atividades_construtora" },
  ]},
  { grupo: "DEMAIS SEÇÕES", itens: [
    { id: "9", label: "9 - Acompanhamento Físico-Financeiro", chave: "acompanhamento_fisico_financeiro" },
    { id: "9.1", label: "9.1 - Acompanhamento Financeiro", chave: "acompanhamento_financeiro" },
    { id: "9.2", label: "9.2 - Acompanhamento Físico", chave: "acompanhamento_fisico" },
    { id: "10", label: "10 - Análise Crítica dos Cronogramas", chave: "analise_cronogramas" },
    { id: "11", label: "11 - Controle Pluviométrico", chave: "controle_pluviometrico" },
    { id: "12", label: "12 - Resumo de Avanço Físico", chave: "resumo_avanco_fisico" },
    { id: "13", label: "13 - Documentação Fotográfica", chave: "documentacao_fotografica" },
    { id: "14", label: "14 - Componente Ambiental", chave: "componente_ambiental" },
    { id: "15", label: "15 - Gestão da Qualidade", chave: "gestao_qualidade" },
    { id: "15.1", label: "15.1 - Ensaios de Laboratório da Construtora", chave: "ensaios_laboratorio_construtora" },
    { id: "15.2", label: "15.2 - Ensaios de Laboratório da Supervisora", chave: "ensaios_laboratorio_supervisora" },
    { id: "15.3", label: "15.3 - PVEGQ", chave: "pvegq" },
    { id: "16", label: "16 - Registros de Não Conformidades (RNC)", chave: "nao_conformidades" },
    { id: "17", label: "17 - Gestão Jurídica, Garantias e Seguros", chave: "gestao_juridica" },
    { id: "18", label: "18 - Gestão de Riscos e Interferências", chave: "gestao_riscos" },
    { id: "19", label: "19 - Atas e Correspondências", chave: "atas_correspondencias" },
    { id: "20", label: "20 - Gestão de Tratativas", chave: "gestao_tratativas" },
    { id: "21", label: "21 - Conclusão e Comentários", chave: "conclusao" },
    { id: "22", label: "22 - Termo de Encerramento", chave: "termo_encerramento" },
    { id: "23", label: "23 - Anexos", chave: "anexos" },
  ]},
]);
