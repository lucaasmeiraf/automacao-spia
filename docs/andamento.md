# Andamento do projeto — Supra IA

Registro vivo do que foi entregue, onde estamos atacando, o que está bloqueado e o que vem a seguir.
**Atualize ao fim de cada tarefa** (entrada nova no topo do histórico + quadros abaixo).
Decisões técnicas e detalhes ficam em [`architecture.md`](architecture.md); aqui fica o *status*.

> Última atualização: **2026-09-28**

---

## Situação em uma olhada

| Frente | Estado |
|---|---|
| Migração dos 14 tópicos (Etapa 1) | ✅ Código pronto e testado com mocks |
| Configuração de tópicos (ativação + prompts em arquivo) — fase 1 | ✅ |
| Segurança (login admin, chave do webhook, `/docs` off) — fase 2a | ✅ |
| API de configuração (`/api/topicos`, `/api/prompts`, `/api/executar`, `/api/logs`) — fase 2b | ✅ |
| **Teste de integração real (SUPRA + OpenAI)** | ⛔ **Bloqueado** — ver "Bloqueios" |
| Prompts de cada tópico (`prompts/<chave>.md`) | ⚠️ Não existem ainda — ver "Bloqueios" |
| Tela de configuração (dev) — fase 3 | ⏳ Próxima |
| Tela de resultado (dev/homolog) — fase 4 | ⏳ |
| Grupo 3 (Construtora), Documentação Fotográfica | 💤 Fora do escopo atual |

Testes automatizados: **235 passando** (`pytest`).

---

## Bloqueios (precisam de ação fora do código)

| # | Bloqueio | Evidência | Quem resolve / o que fazer |
|---|---|---|---|
| B1 | **Firewall do DNIT bloqueia a OpenAI.** `api.openai.com` cai na categoria `DNIT_DENY` do FortiGuard e recebe uma página HTML 403. A chamada **nem chega à OpenAI** (nada é cobrado e a chave nem é validada). | Teste de 2026-09-28: `GET /v1/models` e `POST /v1/chat/completions` → 403 "Web Filter Violation … Category DNIT_DENY". | Equipe de rede/segurança do DNIT: pedir **liberação de `api.openai.com`** (443) para a máquina/servidor do Supra IA. Alternativa: rodar em um servidor fora dessa política (onde o n8n rodava?). |
| B2 | **SUPRA recusa o token.** Toda seção responde `{"status": false, "mensagem": "Usuário não cadastrado ou dados inválidos."}`. | Teste de 2026-09-28 com o contrato `00 00493/2013` (out/2025). O token do `.env` é idêntico ao do export do n8n. | Obter **um token SUPRA novo** (o antigo estava no export do n8n, considerado comprometido — provavelmente foi revogado ou a senha mudou) e confirmar um **contrato + período de teste** com dados. |
| B3 | **Não há prompts.** No n8n eles chegavam no payload do sistema chamador (`prompts[]`); não estão no export. Sem prompt, o tópico ativo volta `ok: false`. | `prompts/` só tem o README. | Recuperar os prompts usados em produção no n8n (ou redigi-los com o analista) e salvá-los em `prompts/<chave>.md` — pela API `PUT /api/prompts/{chave}` ou pela tela da fase 3. |

---

## Onde estamos atacando agora

1. **Destravar o teste real** (B1–B3). Enquanto isso, o `dry_run` já permite validar busca e montagem sem
   OpenAI assim que a SUPRA voltar a responder.
2. **Fase 3 — tela de configuração** (só `dev`, admin): cartões de tópicos, editor de prompts, Executar
   (com dry-run), painel de logs. Não depende dos bloqueios — consome a API da fase 2b.

---

## Pontos de atenção descobertos (não bloqueiam)

- **Inspeção de TLS na rede do DNIT:** sites externos chegam reassinados pela CA interna
  `DNIT_SubCA_SSL`. O app passou a validar TLS pelo repositório de certificados do sistema (em vez do
  `certifi`). Consequência de segurança: quando a OpenAI for liberada, o **proxy do DNIT enxerga o tráfego
  descriptografado**, inclusive o header com a chave da OpenAI e o conteúdo dos relatórios. Vale alinhar com
  a segurança do DNIT (política de retenção de logs do proxy) e, se possível, pedir exceção de inspeção
  para `api.openai.com`. Em Docker/Linux dentro da rede do DNIT, a CA interna precisa ser instalada no
  contêiner.
- **Token SUPRA carrega usuário e senha** (JWT com campos `user` e `pass`, sem expiração). Quem tiver o
  token tem, na prática, a credencial. Reforça: gerar um novo e nunca colocar em arquivo versionado.
- **Erro de autenticação da SUPRA é tratado como "sem dados":** hoje a resposta `status: false` vira
  conteúdo vazio (ou `_nao_encontrado`) e seguiria para a LLM, que avaliaria "nada" — gastando token e
  gerando um "Não Conforme" enganoso. Proposta no backlog (`architecture.md` §8): distinguir erro de
  acesso (ex.: "Usuário não cadastrado") de "seção vazia" e devolver `ok: false` sem chamar a LLM.
  *Aguardando confirmação* — é mudança de comportamento em relação ao n8n.

---

## Histórico de entregas (mais recente primeiro)

### 2026-09-28 — Teste de integração em dev (parcial) + correção de TLS
- `.env` preenchido pelo Lucas (ENV=dev, 1 admin, chaves presentes).
- **Dry-run real dos 14 tópicos** (SUPRA/Nominatim/Open-Meteo reais, OpenAI simulada): pipeline completo
  sem exceções em ~3 s; mas a SUPRA devolveu "Usuário não cadastrado" para todas as seções (B2).
- **Webhook real** (servidor local): sem `X-API-Key` → 401 ✅; com chave → 200 ✅; tópicos sem prompt →
  `ok: false` sem derrubar os demais ✅; nenhum segredo nos logs ✅. Chamada à OpenAI falhou: primeiro por
  certificado (corrigido), depois pelo firewall (B1).
- **Correção:** cliente HTTP valida TLS com o repositório de certificados do sistema
  (`ssl.create_default_context()` no transport do httpx) — necessário na rede do DNIT.

### 2026-09-28 — Fases 1, 2a e 2b (commit `d7d5386`)
- **Fase 1:** ativação de tópicos em `config/topics.yaml` (falha segura → 503), prompts em
  `prompts/<chave>.md`, regra de seleção, variável `ENV`.
- **Fase 2a:** login de admin (argon2id, sessão no servidor, CSRF, limite de tentativas), `X-API-Key` no
  webhook, `/docs` desligado, cabeçalhos de segurança, `create_app` com rotas por ambiente.
- **Fase 2b:** API de configuração — ligar/desligar tópicos, editar prompts, executar (com `dry_run` e
  tópicos avulsos), logs por execução.
- 161 → 235 testes.

### 2026-09-21 — Etapa 1: migração n8n → Python (commits `e08daf6`…`eb6ba9c`)
- Scaffolding, configuração tipada, clientes HTTP (SUPRA, OpenAI, Open-Meteo, Nominatim).
- Registro declarativo dos 14 tópicos + pipeline genérico + handlers (imagem, contratuais, pluviométrico).
- Execução paralela via `asyncio.gather`. 41 testes.

---

## Próximos passos (ordem sugerida)

1. [ ] B1 — pedir liberação de `api.openai.com` à rede do DNIT (ou definir onde o serviço vai rodar).
2. [ ] B2 — token SUPRA novo + contrato/período de teste com dados.
3. [ ] B3 — recuperar/redigir os 14 prompts.
4. [ ] Refazer o teste de integração: `dry_run` completo → execução real de 1 tópico barato → todos.
5. [ ] Fase 3 — tela de configuração (pode começar em paralelo aos itens 1–3).
6. [ ] Fase 4 — tela de resultado.
