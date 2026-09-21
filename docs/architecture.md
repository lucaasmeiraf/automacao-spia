# Supra AI — Documentação de Arquitetura

> Última atualização: 2026-09-21
> Autor: Lucas Meira / DNIT

---

## 1. Visão Geral

O **Supra AI** é um sistema de auditoria automatizada de Relatórios de Supervisão de obras rodoviárias do DNIT, seguindo os critérios da **Instrução Normativa IN_51/2021**.

O sistema recebe uma requisição com identificação de contrato e período, busca dados de múltiplas seções do relatório via API do sistema **SUPRA** (supra.dnit.gov.br), analisa cada seção com modelos de linguagem (OpenAI), e retorna um JSON consolidado com a avaliação de conformidade de cada seção.

### Origem

O projeto foi migrado de um fluxo no **n8n** (`Supra AI - n8n.json`, versão v3) para Python, visando maior controle, escalabilidade e facilidade de manutenção em ambientes de servidor.

### Ambientes

| Ambiente | Descrição |
|---|---|
| `dev` | Desenvolvimento local. Possui tela de visualização do retorno. |
| `homolog` | Homologação. Possui tela de visualização do retorno. |
| `prod` | Produção. Apenas automação — sem tela de visualização. |

---

## 2. Fluxo Original (n8n)

O fluxo n8n `Supra AI - v3` funciona da seguinte forma:

1. **Webhook POST** recebe `{ contrato, periodo_inicio, periodo_fim, prompts[] }`
2. **Validação (If)** — garante que os 3 campos obrigatórios estão preenchidos
3. **Separa Prompts** — mapeia cada prompt (system message) pelo seu tópico
4. **Define Variáveis Globais** — JWT SUPRA, token OpenAI, contrato, período
5. **Chains paralelas** — cada seção do relatório é processada independentemente
6. **Merge** — reúne todos os resultados
7. **Respond to Webhook** — devolve o JSON consolidado

### Nota sobre os nós desabilitados

Quatro nós estavam com `disabled: true` no n8n (versões antigas de agentes nativos do n8n) e **não foram migrados**:
- Agente Construtora
- Agente Acompanhamento Físico
- Agente Análise Crítica
- Agente Pluviométrico (nativo)

---

## 3. Arquitetura Python

### 3.1 Tecnologias

| Componente | Tecnologia | Justificativa |
|---|---|---|
| Servidor HTTP | **FastAPI** | Async nativo, substitui o Webhook do n8n |
| Paralelismo | **asyncio.gather** | Replica os branches paralelos do n8n |
| HTTP Client | **httpx.AsyncClient** | HTTP assíncrono, único client compartilhado |
| Config | **pydantic-settings** | Carrega `.env` com tipagem |
| Modelos | **Pydantic v2** | Validação de entrada e saída |
| LLM | **OpenAI API** (gpt-4o-mini / gpt-4o) | Mantém a mesma escolha do n8n |

### 3.2 Estrutura de Pastas

```
supra-ia/
├── CLAUDE.md                     # Instruções para Claude Code
├── docs/
│   └── architecture.md           # Este documento
├── app/
│   ├── main.py                   # Entry point FastAPI
│   ├── config.py                 # Settings (pydantic-settings)
│   ├── models.py                 # Pydantic: request / response / resultado
│   ├── topics.py                 # Registro declarativo de todos os tópicos
│   ├── logging_config.py         # Setup de logging
│   ├── clients/
│   │   ├── dnit.py               # API SUPRA (GET secao_ws + download imagem)
│   │   ├── openai_client.py      # OpenAI Chat Completions (via httpx)
│   │   ├── openmeteo.py          # Open-Meteo (histórico meteorológico)
│   │   └── nominatim.py          # Nominatim / OSM (geocodificação)
│   └── processing/
│       ├── context.py            # ProcessingContext (agrupa clientes)
│       ├── pipeline.py           # Pipeline genérico + roteamento
│       ├── records.py            # Helpers: limpar_registro, detectar_vazio
│       ├── html_clean.py         # strip_html (porta do n8n)
│       ├── image.py              # Handler imagens (mapa_situacao, diagrama)
│       ├── contratuais.py        # Handler info_contratuais (datas, moeda)
│       └── pluviometrico.py      # Handler pluviométrico (multi-fonte)
├── tests/
│   ├── test_html_clean.py
│   ├── test_pipeline.py
│   └── test_pluviometrico.py
├── .env                          # Credenciais locais (NÃO commitar)
├── .env.example                  # Template de variáveis (sim commitar)
├── .gitignore
├── requirements.txt
└── Dockerfile
```

### 3.3 Sistema de Toggle de Tópicos

O tópico só executa quando **ambas** as condições são verdadeiras:

1. O tópico está listado em `app/topics.py` (no dicionário `TOPICS`)
2. O payload da requisição contém o prompt correspondente em `prompts[]`

Para desativar um tópico, basta comentá-lo ou removê-lo de `TOPICS`. Para ativar novamente, descomente.

### 3.4 Estratégias de Processamento (`estrategia`)

| Estratégia | Descrição | Handler |
|---|---|---|
| `"campo"` | Extrai um campo do 1º registro como texto | `pipeline.py` |
| `"json"` | Serializa todos os registros como JSON, com filtro de campos (`campos_manter`), limpeza HTML (`html_fields`), detecção de vazio (`empty_as_array`) | `pipeline.py` |
| `"imagem"` | Baixa imagem e analisa com gpt-4o (visão) | `processing/image.py` |
| `"contratuais"` | Formata datas e valores monetários antes da LLM | `processing/contratuais.py` |
| `"pluviometrico"` | Pipeline 4 fontes: SUPRA + Nominatim + Open-Meteo + LLM | `processing/pluviometrico.py` |

### 3.5 Paralelismo

Os tópicos de uma mesma requisição são executados em paralelo via `asyncio.gather`, replicando o comportamento das chains paralelas do n8n.

### 3.6 Gestão de Ambientes

Cada ambiente usa seu próprio arquivo `.env`:

```bash
# .env (dev)
OPENAI_API_KEY=sk-proj-...
DNIT_TOKEN=eyJ...
DNIT_BASE_URL=https://supra.dnit.gov.br/index_cgcont_common.php/cgcont/ai
OPENAI_BASE_URL=https://api.openai.com/v1
LEGENDAS=1 - Bom | 2 - Chuva | 3 - Impraticável | 5 - Instável | 4 - Não houveram atividades
```

Veja `.env.example` para todos os campos disponíveis.

---

## 4. Endpoints SUPRA utilizados

Base URL: `https://supra.dnit.gov.br/index_cgcont_common.php/cgcont/ai/relatorio/secao_ws/`

Todos os endpoints GET usam os parâmetros de query:
- `contrato`
- `periodo_incio` (**atenção: typo original, sem acento, mantido por compatibilidade**)
- `periodo_fim`

E o header: `token: <JWT>`

| Seção | Endpoint (sufixo) | Método |
|---|---|---|
| Capa / Infos e Localização | `capa` | GET |
| Justificativa | `justificativa` | GET |
| Mapa de Situação | `mapa_situacao` | GET |
| Resumo do Projeto | `resumo_projeto` | GET |
| Diagrama de Ocorrências | `diagrama_ocorrencias` | GET |
| OAEs | `oaes` | GET |
| RPFO | `rpfo` | GET |
| Histórico | `historico` | GET |
| Introdução | `introducao` | GET |
| Infos. Contratuais Supervisora | `info_contratuais_supervisora` | GET |
| Termos Aditivos Supervisora | `termos_aditivos_supervisora` | GET |
| Responsáveis Técnicos Supervisora | `responsaveis_tecnicos_supervisora` | GET |
| Paralisação / Reinício | `paralisacao_reinicio` | GET |
| Apostilas Supervisora | `apostilas_supervisora` | GET |
| Controle Pluviométrico | `controle_pluviometrico` | GET |
| Documentação Fotográfica | `documentacao_fotografica` | POST (desativado) |

Download de arquivos (imagens): `GET /cgcont/ai/arquivo/download_ws?contrato=...&nome_arquivo=...`

---

## 5. Formato de Entrada e Saída

### Entrada (POST /webhook/relatorio)

```json
{
  "contrato": "00 00493/2013",
  "periodo_inicio": "2025-10-01",
  "periodo_fim": "2025-10-31",
  "prompts": [
    { "topico": "justificativa", "conteudo": "Você é um auditor..." },
    { "topico": "resumo_projeto", "conteudo": "..." }
  ]
}
```

### Saída

```json
{
  "contrato": "00 00493/2013",
  "periodo_inicio": "2025-10-01",
  "periodo_fim": "2025-10-31",
  "topicos": [
    {
      "topico": "justificativa",
      "ok": true,
      "conteudo": {
        "conforme": "Conforme",
        "motivo": "...",
        "infos": "..."
      }
    }
  ]
}
```

---

## 6. Fluxo do Controle Pluviométrico (mais complexo)

O tópico de controle pluviométrico envolve 4 fontes de dados:

```
SUPRA /controle_pluviometrico  +  SUPRA /capa
        ↓                               ↓
Extrai registros diários        Extrai BR, UF, município
        ↓
Nominatim (geocodifica "BR-XXX, Município, UF, Brasil" → lat/lon)
        ↓ (fallback: centroide da UF)
Open-Meteo (dados históricos de precipitação, temperatura, vento)
        ↓
Identifica Divergências (cruza dia a dia: SUPRA vs Open-Meteo)
        ↓
Payload LLM (monta prompt com divergências)
        ↓
OpenAI gpt-4o-mini
        ↓
Análise de conformidade pluviométrica
```

**Lógica de inferência de status** (Open-Meteo → status esperado):
- `precipitação >= 10mm` → Impraticável
- `weathercode >= 95` (tempestade) → Impraticável
- `vento >= 50km/h` → Impraticável
- `temperatura >= 42°C` → Impraticável
- `temperatura >= 38°C` → Instável
- `precipitação >= 1mm` → Chuva
- `precipitação >= 0.1mm` → Instável
- Caso contrário → Bom

---

## 7. Tópicos implementados (Etapa 1 concluída)

| Tópico | Estratégia | Modelo | Status |
|---|---|---|---|
| `justificativa` | campo | gpt-4o-mini | ✅ |
| `resumo_projeto` | campo | gpt-4o-mini | ✅ |
| `historico` | campo | gpt-4o-mini | ✅ |
| `introducao` | campo | gpt-4o-mini | ✅ |
| `oaes` | json + campos_manter | gpt-4o-mini | ✅ |
| `rpfo` | json + campos_manter | gpt-4o-mini | ✅ |
| `mapa_situacao` | imagem | gpt-4o | ✅ |
| `diagrama_ocorrencias` | imagem | gpt-4o | ✅ |
| `info_contratuais_supervisora` | contratuais | gpt-4o-mini | ✅ |
| `termos_aditivos_supervisora` | json + empty_as_array | gpt-4o-mini | ✅ |
| `responsaveis_tecnicos_supervisora` | json + empty_as_array | gpt-4o-mini | ✅ |
| `paralisacao_reinicio` | json + empty_as_array | gpt-4o-mini | ✅ |
| `apostilas_supervisora` | json + empty_as_array | gpt-4o-mini | ✅ |
| `controle_pluviometrico` | pluviometrico | gpt-4o-mini | ✅ |
| `documentacao_fotografica` | — | gpt-4o | 🔒 desativado |

---

## 8. Issues Futuras (Backlog)

- [ ] Implementar seção Construtora (info_contratuais, aditivos, apostilas, atividades)
- [ ] Acompanhamento Físico e Financeiro
- [ ] Análise Crítica dos Cronogramas
- [ ] Gestão de Qualidade, Componente Ambiental, Gestão Jurídica
- [ ] Documentação Fotográfica (`doc_fotografica` — POST form-data, análise por imagem)
- [ ] Tela de visualização (dev/homolog)
- [ ] Ajuste de prompts por seção conforme feedback dos resultados

---

## 9. Observações Técnicas

- O parâmetro `periodo_incio` (sem "í") é um **typo existente na API SUPRA** e deve ser mantido exatamente assim — ver `app/clients/dnit.py`
- Tokens JWT e chaves de API **nunca devem ser commitados** — usar `.env` (adicionado ao `.gitignore`)
- Para imagens (Mapa de Situação, Diagrama de Ocorrências), o modelo usado é `gpt-4o` com suporte a visão — custo significativamente maior que `gpt-4o-mini`
- O `ProcessingContext` é criado por requisição em `main.py`, agrupa todos os clientes HTTP e é passado para `processar_topico()`
- Os clientes Open-Meteo e Nominatim são APIs públicas sem autenticação; o User-Agent `SupraDNIT/1.0` é obrigatório por política de uso
