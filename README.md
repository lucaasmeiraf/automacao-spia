# Supra IA — n8n → Python

Migração do fluxo de automação **Supra AI** (originalmente em n8n) para Python com
FastAPI. Analisa relatórios de supervisão de obras do DNIT (IN_51/2021) buscando
dados da API SUPRA, processando cada seção com LLM (OpenAI) e devolvendo um JSON
consolidado de conformidade.

## Mapeamento n8n → Python

| n8n | Aqui |
|---|---|
| Webhook | `POST /webhook/relatorio` (`app/main.py`) |
| If (valida campos obrigatórios) | Validação Pydantic em `app/models.py` |
| Separa Prompts | `RelatorioRequest.prompts_ativos()` |
| Define Variáveis Globais | `app/config.py` (via `.env`, sem segredos no código) |
| Chains paralelas | `asyncio.gather` em `app/main.py` |
| HTTP Request (secao_ws/…) | `app/clients/dnit.py` |
| Payload … (stripHtml + body) | `app/processing/html_clean.py` + `pipeline.py` |
| LLM (api.openai.com) | `app/clients/openai_client.py` |
| Limpa Retorno … | `pipeline.py` + handlers especializados |
| Respond to Webhook | `RelatorioResponse` (Pydantic) |

## Estrutura

```
app/
├── main.py                   # FastAPI: webhook + paralelismo (asyncio.gather)
├── config.py                 # Settings via .env (pydantic-settings)
├── models.py                 # Validação de entrada e saída (Pydantic v2)
├── topics.py                 # Registro declarativo dos 14 tópicos
├── logging_config.py
├── clients/
│   ├── dnit.py               # API SUPRA (GET secao_ws + download imagem)
│   ├── openai_client.py      # OpenAI Chat Completions (via httpx)
│   ├── openmeteo.py          # Open-Meteo (histórico meteorológico)
│   └── nominatim.py          # Nominatim / OSM (geocodificação)
└── processing/
    ├── context.py            # ProcessingContext (agrupa clientes)
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

## Rodando localmente

```bash
cp .env.example .env     # edite com suas chaves
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Com Docker:

```bash
cp .env.example .env
docker compose up --build
```

API disponível em `http://localhost:8000`.
Documentação interativa em `http://localhost:8000/docs`.

## Testando o webhook

```bash
curl -X POST http://localhost:8000/webhook/relatorio \
  -H "Content-Type: application/json" \
  -d '{
    "contrato": "00 00493/2013",
    "periodo_inicio": "2025-10-01",
    "periodo_fim": "2025-10-31",
    "prompts": [
      { "topico": "justificativa", "conteudo": "Você é um auditor técnico. Analise e retorne JSON." }
    ]
  }'
```

## Testes

```bash
pytest tests/ -v
```

## Segurança

- Segredos **somente** no `.env` (que está no `.gitignore`).
- O arquivo `Supra AI - n8n.json` continha credenciais expostas — **gere tokens novos** antes de usar em qualquer ambiente.
- Ver `.env.example` para os campos obrigatórios.
