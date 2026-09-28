# CLAUDE.md — Supra AI

Guia de trabalho para Claude Code neste projeto. Leia antes de qualquer implementação.

> Último alinhamento com o código: 2026-09-28. Se código e este arquivo divergirem, o código é a
> verdade — corrija este arquivo na mesma tarefa.

---

## Contexto do Projeto

Sistema de auditoria automatizada de Relatórios de Supervisão do DNIT (IN_51/2021).
Migração de fluxo n8n → Python com FastAPI. Consulte `docs/architecture.md` para a documentação completa.

**Stack**: Python 3.11+, FastAPI, asyncio, **httpx** (`AsyncClient` único e compartilhado), Pydantic v2,
pydantic-settings, OpenAI Chat Completions (via httpx, sem SDK), pytest.

---

## Estrutura e Convenções

### Pastas (estrutura REAL)

```
app/
├── main.py              # create_app(settings) (fábrica): webhook, /health, rotas por ENV
├── security/            # passwords (argon2), sessions, throttle, deps (exigir_admin/webhook), headers
├── routers/             # auth.py (login/me/logout) e admin.py (/api/topicos|prompts|executar|logs), só ENV=dev
├── config.py            # Settings (pydantic-settings) — lê .env
├── models.py            # Pydantic: RelatorioRequest / TopicoResultado / RelatorioResponse
├── topics.py            # DEFINIÇÃO dos tópicos: TOPICS = {chave: TopicConfig(...)}
├── topic_state.py       # ATIVAÇÃO: lê/grava config/topics.yaml (cache por mtime, falha segura)
├── prompts_store.py     # prompts/<chave>.md lê/grava (só chaves conhecidas; anti path traversal)
├── arquivos.py          # escrever_atomico (temporário + os.replace)
├── log_buffer.py        # BufferDeLogs (painel de logs, só dev) + em_execucao() (id de execução nos logs)
├── logging_config.py
├── clients/             # HTTP puro para APIs externas (dnit, openai_client, openmeteo, nominatim)
└── processing/
    ├── execucao.py      # executar_relatorio(): seleção + asyncio.gather (webhook E /api/executar)
    ├── dry_run.py       # OpenAISimulado: dry-run sem chamar a OpenAI
    ├── pipeline.py      # processar_topico(): fluxo genérico + roteamento por estratégia
    ├── context.py       # ProcessingContext (agrupa os clients; criado por requisição)
    ├── selecao.py       # quais tópicos rodam (ativo no YAML + prompt disponível)
    ├── records.py       # limpar_registro, detectar_vazio
    ├── html_clean.py    # strip_html
    ├── image.py         # handler estratégia "imagem"
    ├── contratuais.py   # handler estratégia "contratuais"
    └── pluviometrico.py # handler estratégia "pluviometrico"
scripts/                 # python -m scripts.gerar_hash_senha | gerar_chave (uso manual, não é do app)
pytest.ini               # pythonpath=. — `pytest` puro funciona
config/topics.yaml       # ATIVAÇÃO dos tópicos (true/false) — versionado
prompts/<chave>.md       # prompt de sistema por tópico (o payload sobrepõe)
tests/                   # pytest, arquivos planos: test_<assunto>.py
docs/architecture.md     # documentação de arquitetura e decisões
docs/andamento.md        # STATUS: entregas, frente atual, bloqueios, próximos passos
```

Não existem `src/`, `BaseProcessor` nem `tests/processors/` — não os crie.

### Código

- Todo código de I/O (HTTP, arquivo) deve ser **async**.
- **Um tópico = uma entrada em `TOPICS`** (`app/topics.py`). Tópicos simples (`campo`, `json`) não têm
  código próprio: são executados pelo fluxo genérico de `pipeline.py`.
- Tópicos com lógica própria têm um **handler** em `app/processing/<nome>.py` com a assinatura
  `async def processar_<nome>(cfg, prompt_sistema, contrato, periodo_inicio, periodo_fim, ctx) -> TopicoResultado`,
  roteado por `cfg.estrategia` em `processar_topico()`.
- `processar_topico()` é o único ponto de entrada de um tópico, chamado por `processing/execucao.py`
  (`executar_relatorio`: seleção + `asyncio.gather`), que o webhook e o `POST /api/executar` compartilham.
- Não adicione lógica de negócio em `main.py` nem nos routers — eles validam, autenticam e delegam a
  `executar_relatorio`. A app sobe com `uvicorn app.main:create_app --factory`
  (não existe `app.main:app` no import: as configurações precisam existir para montar rotas/`/docs`).
- **Toda rota nova de administração** vai em `app/routers/admin.py`, que já tem `exigir_admin` no router
  inteiro (sessão de admin + CSRF nas escritas) e só é registrado sob `settings.env == "dev"`. Rota nova
  de automação externa usa `Depends(exigir_chave_webhook)`. Nunca crie rota de configuração sem autenticação.
- Arquivos gravados pela API (`topics.yaml`, prompts) usam `escrever_atomico` (`app/arquivos.py`).
- Clients (`app/clients/`) não têm lógica de negócio — apenas fazem chamadas e retornam dados brutos.
- Estratégias existentes: `campo`, `json`, `imagem`, `contratuais`, `pluviometrico`
  (detalhes em `docs/architecture.md` §3.4).

### Como adicionar um tópico

1. Confirme que o endpoint SUPRA existe e está em `docs/architecture.md` §4 (senão, adicione).
2. Adicione a entrada em `TOPICS` (`app/topics.py`). Se precisar de lógica nova, crie um handler e uma
   nova `estrategia` roteada em `pipeline.py`.
3. Escreva testes em `tests/` (ver "Testes Obrigatórios").
4. Rode o teste de integração em dev antes de marcar como pronto.
5. Atualize `docs/architecture.md` (§7) e o README.

### Variáveis de Ambiente

- Credenciais **nunca** vão no código — sempre no `.env` (que está no `.gitignore`).
- `.env.example` é o template versionado; mantenha-o em dia quando criar uma variável nova.
- `app/config.py` carrega um único `.env`. `ENV` (`dev`/`homolog`/`prod`) existe e o padrão é `prod`
  (falha fechada). Variáveis de segurança: `WEBHOOK_API_KEY`, `ADMIN_USERS` (só hashes argon2, JSON entre
  aspas simples), `COOKIE_SECURE`, `ENABLE_DOCS`, `SESSION_*` — ver `.env.example` e `docs/architecture.md` §10.10.
- **Segredos:** nunca imprima, logue nem devolva em resposta valores de chave/token/senha/hash. Erros de
  configuração não repetem o valor recebido (`hide_input_in_errors`). Logue nomes de usuário sempre com `%r`
  e truncados (anti log-injection).

### Typo intencional

O parâmetro da query da API SUPRA é `periodo_incio` (sem "í"). **Não corrija**. É o parâmetro real da API.
Está em `app/clients/dnit.py`.

---

## Toggle de Tópicos

Separe **definição** de **ativação**. Um tópico só executa quando:
1. Existe em `TOPICS` (`app/topics.py`) — *como* ele funciona;
2. Está `true` em `config/topics.yaml` — *se* roda (equivale ao "fio" do n8n). Ausente = desligado;
3. Há prompt: o do payload (`prompts[]`) prevalece; senão `prompts/<chave>.md`.

Só o dev decide o que a LLM analisa: tópico desligado é ignorado mesmo com prompt no payload (não roda,
não aparece na resposta). Tópico ativo sem prompt volta como `ok: false`. YAML ausente/inválido ⇒
**nenhum** tópico roda e a API responde 503 (falha segura — nunca "ligar tudo").

Ao criar um tópico novo: adicione em `TOPICS` **e** em `config/topics.yaml` (com `false` até estar
testado; há um teste que exige que o YAML liste todos os tópicos).

**Em andamento** (`docs/architecture.md` §10): fases 1 (base), 2a (segurança: login admin, chave do
webhook, `/docs` desligado, cabeçalhos) e 2b (API de configuração: `/api/topicos`, `/api/prompts`,
`POST /api/executar` com `dry_run`/`topicos`, `/api/logs`) concluídas. Faltam 3 (tela de configuração,
só `dev`) e 4 (tela de resultado, `dev`/`homolog`). Requisitos de segurança em §10.10: siga-os; não exponha segredos no front e nunca
confie em esconder rota como proteção — a autorização é sempre no servidor.

Documentação Fotográfica (`documentacao_fotografica`) e o Grupo 3 (Construtora) **não** têm processor:
ver "Observações Importantes".

---

## Antes de Implementar Qualquer Coisa

1. **Leia** `docs/architecture.md` inteiro.
2. **Verifique** se o tópico já existe em `app/topics.py` e se há handler em `app/processing/`.
3. Para tópico novo, confirme que a entrada está em `TOPICS` e que o roteamento por `estrategia` existe.
4. Se for um novo client HTTP, **confirme** que não existe lógica de negócio no client.
5. **Documente antes de codar** funcionalidades novas: atualize/crie a seção em `docs/architecture.md`
   e alinhe com o usuário antes da implementação.

---

## Testes Obrigatórios

Execute estes testes após qualquer mudança antes de considerar a tarefa concluída:

### 1. Validação de Estrutura
```bash
python -m py_compile app/processing/<arquivo>.py
python -m py_compile app/clients/<arquivo>.py
```

### 2. Testes Unitários
```bash
pytest tests/ -v
```
Estado atual: 235 testes (pipeline, pluviométrico, html_clean, ativação, prompts, seleção, webhook,
segurança, auth, settings, API de configuração, dry-run, buffer de logs). Testes de app usam `tests/helpers.py` (`fazer_settings`/`fazer_app`: Settings
hermético e `create_app` sem lifespan). Toda mudança de segurança precisa de teste do caso NEGATIVO
(sem chave, sem sessão, sem CSRF, senha errada, fora de `dev`). Todo handler novo deve ter testes com
**clients mockados** (`AsyncMock`/`MagicMock`; nunca chamar API real) cobrindo:
- montagem do conteúdo enviado à LLM (`prepare`, no nosso caso `_montar_user_content` ou equivalente);
- tratamento de resposta LLM válida (JSON) e inválida (texto puro);
- falha de fetch/LLM → `TopicoResultado(ok=False, erro=...)`, sem levantar exceção.

### 3. Teste de Integração (apenas em dev, com `.env` válido)
Antes de marcar um tópico como pronto, faça uma chamada real ao `POST /webhook/relatorio` (com o header
`X-API-Key`) com um contrato de teste válido e verifique:
- `ok` é `true` e `conteudo.conforme` é `"Conforme"`, `"Atenção"` ou `"Não Conforme"`;
- `conteudo.motivo` é uma string não vazia;
- `conteudo.infos` contém os dados brutos enviados à LLM;
- nenhuma exception não tratada nos logs.

> Nota: nenhum código valida o valor de `conforme` — a checagem é manual/de teste.

### 4. Teste de Paralelismo
Ao modificar `main.py`, `processing/execucao.py` ou `pipeline.py`, execute com pelo menos 3 tópicos simultâneos e verifique:
- todos os resultados estão presentes em `topicos`;
- erro em um tópico não interrompe os demais. Hoje isso é garantido porque **cada handler captura suas
  próprias exceções** e devolve `ok=False`; um handler novo que deixar escapar exceção derruba a
  requisição inteira (`asyncio.gather` em `processing/execucao.py` está sem `return_exceptions=True`).

### 5. Verificação de Ambiente
```bash
python -c "from app.config import get_settings; s = get_settings(); print(bool(s.openai_api_key), bool(s.dnit_token))"
```
Não imprima tokens/chaves.

---

## Quando Atualizar `docs/architecture.md`

Atualize a documentação sempre que:

- Um novo tópico for implementado e testado → marque na seção 7
- Um novo endpoint SUPRA for descoberto ou corrigido → atualize a seção 4
- Uma issue do backlog for implementada → mova da seção 8 para a seção correspondente
- O formato de entrada/saída mudar → atualize a seção 5
- Uma decisão de arquitetura mudar → adicione à seção correspondente com data
- A estrutura de pastas mudar → atualize este arquivo, o README e a seção 3.2

**Nunca** espere acumular muitas mudanças — atualize ao final de cada tarefa concluída.

Atualize também **`docs/andamento.md`** ao final de cada tarefa (pedido do Lucas): entrada nova no topo do
histórico de entregas, quadro "Situação em uma olhada", bloqueios e próximos passos. Resultados de testes de
integração (o que passou, o que falhou e por quê) vão lá.

---

## Padrões de Código

### Tópico simples (sem código próprio)

```python
"justificativa": TopicConfig(
    chave="justificativa",
    endpoint="justificativa",
    model="gpt-4o-mini",
    max_tokens=1200,
    html_fields=("resumo", "descricao"),
    estrategia="campo",
    campo_conteudo="resumo",
),
```

O fluxo genérico (`pipeline.processar_topico`) faz: fetch → `_montar_user_content` → `ctx.openai.chat(body)`
→ `_interpretar_retorno` → anexa `infos` (dado enviado à LLM) → `TopicoResultado`.

### Tratamento de erro

Nunca deixe um handler explodir. Capture e devolva resultado estruturado:

```python
except Exception as exc:
    logger.exception("Falha ao processar tópico '%s'", cfg.chave)
    return TopicoResultado(topico=cfg.chave, ok=False, erro=str(exc))
```

Onde a IA/dados falham de forma esperada (ex.: imagem ausente), os handlers de imagem devolvem
`ok=True` com um `conforme: "Atenção"` de fallback estruturado — mantenha esse padrão nos handlers com
esquema fixo.

### Limpeza de HTML

Use sempre `strip_html()` (`app/processing/html_clean.py`) ou `limpar_registro(..., html_fields=...)`
(`app/processing/records.py`) para qualquer campo que possa conter HTML. Nunca replique a lógica inline.

### Parse de resposta LLM

`OpenAIClient.chat()` devolve o texto de `choices[0].message.content`. O fluxo genérico interpreta com
`_interpretar_retorno` (`pipeline.py`): `json.loads`, e se falhar devolve o texto puro. Não há remoção de
blocos ```` ```json ```` nem `response_format` (o n8n original também não tinha) — ver backlog.

---

## Issues Ativas e Próximas Etapas

Ver `docs/architecture.md` seção 8 (Issues Futuras) e seção 10 (proposta de telas/configuração).

Antes de implementar qualquer issue do backlog, **confirme com o usuário** que ela faz parte do escopo atual.

---

## Observações Importantes

- Projeto em múltiplos ambientes (dev → homolog → prod). Nunca hardcode credenciais.
- Ambientes: `dev` = automação + telas de configuração e de resultado; `homolog` = automação + só a tela
  de resultado (só as respostas, para o analista avaliar); `prod` = só automação (sem tela). As telas ainda
  não existem — ver `docs/architecture.md` §10.
- Segurança (§10.10): `POST /webhook/relatorio` exige `X-API-Key`; `/docs` está desligado; login admin
  (`ADMIN_USERS`). Sessões ficam em memória: rode **um** processo.
- O Grupo 3 (Construtora) está no n8n mas **não deve ser migrado ainda** — issue futura.
- Os 4 nós desabilitados do n8n (Agente Construtora, Acomp. Físico, Análise Crítica, Pluviométrico agente)
  e o nó HTTP para Ollama **não são migrados**.
- Documentação Fotográfica: no n8n funciona, mas fica desligada para não gastar créditos. No Python o
  processor **ainda não existe** (bloco comentado em `topics.py`); quando existir, deve nascer desativado.
- Modelos: `gpt-4o-mini` para texto, `gpt-4o` para visão (imagens; custo bem maior).
- `Supra AI - n8n.json` está no `.gitignore` (tem credenciais); os tokens que ele continha devem ser
  considerados comprometidos.
