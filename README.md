# Supra IA — n8n → Python

Migração do fluxo de automação **Supra AI** (originalmente em n8n) para Python com
FastAPI. Analisa relatórios de supervisão de obras do DNIT (IN_51/2021) buscando
dados da API SUPRA, processando cada seção com LLM (OpenAI) e devolvendo um JSON
consolidado de conformidade.

> **Status do projeto, bloqueios e próximos passos:** [`docs/andamento.md`](docs/andamento.md).

## Mapeamento n8n → Python

| n8n | Aqui |
|---|---|
| Webhook | `POST /webhook/relatorio` (`app/main.py`) |
| If (valida campos obrigatórios) | Validação Pydantic em `app/models.py` |
| Separa Prompts | `RelatorioRequest.prompts_ativos()` |
| Define Variáveis Globais | `app/config.py` (via `.env`, sem segredos no código) |
| Chains paralelas | `asyncio.gather` em `app/processing/execucao.py` |
| HTTP Request (secao_ws/…) | `app/clients/dnit.py` |
| Payload … (stripHtml + body) | `app/processing/html_clean.py` + `pipeline.py` |
| LLM (api.openai.com) | `app/clients/openai_client.py` |
| Limpa Retorno … | `pipeline.py` + handlers especializados |
| Respond to Webhook | `RelatorioResponse` (Pydantic) |

## Estrutura

```
app/
├── main.py                   # create_app: webhook, /health, rotas por ENV
├── config.py                 # Settings via .env (pydantic-settings)
├── models.py                 # Validação de entrada e saída (Pydantic v2)
├── topics.py                 # DEFINIÇÃO dos 14 tópicos (como funcionam)
├── topic_state.py            # ATIVAÇÃO: config/topics.yaml (o "fio" do n8n): lê e grava
├── prompts_store.py          # prompts/<chave>.md: lê e grava
├── arquivos.py               # gravação atômica (temporário + os.replace)
├── log_buffer.py             # últimas linhas de log em memória (painel de logs, só dev)
├── logging_config.py
├── security/                 # senhas argon2, sessões, CSRF, limite de tentativas, cabeçalhos
├── routers/
│   ├── auth.py               # /api/auth/login | me | logout (só ENV=dev)
│   ├── admin.py              # /api/topicos | prompts | executar | logs (só ENV=dev, admin)
│   └── ui.py                 # tela de configuração: / → /ui/config (só ENV=dev)
├── ui/                       # config.html + static/ (CSS e JS puros, sem build)
├── clients/
│   ├── dnit.py               # API SUPRA (GET secao_ws + download imagem)
│   ├── openai_client.py      # OpenAI Chat Completions (via httpx)
│   ├── openmeteo.py          # Open-Meteo (histórico meteorológico)
│   └── nominatim.py          # Nominatim / OSM (geocodificação)
└── processing/
    ├── context.py            # ProcessingContext (agrupa clientes)
    ├── execucao.py           # seleção + execução paralela (webhook e /api/executar)
    ├── dry_run.py            # modo dry-run: monta tudo e não chama a OpenAI
    ├── selecao.py            # Quais tópicos rodam (ativo no YAML + prompt)
    ├── pipeline.py           # Pipeline genérico + roteamento
    ├── records.py            # limpar_registro, detectar_vazio
    ├── html_clean.py         # strip_html (porta do n8n)
    ├── image.py              # Análise de imagem com gpt-4o (visão)
    ├── contratuais.py        # Info contratuais (datas, moeda)
    └── pluviometrico.py      # Pluviométrico (SUPRA + Nominatim + Open-Meteo + LLM)
```

## Tópicos implementados (Etapa 1)

| Tópico | Estratégia | Modelo |
|---|---|---|
| `justificativa` | campo | gpt-4o-mini |
| `resumo_projeto` | campo | gpt-4o-mini |
| `historico` | campo | gpt-4o-mini |
| `introducao` | campo | gpt-4o-mini |
| `oaes` | json + filtro de campos | gpt-4o-mini |
| `rpfo` | json + filtro de campos | gpt-4o-mini |
| `mapa_situacao` | imagem (visão) | gpt-4o |
| `diagrama_ocorrencias` | imagem (visão) | gpt-4o |
| `info_contratuais_supervisora` | contratuais (datas/moeda) | gpt-4o-mini |
| `termos_aditivos_supervisora` | json + detecção de vazio | gpt-4o-mini |
| `responsaveis_tecnicos_supervisora` | json + detecção de vazio | gpt-4o-mini |
| `paralisacao_reinicio` | json + detecção de vazio | gpt-4o-mini |
| `apostilas_supervisora` | json + detecção de vazio | gpt-4o-mini |
| `controle_pluviometrico` | multi-fonte | gpt-4o-mini |

## Quais tópicos rodam

Um tópico roda se estiver **`true` em `config/topics.yaml`** (equivale ao fio ligado no n8n) e tiver
prompt: o enviado em `prompts[]` ou, se não vier, `prompts/<chave>.md`. Tópico desligado é ignorado
mesmo que o payload traga o prompt. Se o YAML estiver inválido, a API responde 503 e nada roda.
Detalhes e o plano das telas de configuração/resultado: `docs/architecture.md` §3.3 e §10.

## Rodando localmente

```bash
cp .env.example .env                       # edite com suas chaves (ver "Configurando o .env")
pip install -r requirements.txt
uvicorn app.main:create_app --factory --reload
```

Com Docker:

```bash
cp .env.example .env
docker compose up --build
```

API disponível em `http://localhost:8000` (`GET /health`). A documentação interativa (`/docs`) fica
**desligada**; só liga com `ENV=dev` e `ENABLE_DOCS=true`.

## Configurando o .env

Copie `.env.example` para `.env` e preencha (cada ambiente tem o seu):

1. `OPENAI_API_KEY`, `DNIT_TOKEN`, `LEGENDAS` — no n8n, nó **Define Variáveis Globais** (campos
   `token-openai`, `token`, `legendas`). Prefira gerar chaves novas: as antigas ficaram expostas.
2. `WEBHOOK_API_KEY` — `python -m scripts.gerar_chave` (o sistema que chamar o webhook envia no header `X-API-Key`).
3. `ADMIN_USERS` (login da administração, só `ENV=dev`) — `python -m scripts.gerar_hash_senha seu.usuario`
   e cole a linha impressa. Guarda só o hash da senha.
4. `ENV=dev` (ou `homolog` / `prod`; se omitido vale `prod`).

Sem `WEBHOOK_API_KEY` o webhook responde 503; sem `ADMIN_USERS` ninguém consegue logar.
Com `COOKIE_SECURE=true` (padrão) o login exige `https://` ou `http://localhost`.

## Testando o webhook

```bash
curl -X POST http://localhost:8000/webhook/relatorio \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <sua WEBHOOK_API_KEY>" \
  -d '{
    "contrato": "00 00493/2013",
    "periodo_inicio": "2025-10-01",
    "periodo_fim": "2025-10-31",
    "prompts": [
      { "topico": "justificativa", "conteudo": "Você é um auditor técnico. Analise e retorne JSON." }
    ]
  }'
```

## Tela de configuração (só `ENV=dev`)

Com o servidor rodando, abra **`http://localhost:8000/`** e entre com um usuário de `ADMIN_USERS`. Na tela:
ligar/desligar tópicos (e salvar), editar prompts, **Executar** (dry-run marcado por padrão; a execução real
pede confirmação; "Só este ▶" roda um tópico) e acompanhar os logs. Use `localhost` (não o IP da máquina):
com `COOKIE_SECURE=true` o login só funciona em `localhost` ou HTTPS.

## API de configuração (só `ENV=dev`, login de admin)

Base da futura tela de configuração (`docs/architecture.md` §10.5). Todas as rotas exigem a sessão do
login (`POST /api/auth/login`); as escritas exigem também o header `X-CSRF-Token` devolvido no login.

| Rota | Função |
|---|---|
| `GET /api/topicos` / `PUT /api/topicos` | lista / liga e desliga tópicos (`{"topicos": {"rpfo": true}}`), grava `config/topics.yaml` |
| `GET /api/prompts`, `GET/PUT /api/prompts/{chave}` | lê / salva `prompts/<chave>.md` (`{"conteudo": "..."}`) |
| `POST /api/executar` | roda como o webhook; extras: `"topicos": ["rpfo"]` (só esses, ignora o YAML) e `"dry_run": true` (busca os dados e monta o payload, **sem chamar a OpenAI**) |
| `GET /api/logs?nivel=INFO&execucao=<id>` | últimas linhas de log; `execucao_id` vem na resposta do executar |

## Testes

```bash
pytest -v
```

## Segurança

- Segredos **somente** no `.env` (que está no `.gitignore`). Senhas de admin: só o hash Argon2id.
- O webhook exige `X-API-Key`; a administração exige login (sessão em cookie `HttpOnly`/`Secure`/`SameSite=Strict`,
  CSRF, limite de tentativas) e só existe com `ENV=dev`.
- O arquivo `Supra AI - n8n.json` (no `.gitignore`) continha credenciais expostas — **gere tokens novos**.
- Em produção/homologação use HTTPS (proxy reverso) e rode **um** processo (sessões em memória).
- Detalhes, limitações e o plano das telas: `docs/architecture.md` §10.
