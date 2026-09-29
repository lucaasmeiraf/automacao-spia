# Supra AI — Documentação de Arquitetura

> Última atualização: 2026-09-28
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

### Nota sobre a fiação do n8n (2026-09-28)

Cada tópico é uma **cadeia independente**: `fetch → Payload → LLM → Limpa Retorno → Merge`
(ex.: `Justificativa → Payload Justificativa → LLM14 → Limpa Retorno Justificativa → Merge[0]`).
Ligar ou desligar um tópico no n8n = ligar/desligar o fio que sai de `Define Variáveis Globais` para o
primeiro nó da cadeia. No JSON exportado só a cadeia do Controle Pluviométrico
(`Infos e Localização → Controle Pluviométrico → …`) estava ligada; as demais cadeias estavam soltas
**de propósito**, para testar um tópico por vez sem gastar créditos de API. A intenção é ter **todas**
ligadas em operação normal. Ver §10 (o "fio" vira um interruptor numa tela de configuração).

Nós que existem no n8n e não estão em nenhuma cadeia que chegue ao `Merge`: Documentação Fotográfica
(desligada por custo), Nominatim reverse/`Limpa Dados` (sem entrada), Construtora e Atividades Executadas
(Supervisora/Construtora) — estas terminam em `Limpa Retorno` sem ir ao `Merge`.

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
│   ├── main.py                   # Entry point FastAPI (create_app: webhook, /health, rotas por ENV)
│   ├── config.py                 # Settings (pydantic-settings)
│   ├── models.py                 # Pydantic: request / response / resultado
│   ├── topics.py                 # DEFINIÇÃO declarativa dos tópicos (como funcionam)
│   ├── topic_state.py            # ATIVAÇÃO: lê/grava config/topics.yaml (o "fio" do n8n), falha segura
│   ├── topicos_extras.py         # Tópicos campo/json criados pela tela (config/topicos_extras.yaml)
│   ├── prompts_store.py          # Prompts por tópico: prompts/<chave>.md (lê/grava)
│   ├── arquivos.py               # Gravação atômica (temporário + os.replace)
│   ├── log_buffer.py             # Buffer de logs em memória + id de execução (painel de logs, só dev)
│   ├── logging_config.py         # Setup de logging
│   ├── security/                 # Segurança (§10.10)
│   │   ├── passwords.py          #   Argon2id (argon2-cffi): gerar_hash / verificar
│   │   ├── sessions.py           #   Sessões no servidor (token opaco, CSRF, expiração)
│   │   ├── throttle.py           #   Limite de tentativas (força bruta) com espera crescente
│   │   ├── deps.py               #   exigir_chave_webhook, exigir_admin (+CSRF nas escritas)
│   │   └── headers.py            #   CSP, nosniff, X-Frame-Options, no-store…
│   ├── routers/
│   │   ├── auth.py               # /api/auth/login | me | logout (só ENV=dev)
│   │   ├── admin.py              # /api/topicos | prompts | executar | logs (só ENV=dev, admin)
│   │   └── ui.py                 # / → /ui/config, /ui/config, /ui/static (só ENV=dev)
│   ├── ui/                       # Telas (HTML/CSS/JS puro, sem build)
│   │   ├── config.html           #   Tela de configuração
│   │   └── static/               #   app.css, config.js
│   ├── clients/
│   │   ├── dnit.py               # API SUPRA (GET secao_ws + download imagem)
│   │   ├── openai_client.py      # OpenAI Chat Completions (via httpx)
│   │   ├── openmeteo.py          # Open-Meteo (histórico meteorológico)
│   │   └── nominatim.py          # Nominatim / OSM (geocodificação)
│   └── processing/
│       ├── context.py            # ProcessingContext (agrupa clientes)
│       ├── execucao.py           # Seleção + execução paralela (webhook e /api/executar)
│       ├── dry_run.py            # Dry-run: OpenAI simulada, resumo do que seria enviado
│       ├── pipeline.py           # Pipeline genérico + roteamento
│       ├── selecao.py            # Quais tópicos rodam (ativo + prompt) — regra da §3.3
│       ├── records.py            # Helpers: limpar_registro, detectar_vazio
│       ├── html_clean.py         # strip_html (porta do n8n)
│       ├── image.py              # Handler imagens (mapa_situacao, diagrama)
│       ├── contratuais.py        # Handler info_contratuais (datas, moeda)
│       └── pluviometrico.py      # Handler pluviométrico (multi-fonte)
├── scripts/
│   ├── gerar_hash_senha.py       # gera a linha ADMIN_USERS do .env (hash argon2)
│   └── gerar_chave.py            # gera WEBHOOK_API_KEY
├── pytest.ini                    # pythonpath=. (pytest puro funciona)
├── config/
│   ├── topics.yaml               # Ativação dos tópicos (true/false), versionado
│   └── topicos_extras.yaml       # Tópicos criados pela tela (definição), versionado
├── prompts/
│   └── <chave>.md                # Prompt de sistema por tópico (padrão; o payload sobrepõe)
├── tests/
│   ├── test_html_clean.py
│   ├── test_pipeline.py
│   ├── test_pluviometrico.py
│   ├── test_topic_state.py
│   ├── test_prompts_store.py
│   ├── test_selecao.py
│   ├── test_webhook_selecao.py   # seleção + chave de API do webhook
│   ├── test_security_core.py     # argon2, sessões, limitador
│   ├── test_auth_api.py          # login/me/logout, CSRF, rotas por ambiente, /docs
│   ├── test_admin_api.py         # /api/topicos, prompts, executar, logs (+ casos negativos)
│   ├── test_dry_run.py
│   ├── test_log_buffer.py
│   ├── test_ui.py                # tela: rotas por ambiente + segurança estática do front
│   ├── test_settings_seguranca.py# leitura do .env (hash com '$', chaves curtas…)
│   ├── conftest.py / helpers.py  # Settings hermético e app sem lifespan
├── .env                          # Credenciais locais (NÃO commitar)
├── .env.example                  # Template de variáveis (sim commitar)
├── .gitignore
├── requirements.txt
└── Dockerfile
```

### 3.3 Sistema de Toggle de Tópicos

*(Atualizado em 2026-09-28 — fase 1 da §10.)* Separamos **definição** de **ativação**. Um tópico só
executa quando **as três** condições são verdadeiras:

1. **Existe** em `app/topics.py` (`TOPICS`) — define *como* o tópico funciona;
2. Está **`true`** em `config/topics.yaml` — decisão do dev sobre *se* roda (o "fio" do n8n);
3. Há um **prompt**: o do payload (`prompts[]`) tem prioridade; senão vale `prompts/<chave>.md`.

Só o dev decide o que a LLM analisa: tópico `false` (ou ausente) no YAML é ignorado **mesmo que o
payload traga o prompt dele** — não roda, não aparece na resposta (só log). Tópico ativo **sem nenhum
prompt** aparece na resposta como `ok: false` (erro de configuração não pode ser silencioso).
Chave desconhecida no payload continua voltando como erro. A resposta sai na ordem de `TOPICS`.

`config/topics.yaml` é relido a cada requisição (cache por mtime/tamanho): editar tem efeito imediato.
**Falha segura**: arquivo ausente, YAML inválido ou valor que não seja `true`/`false` ⇒ nenhum tópico
roda e a API responde **503** com mensagem genérica (o detalhe fica só no log).

### 3.4 Estratégias de Processamento (`estrategia`)

| Estratégia | Descrição | Handler |
|---|---|---|
| `"campo"` | Extrai um campo do 1º registro como texto | `pipeline.py` |
| `"json"` | Serializa todos os registros como JSON, com filtro de campos (`campos_manter`), limpeza HTML (`html_fields`), detecção de vazio (`empty_as_array`) | `pipeline.py` |
| `"imagem"` | Baixa imagem e analisa com gpt-4o (visão) | `processing/image.py` |
| `"contratuais"` | Formata datas e valores monetários antes da LLM | `processing/contratuais.py` |
| `"pluviometrico"` | Pipeline 4 fontes: SUPRA + Nominatim + Open-Meteo + LLM | `processing/pluviometrico.py` |

### 3.5 Paralelismo

Os tópicos de uma mesma requisição são executados em paralelo via `asyncio.gather` (em `app/processing/execucao.py`, compartilhado pelo webhook e pelo `POST /api/executar`), replicando o comportamento das chains paralelas do n8n.

### 3.6 Gestão de Ambientes

Cada ambiente usa seu próprio arquivo `.env`:

```bash
# .env (dev)
ENV=dev                      # dev | homolog | prod (padrão: prod)
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

- `nome_arquivo` vem do `secao_ws` do tópico (formato real, 2026-09-29: `nome_arquivo`, `nomeOriginalArquivo`,
  `desc_arquivo` — `"None"` quando vazio — e `ultima_alteracao`).
- Resposta (pelo fluxo n8n, `responseFormat: json`): `{"resultado": {"base64": "...", "mime_type": "..."}}`.
  `DnitClient.download_arquivo` também tolera binário cru e confirma o tipo pelos bytes da imagem.
- Estrutura do resultado dos tópicos de imagem = chaves dos nós "Limpa Retorno" do n8n (Mapa:
  `elementos_cartograficos` mapa_brasil/mapa_regional/malha_viaria/corpos_dagua/folha_a4_rm2 e
  `informacoes_legenda` rodovia/trecho/segmento/extensao/codigo_snv; Diagrama: `pontos_passagem`,
  `ocorrencias_projeto`, `apresentacao`). O prompt precisa pedir essas mesmas chaves.

**Interpretação da resposta da LLM (2026-09-29)** — `app/processing/llm_resposta.py`, usado por todas as
estratégias: modo JSON da OpenAI quando o prompt pede JSON; remoção de ```` ```json ````; JSON recortado do meio
de texto; fallback por regex (`erro_parse: true` + `resposta_ia`). O resultado é sempre um objeto com
`identificador`, `conforme` e `motivo` — antes, resposta sem JSON virava texto solto. `infos` na estratégia
`json` é a lista enviada à LLM (antes, texto JSON). O pluviométrico mantém toda a resposta da IA
(`distribuicao_dias`, `conformidade_in51`, `analise_impacto`, `checklist`), como no n8n.
- Token inválido: a SUPRA responde **307** para a página inicial (não 401) → `SupraTokenRecusado`.

---

## 5. Formato de Entrada e Saída

### Entrada (POST /webhook/relatorio)

**Autenticação (desde 2026-09-28):** header `X-API-Key: <WEBHOOK_API_KEY>` obrigatório. Sem ele: `401`;
chave não configurada no servidor: `503` (falha fechada); muitas chaves erradas seguidas: `429` com `Retry-After`.
`prompts[]` é opcional: tópico ativo sem prompt no payload usa `prompts/<chave>.md`.

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
- [ ] Atividades Executadas da Supervisora (`atividades_supervisora_descricao`) — pertence à Apresentação Supervisora; não migrado
- [x] ~~Proteger `POST /webhook/relatorio` e desativar `/docs`~~ — feito na fase 2a (2026-09-28)
- [x] ~~API de configuração (tópicos, prompts, executar, logs)~~ — feito na fase 2b (2026-09-28)
- [x] ~~Tela de configuração (dev)~~ — feito na fase 3 (2026-09-28)
- [ ] Tela de resultado (dev/homolog) — **§10, fase 4**
- [ ] (opcional) Resultado por tópico conforme termina (SSE) em vez de esperar todos — §10.6
- [ ] Sessões de login ficam em memória (1 processo): migrar para armazenamento compartilhado se um dia rodar com vários processos
- [ ] Ajuste de prompts por seção conforme feedback dos resultados
- [ ] Endurecer o parse da LLM (remover blocos ```` ```json ````, avaliar `response_format: json_object`) — o n8n também não tinha
- [ ] Validar o valor de `conforme` (`Conforme` / `Atenção` / `Não Conforme`) no resultado
- [ ] Distinguir **erro de acesso da SUPRA** (`status: false` + "Usuário não cadastrado ou dados inválidos") de
  **seção sem dados**: hoje os dois viram conteúdo vazio e seguiriam para a LLM (custo + "Não Conforme"
  enganoso). Proposta: `ok: false` sem chamar a LLM no primeiro caso. Descoberto no teste de 2026-09-28;
  aguardando confirmação (muda o comportamento herdado do n8n)
- [ ] Formato de saída: o n8n devolvia `analises[]`; o Python devolve `topicos[]` (`topico`, `ok`, `conteudo`, `erro`). Documentar a mudança para quem consumir. *(Correção: o campo `id_contrato` do nó final do n8n nunca foi definido em "Define Variáveis Globais" — saía sempre ausente; não é uma lacuna do Python.)*

---

## 9. Observações Técnicas

- O parâmetro `periodo_incio` (sem "í") é um **typo existente na API SUPRA** e deve ser mantido exatamente assim — ver `app/clients/dnit.py`
- Tokens JWT e chaves de API **nunca devem ser commitados** — usar `.env` (adicionado ao `.gitignore`)
- Para imagens (Mapa de Situação, Diagrama de Ocorrências), o modelo usado é `gpt-4o` com suporte a visão — custo significativamente maior que `gpt-4o-mini`
- O `ProcessingContext` é criado por requisição (`ProcessingContext.da_app(app.state)`, no webhook e no `/api/executar`), agrupa todos os clientes HTTP e é passado para `processar_topico()`
- Os clientes Open-Meteo e Nominatim são APIs públicas sem autenticação; o User-Agent `SupraDNIT/1.0` é obrigatório por política de uso
- **Rede do DNIT (2026-09-28):** o proxy faz inspeção de TLS e reassina sites externos com a CA interna
  `DNIT_SubCA_SSL`. Por isso o `AsyncClient` (em `create_app`) valida TLS com `ssl.create_default_context()`
  (repositório do sistema) em vez do `certifi`; a verificação continua ativa. O `verify` vai no
  `AsyncHTTPTransport`, porque com `transport=` o httpx ignora o `verify` do client. Em contêiner Linux na
  rede do DNIT, instale a CA interna no sistema do contêiner. O mesmo firewall bloqueia `api.openai.com`
  (categoria `DNIT_DENY`): ver `docs/andamento.md`
- **Proteção do servidor da SUPRA (2026-09-28):** com ~15 chamadas simultâneas o proxy da SUPRA devolve
  "502 Proxy Error" para algumas (uma a uma, todas funcionam). `DnitClient` limita as requisições simultâneas
  (`DNIT_MAX_CONCORRENCIA`, padrão 4, via `asyncio.Semaphore` por instância — há uma por processo) e repete
  502/503/504 até `DNIT_RETRIES` vezes (padrão 2, espera `DNIT_RETRY_ESPERA` × tentativa, fora do semáforo).
  Só GETs de leitura; outros status falham na hora, como antes. Timeouts e respostas não-JSON **não** são
  repetidos (ver `docs/andamento.md`)
- **Token SUPRA:** JWT HS256 com `{"user": e-mail, "pass": senha}` assinado com a `encryption_key` do SUPRA;
  enviado no header `token`. Respostas: "Token inválido." = assinatura errada; "Usuário não cadastrado ou
  dados inválidos." = e-mail/senha errados. Endpoint alternativo documentado pela SUPRA:
  `relatorio/contexto_ws` (agrega todas as seções numa chamada) — não usado; avaliar no futuro
- Status do projeto, bloqueios e histórico de entregas: `docs/andamento.md`

---

## 10. Configuração visual de tópicos e telas por ambiente

> **Status (2026-09-28): proposta aprovada. Fases 1, 2a, 2b e 3 ✅ implementadas (base, segurança, API de configuração, tela de configuração); 4 pendente (ver 10.8).**
> Decisões do Lucas incorporadas em 10.9. Segurança/autenticação (exigência dele) em 10.10.

### 10.1 Objetivo

Reproduzir no Python o "fio" do n8n: escolher, sem editar código nem redeploy, **quais tópicos rodam**
numa execução. Motivação principal: testar/ajustar um tópico por vez sem rodar (e pagar) todos os outros.

### 10.2 Modelo: definição (código) × ativação (estado)

| | Onde vive | Quem muda | Exemplo |
|---|---|---|---|
| **Definição** do tópico — *como* ele funciona | `app/topics.py` (`TOPICS`), versionado | desenvolvedor | endpoint, estratégia, modelo, campos |
| **Definição** de tópico simples criado pela tela | `config/topicos_extras.yaml`, versionado | tela de configuração (só `dev`) | mesmos campos, só `campo`/`json` |
| **Ativação** — *se* ele roda | `config/topics.yaml`, versionado | tela de configuração (só `dev`) | `justificativa: true` |
| **Prompt** — instrução ao LLM | payload da requisição (`prompts[]`) | sistema chamador | igual ao n8n |

`config/topics.yaml` (chave → booleano; agrupamento/título/ordem ficam no código, em `TopicConfig`):

```yaml
topicos:
  justificativa: true
  resumo_projeto: true
  mapa_situacao: false      # gpt-4o (visão): caro, ligar só quando necessário
  controle_pluviometrico: true
```

**Regra de execução** (implementada — detalhes na §3.3): um tópico roda se
1. existe em `TOPICS` **e**
2. está `true` em `topics.yaml` **e**
3. há prompt (payload ou `prompts/<chave>.md`; o payload prevalece).

Tópico ausente do YAML = desligado. Tópico desligado com prompt no payload é **omitido** da resposta
(como no n8n, onde cadeia sem fio não aparece) e registrado em log.

> **Mudança de comportamento em relação à versão anterior:** antes, "o payload traz o prompt" era
> condição para rodar (o sistema chamador escolhia o subconjunto). Agora o dev decide o conjunto no
> YAML, e o payload só *sobrepõe o texto* do prompt. Um chamador que enviava só alguns prompts passa a
> receber `ok: false` ("sem prompt") para os tópicos ativos que ficaram sem prompt — a menos que exista
> `prompts/<chave>.md`. Se preferir que o payload também restrinja o conjunto, é uma linha em `selecao.py`.

Os tópicos são independentes entre si (o pluviométrico busca `capa` por conta própria), então ligar/desligar
qualquer subconjunto é seguro. Se um dia houver dependência entre tópicos, `TopicConfig` ganha
`depende_de` e a tela bloqueia combinações inválidas.

### 10.3 Ambientes

Variável `ENV` (`dev` | `homolog` | `prod`) em `app/config.py` / `.env` — **implementada**. O padrão é
`prod` (falha fechada: se esquecerem a variável, nenhuma rota de configuração será exposta) e valores
fora da lista são rejeitados na inicialização. As rotas condicionais por ambiente chegam na fase 2.

| Recurso | dev | homolog | prod |
|---|---|---|---|
| `POST /webhook/relatorio` (automação) | ✅ | ✅ | ✅ |
| Tela de **resultado** (tópicos) | ✅ | ✅ | ❌ |
| Tela de **configuração** (ligar/desligar, executar, dry-run) | ✅ | ❌ | ❌ |
| API de configuração (`/api/topicos` PUT, `/api/executar`) | ✅ | ❌ | ❌ |

**A restrição é feita no servidor**: os routers de configuração só são registrados
(`app.include_router`) quando `ENV == "dev"`. Esconder o botão na tela não basta. Em homolog/prod essas
rotas devolvem 404, não 403 (não revelam que existem).

Promoção dev → homolog: a configuração sai do `dev` como um commit em `config/topics.yaml`; homolog/prod
apenas leem o arquivo que vem no deploy. Assim o que foi validado em dev é exatamente o que sobe.

### 10.4 Como o Python lê o estado

- `topics.yaml` é lido **a cada requisição**, com cache por `mtime` (custo desprezível). Funciona com
  vários workers do uvicorn e dispensa reiniciar o servidor após mexer na tela.
- A tela grava de forma atômica (arquivo temporário + `os.replace`) para nunca deixar YAML pela metade.
- YAML inválido ou ausente → falha segura: nenhum tópico roda e o erro aparece em log e na tela
  (nunca "liga tudo" por engano — isso geraria custo).
- Docker/dev: montar `config/` como volume para as edições sobreviverem ao recriar o contêiner.

### 10.5 API (JSON) — a tela é só um cliente dela

Todas as rotas `dev` abaixo exigem sessão de **admin** (`Depends(exigir_admin)`, que já cobra CSRF nas escritas).

| Método e rota | Ambientes | Função | Estado |
|---|---|---|---|
| `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout` | dev | Login do admin, sessão e token CSRF | ✅ fase 2a |
| `POST /webhook/relatorio` | todos | Automação externa (header `X-API-Key`) | ✅ fase 2a |
| `GET /api/topicos` | dev | Lista tópicos: chave, título, grupo, estratégia, modelo, `max_tokens`, endpoint, `custo`, `ativo`, `implementado`, `tem_prompt`; `configuracao_valida` + mensagem genérica se o YAML estiver inválido | ✅ 2b |
| `POST /api/topicos` | dev | Cria tópico `campo`/`json` (mesmos campos de `TopicConfig`; chave `^[a-z][a-z0-9_]{1,63}$`, endpoint `^[a-z0-9_]{1,80}$`, nomes de campo `^[A-Za-z0-9_]{1,64}$`, modelo `gpt-4o-mini`/`gpt-4o`, `max_tokens` 50–4096). Chave repetida = 409. Grava `config/topicos_extras.yaml` (atômico) e acrescenta a `TOPICS` na hora; nasce desligado e sem prompt. Lido de novo em `create_app` (falha segura: arquivo ruim = nenhum extra; entrada ruim = só ela ignorada) | ✅ 2026-09-29 |
| `PUT /api/topicos` | dev | `{"topicos": {chave: bool}}` aplicado **sobre o estado atual** (só as chaves enviadas mudam; valores precisam ser booleanos; chave fora de `TOPICS` = 422). Regrava o YAML inteiro (todos os tópicos, por grupo) de forma atômica; YAML inválido é consertado partindo de "tudo desligado" | ✅ 2b |
| `GET /api/prompts`, `GET/PUT /api/prompts/{chave}` | dev | Lê/salva `prompts/<chave>.md` (`{"conteudo": ...}`; chave fora de `TOPICS` = 404; vazio ou > 50 000 caracteres = 422; CRLF normalizado; gravação atômica) | ✅ 2b |
| `DELETE /api/prompts/{chave}` | dev | Apaga `prompts/<chave>.md` (idempotente: sem arquivo = 200 com `conteudo: null`; chave fora de `TOPICS` = 404). O tópico fica sem prompt | ✅ 2026-09-29 |
| `POST /api/executar` | dev | **O botão "Executar"**: `{contrato, periodo_inicio, periodo_fim, prompts?, topicos?, dry_run?}`; mesma execução do webhook (`processing/execucao.py`); devolve a resposta por tópico + `execucao_id`, `dry_run`, `duracao_ms` | ✅ 2b |
| `GET /api/logs` | dev | Últimas linhas de log (buffer em memória, 1000 linhas): `?nivel=INFO&execucao=<id>&apos=<seq>&limite=200` | ✅ 2b |
| `GET /api/execucoes`, `GET /api/execucoes/{id}` | dev, homolog | Respostas das execuções feitas pela tela | 4 |
| `GET /ui/config` (+ `/` e `/ui/static/*`) | dev | Tela de configuração (página estática) | ✅ 3 |
| `GET /ui/resultado` | dev, homolog | Tela de resultado | 4 |

**Modo `dry_run`** (resolve a preocupação com créditos): executa `fetch` + montagem do payload e **não chama
a OpenAI**; devolve o que *seria* enviado (tamanho, modelo). Serve para conferir dados e prompts sem gastar
token. **`topicos?`** permite rodar só um tópico numa execução avulsa, sem alterar o estado salvo.

*Como foi implementado (2026-09-28):*
- **dry-run** (`processing/dry_run.py`): cada tópico recebe um `ctx` cujo `openai` é um `OpenAISimulado`, que
  só registra o corpo. Os handlers não mudam, e o dry-run vale para todas as estratégias (busca na SUPRA,
  Nominatim e Open-Meteo acontecem de verdade; são gratuitas). O `conteudo` do tópico vira
  `{"dry_run": true, "chamadas_llm": [{modelo, max_tokens, caracteres_texto, tokens_texto_estimados, imagens,
  mensagens}]}`: as mensagens trazem o prompt e os dados completos, e as imagens aparecem só com o tamanho do
  base64. A estimativa de tokens é grosseira (~4 caracteres/token, sem imagens). Falha de fetch continua
  `ok: false`.
- **`topicos`** roda **exatamente** esses tópicos e ignora `config/topics.yaml`, inclusive tópicos desligados
  (é a execução avulsa do admin). Sem `topicos`, vale o YAML (inválido ⇒ 503, como no webhook).
- **Logs por execução:** o webhook e o executar marcam os logs com um `execucao_id` (ContextVar, herdado pelas
  tarefas do `gather`). O buffer (`log_buffer.py`) só existe em `dev` e guarda exceções como `Tipo: mensagem`,
  sem traceback.

### 10.6 Tela de configuração (dev)

Página única, sem build (HTML + CSS + JS puro servido pelo FastAPI, em `app/ui/`), visual sóbrio e
consistente, com selo do ambiente no topo.

```
┌──────────────────────────────────────────────────────────────────────┐
│ Supra IA · Configuração            [ DEV ]     ● 11 de 14 ativos     │
├──────────────────────────────────────────────────────────────────────┤
│ Grupo 1 — Relatório Principal                   [Ativar todos][Limpar]│
│ ┌───────────────────────┐ ┌───────────────────────┐                  │
│ │ Justificativa    [ ●─]│ │ Mapa de Situação [─ ○]│                  │
│ │ campo · gpt-4o-mini   │ │ imagem · gpt-4o  $$$  │                  │
│ │ GET …/justificativa   │ │ GET …/mapa_situacao   │                  │
│ └───────────────────────┘ └───────────────────────┘                  │
│ Grupo 2 — Apresentação Supervisora   …                               │
│ Grupo 3 — Construtora   (não implementado)  cards bloqueados         │
├──────────────────────────────────────────────────────────────────────┤
│ Testar: contrato [_____] período [__]–[__]  ☐ dry-run   [Executar ▶] │
│ ⚠ 2 alterações não salvas                        [Descartar][Salvar]  │
└──────────────────────────────────────────────────────────────────────┘
```

Além dos cartões, a tela de dev terá:

- **Editor de prompts** por tópico: carrega `prompts/<chave>.md`, permite editar e **Salvar** (grava o arquivo).
  Ao clicar em **Executar**, os prompts que estão na tela (salvos ou não) seguem no corpo da requisição —
  o mesmo papel do `prompts[]` que o n8n recebia. Assim dá para testar uma variação sem sobrescrever o arquivo.
- **Botão Executar** (contrato + período) que roda os tópicos ativos e mostra a resposta de cada um.
  Como os tópicos rodam em paralelo e alguns (visão, gpt-4o) demoram, uma evolução possível é devolver
  cada tópico assim que termina (SSE), em vez de esperar o conjunto todo.
- **Painel de logs**: últimas linhas do servidor (nível, tópico, duração, erros), filtráveis pela execução
  atual. Fica só em dev/admin; logs nunca contêm senhas, chaves ou tokens.

Cada cartão mostra estratégia, modelo, endpoint e um selo de custo (gpt-4o visão = alto). Alterações ficam
pendentes até "Salvar" (evita ligar tópico caro sem querer). Tópicos sem implementação (Grupo 3,
Documentação Fotográfica) aparecem bloqueados.

*Como foi implementado (fase 3, 2026-09-28):*
- **Arquivos:** `app/ui/config.html` + `app/ui/static/{app.css,config.js}`; rotas em `app/routers/ui.py`
  (`GET /` → `/ui/config`, `GET /ui/config`, `StaticFiles` em `/ui/static`), **só registradas com `ENV=dev`**
  (fora de dev: 404). A página é só o "casco": sem dados, sem segredos; tudo vem da API, que exige a sessão.
  Cache: `no-cache` (revalida a cada carga).
- **Endereço:** `http://localhost:8000/` (abra por `localhost`/`127.0.0.1`: o navegador aceita o cookie
  `Secure` nesses endereços; por IP de rede sem HTTPS o login não funciona — ver 10.10).
- **Segurança do front:** nada inline (CSP `'self'`); dados da API sempre como texto (`textContent`), nunca
  `innerHTML`; CSRF só em memória; `sessionStorage` guarda apenas contrato/período do formulário. Testes
  estáticos em `tests/test_ui.py` impedem regressões (inline, `innerHTML`/`eval`, `localStorage`, URLs externas,
  rota /api inexistente).
- **Executar = o que está na tela:** o botão envia `topicos` = tópicos **ligados na tela** (salvos ou não) e
  `prompts` = **rascunhos** não salvos do editor; tópicos sem rascunho usam `prompts/<chave>.md`. Cada cartão
  tem "Só este ▶" (execução avulsa, inclusive de tópico desligado).
- **Custo:** dry-run vem **marcado por padrão**. Execução real exige um segundo clique no mesmo botão em até 6 s
  (botão fica vermelho: "Confirmar execução real (N)"); o resumo acima do botão avisa quantos tópicos usam
  gpt-4o (visão).
- **Resultado:** cartão por tópico com selo (Conforme / Atenção / Não Conforme / Erro / Dry-run), `motivo`,
  JSON completo e `infos` recolhíveis (textos > 3 000 caracteres, como base64, são encurtados só na exibição);
  no dry-run, modelo, tokens estimados e as mensagens que seriam enviadas. "Copiar JSON" copia a resposta bruta.
- **Logs:** atualizados a cada 1,5 s durante a execução; depois, filtro "só a última execução" e por nível.
- **Layout (2026-09-29):** barra de execução fixa no topo + abas Tópicos | Resultado | Logs (a aba aberta fica
  no hash da URL; ao executar, a tela vai para Resultado). As abas são só apresentação: não mudam dados nem API.
- **Sessão:** 401 em qualquer chamada volta ao login mantendo rascunhos e alterações pendentes; o navegador
  avisa ao sair da página com alterações não salvas.

### 10.7 Tela de resultado (dev e homolog)

Exibe a resposta consolidada **distribuída em tópicos**, como o n8n devolve: um cartão por tópico com
badge `Conforme` / `Atenção` / `Não Conforme` / `Erro`, `motivo`, campos estruturados e `infos` recolhível;
cabeçalho com contrato, período, duração e tópicos executados; botão para copiar o JSON bruto.
Em homolog não há nenhum controle de configuração.

### 10.8 Fases de implementação (cada uma com testes e atualização deste documento)

1. ✅ **Base** (2026-09-28): `ENV` em `Settings`; `titulo`/`grupo` em `TopicConfig` (a ordem é a de
   `TOPICS`); `config/topics.yaml` + leitor com cache e falha segura (`topic_state.py`); prompts em
   `prompts/<chave>.md` (`prompts_store.py`); regra de execução em `processing/selecao.py`; 503 quando a
   configuração é inválida; Dockerfile copia `config/` e `prompts/`. 92 testes passando.
2a. ✅ **Segurança** (2026-09-28, 161 testes): login de admin (argon2 + sessão + CSRF + limite de
    tentativas), chave de API no webhook, `/docs` desligado, cabeçalhos de segurança, erros 422 sem eco do
    valor, `create_app` (fábrica) com rotas por `ENV`, scripts geradores e `.env.example` completo.
2b. ✅ **API de configuração** (2026-09-28): `GET/PUT /api/topicos`, `GET/PUT /api/prompts`, `POST /api/executar`
    (`dry_run`, `topicos`), `GET /api/logs` (buffer em memória). Todas ficam em `routers/admin.py`, com
    `exigir_admin` no router inteiro. Detalhes em 10.5.
3. ✅ **Tela de configuração** (2026-09-28, dev, somente admin): cartões, editor de prompts, Executar, logs
   — ver "Como foi implementado" em 10.6.
4. **Execuções + tela de resultado** (dev/homolog): só as respostas, para o analista avaliar.

### 10.9 Decisões (2026-09-28)

1. **Prompts:** ficam em `prompts/<chave>.md` (versionados); o payload, quando trouxer, sobrepõe. ✅ fase 1.
2. **Tela de resultado:** mostra **somente as respostas** (sem controles), para o analista do relatório
   avaliar se a saída atende à necessidade. Interpretação adotada: exibe execuções feitas pela própria tela;
   guardar também as chamadas do sistema externo ao webhook fica de fora por ora (confirmar na fase 4).
3. **Tópico desligado com prompt no payload:** ignorado (não roda, não aparece, log). ✅ fase 1.
4. **Grupo 3 (Construtora) e demais tópicos inexistentes:** fora do foco atual; o objetivo é deixar os 14
   tópicos existentes funcionando e testáveis. Na tela, quando houver, aparecem bloqueados.
5. **Autenticação obrigatória** com login e senha e perfil `admin` (10.10). ✅ fase 2a.
6. **Usuários:** em dev só administradores; credenciais (hash) no `.env` (`ADMIN_USERS`). Nenhum sistema
   externo chama o webhook hoje; o "botão" da tela executa o fluxo pela API interna (`POST /api/executar`).
7. **Prompts editáveis na tela de dev**; ao executar, os prompts da tela seguem no corpo, como o `prompts[]` do n8n.
8. **Tela de resultado:** só execuções feitas pela própria tela (pode mudar no futuro). **Painel de logs**
   na tela de dev.

### 10.10 Segurança e autenticação (exigência do Lucas — fase 2a ✅ implementada em 2026-09-28)

**Requisito:** login e senha; usuário `admin` com acesso à configuração; nada que deixe o sistema
vulnerável no front; mesmo em rede protegida, ninguém pode alterar a automação sem autenticar.

**Ponto de honestidade sobre "esconder as chamadas do front":** qualquer requisição feita pelo navegador
aparece no DevTools (aba Network) — isso é inerente à web e não dá para esconder. A segurança **não pode
depender de esconder**; ela vem de o servidor recusar tudo que não esteja autenticado e autorizado, e de
o front não conter nenhum segredo. O que fazemos para reduzir a superfície:

| Medida | Como |
|---|---|
| Nenhum segredo no front ✅ | Chaves/tokens só no servidor (`.env`); o front nunca recebe `OPENAI_API_KEY`, `DNIT_TOKEN`, hash de senha, caminhos internos nem stack traces |
| Autorização no servidor em TODA rota de configuração ✅ | `Depends(exigir_admin)`: sessão válida com perfil `admin`; sem ela: 401. Já cobra CSRF nas escritas, então uma rota nova não "esquece" o CSRF |
| Rotas de configuração inexistentes fora de dev ✅ | Só registradas com `ENV=dev` (em homolog/prod: 404, não 403) |
| Hash de senha forte ✅ | `argon2-cffi` (Argon2id). Senha nunca em texto puro, nunca em log; `.env` só guarda o hash; verificação fora do event loop; usuário inexistente gasta o mesmo tempo (não revela quem existe) |
| Sessão revogável ✅ | Token opaco aleatório (`secrets.token_urlsafe`) guardado no servidor (só o hash SHA-256); logout invalida de verdade; expiração por inatividade e absoluta |
| Cookie de sessão blindado ✅ | `HttpOnly` (JS não lê), `Secure`, `SameSite=Strict`, prefixo `__Host-` |
| CSRF ✅ | `SameSite=Strict` + token por sessão no header `X-CSRF-Token` em toda escrita (`PUT`/`POST`) |
| Força bruta ✅ | Limite de tentativas por IP e por par IP+usuário, com espera crescente (5 falhas → 5 s, dobrando até 15 min); mensagem de erro genérica e tempo de resposta constante (não revela se o usuário existe) |
| Cabeçalhos de segurança ✅ | CSP restritiva (sem scripts inline, só `self`), `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff`, `Cache-Control: no-store` nas respostas da API |
| Superfície da API ✅ | `/docs`, `/redoc` e `/openapi.json` desligados (só ligáveis com `ENV=dev` + `ENABLE_DOCS=true`); erros ao cliente sempre genéricos; 422 sem devolver o valor enviado (não ecoa a senha) |
| Front sem vetor de XSS ✅ | Respostas da LLM/SUPRA e logs sempre como **texto** (`textContent`), nunca como HTML; nada inline; verificado por `tests/test_ui.py` |
| Auditoria ✅ | Login/logout/falhas são logados (usuário e IP, nunca a senha; nome truncado e escapado contra log injection). Alterações de tópicos (ligados/desligados), prompts salvos (chave e tamanho) e execuções pela tela também, com o usuário |
| Transporte | TLS obrigatório fora de `localhost` (reverse proxy); sem HTTPS o cookie `Secure` não funciona, de propósito |
| Credencial do admin ✅ | `ADMIN_USERS` no `.env` (só o **hash**, vários admins possíveis); `python -m scripts.gerar_hash_senha` gera; nada de senha padrão; sem admin configurado ninguém loga |

**Webhook (resolvido):** `POST /webhook/relatorio` agora exige o header `X-API-Key` (comparação em
tempo constante com `hmac.compare_digest`). Sem chave: 401. `WEBHOOK_API_KEY` ausente: 503 (falha fechada —
nunca aberto por esquecimento). Chaves erradas repetidas: 429 com espera crescente por IP. A chave precisa
ter ≥32 caracteres (`python -m scripts.gerar_chave`). Quando algum sistema passar a chamar o webhook, ele
envia esse header.

**Como configurar (.env):**

| Variável | Para quê | Como obter |
|---|---|---|
| `ENV` | `dev` / `homolog` / `prod` (padrão `prod`) | manual |
| `WEBHOOK_API_KEY` | chave do sistema chamador do webhook | `python -m scripts.gerar_chave` |
| `ADMIN_USERS` | `{"usuario": "hash argon2"}` entre aspas simples | `python -m scripts.gerar_hash_senha lucas.meira` (senha digitada oculta) |
| `COOKIE_SECURE` | cookie só em HTTPS (padrão `true`) | manter `true` |
| `SESSION_IDLE_MINUTES` / `SESSION_MAX_HOURS` | expiração da sessão (30 min / 8 h) | opcional |
| `ENABLE_DOCS` | liga `/docs` (só vale em `ENV=dev`; padrão `false`) | opcional |
| `OPENAI_API_KEY`, `DNIT_TOKEN`, `LEGENDAS` | integrações (ver dicas no `.env.example`) | nó "Define Variáveis Globais" do n8n |

**Limitações assumidas (e por quê):**
- *Sessões em memória:* reiniciar o servidor desloga todos; rode **um** processo (o Dockerfile já roda).
- *HTTPS:* com `COOKIE_SECURE=true`, o login só funciona em `https://` ou `http://localhost`. Numa URL
  `http://10.x.x.x:8000` (sem TLS) o navegador descarta o cookie. Solução correta: proxy reverso com TLS;
  `COOKIE_SECURE=false` é uma saída insegura, aceitável só em teste local (o servidor avisa no log).
- *IP do cliente:* atrás de proxy reverso o IP visto é o do proxy; para o limite de tentativas enxergar o IP
  real, subir o uvicorn com `--proxy-headers --forwarded-allow-ips=<ip do proxy>`.
- *Bloqueio por tentativas* é por IP e por par IP+usuário: um atacante em outro IP não consegue trancar o admin.
- *HSTS* é responsabilidade do proxy que termina o TLS.
- *Sem CORS:* nenhum outro site consegue ler respostas da API pelo navegador.

**Usuários de homolog:** ainda sem definição (o que se decidiu vale para `dev`: só admins, no `.env`). Quando a
tela de resultado de homolog for construída (fase 4), decidir se terá login próprio (perfil `analista`).
