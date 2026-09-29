# Andamento do projeto — Supra IA

Registro vivo do que foi entregue, onde estamos atacando, o que está bloqueado e o que vem a seguir.
**Atualize ao fim de cada tarefa** (entrada nova no topo do histórico + quadros abaixo).
Decisões técnicas e detalhes ficam em [`architecture.md`](architecture.md); aqui fica o *status*.

> Última atualização: **2026-09-29**

---

## Situação em uma olhada

| Frente | Estado |
|---|---|
| Migração dos 14 tópicos (Etapa 1) | ✅ Código pronto e testado com mocks |
| Configuração de tópicos (ativação + prompts em arquivo) — fase 1 | ✅ |
| Segurança (login admin, chave do webhook, `/docs` off) — fase 2a | ✅ |
| API de configuração (`/api/topicos`, `/api/prompts`, `/api/executar`, `/api/logs`) — fase 2b | ✅ |
| Acesso à SUPRA (token JWT) | ✅ Resolvido — dry-run real com dados em 14/14 tópicos (com a SUPRA estável) |
| **Teste de integração real com OpenAI** | ⛔ **Bloqueado** pelo firewall (B1) |
| Prompts de cada tópico (`prompts/<chave>.md`) | ⚠️ Não existem ainda — ver "Bloqueios" |
| Tela de configuração (dev) — fase 3 | ✅ `http://localhost:8000/` — validada com dry-run (sem OpenAI) |
| Criar tópico `campo`/`json` pela tela | ✅ 2026-09-29 — `config/topicos_extras.yaml` |
| Tela de resultado (dev/homolog) — fase 4 | ⏳ |
| Grupo 3 (Construtora), Documentação Fotográfica | 💤 Fora do escopo atual |

Testes automatizados: **333 passando** (`pytest`).

**Depois da liberação da OpenAI, o fluxo roda pela tela?** Sim. O botão Executar usa exatamente o mesmo
caminho do webhook (`processing/execucao.py`), já exercitado com SUPRA real, dry-run e smoke test da tela.
O único trecho nunca executado com resposta real é a chamada HTTP à OpenAI (coberta por testes com mocks).
Para rodar de verdade faltam: liberação (B1) e os prompts (B3) — estes podem ser escritos e salvos pela
própria tela. O token SUPRA (B2) foi resolvido em 2026-09-28.

---

## Bloqueios (precisam de ação fora do código)

| # | Bloqueio | Evidência | Quem resolve / o que fazer |
|---|---|---|---|
| B1 | **Firewall do DNIT bloqueia a OpenAI.** `api.openai.com` cai na categoria `DNIT_DENY` do FortiGuard e recebe uma página HTML 403. A chamada **nem chega à OpenAI** (nada é cobrado e a chave nem é validada). | Teste de 2026-09-28: `GET /v1/models` e `POST /v1/chat/completions` → 403 "Web Filter Violation … Category DNIT_DENY". | Equipe de rede/segurança do DNIT: pedir **liberação de `api.openai.com`** (443) para a máquina/servidor do Supra IA. Alternativa: rodar em um servidor fora dessa política (onde o n8n rodava?). |
| ~~B2~~ ✅ | ~~**SUPRA recusava o token.**~~ **Resolvido em 2026-09-28.** Duas causas em sequência: (1) "Usuário não cadastrado ou dados inválidos." — o token carrega e-mail + senha, e a senha tinha sido trocada; (2) "Token inválido." — no jwt.io estava marcada a opção *"secret base64 encoded"*, o que gera assinatura errada. | Token regerado corretamente: capa, justificativa, OAEs e demais seções respondem com dados (contrato `00 00493/2013`, out/2025). | Guia no `.env.example`. Ao trocar a senha do SUPRA, gerar o token de novo. |
| B3 | **Não há prompts.** No n8n eles chegavam no payload do sistema chamador (`prompts[]`); não estão no export. Sem prompt, o tópico ativo volta `ok: false`. | `prompts/` só tem o README. | Recuperar os prompts usados em produção no n8n (ou redigi-los com o analista) e salvá-los em `prompts/<chave>.md` — pela API `PUT /api/prompts/{chave}` ou pela tela da fase 3. |

---

## Onde estamos atacando agora

1. **Destravar o teste real** (B1–B3). A tela já está pronta para isso: escrever os prompts no editor, rodar
   um dry-run para conferir dados e prompts, e depois a execução real de um tópico ("Só este ▶").
2. **Validação visual da tela pelo Lucas** (abrir `http://localhost:8000/`, entrar com o admin do `.env`) e
   ajustes de usabilidade.
3. **Fase 4 — tela de resultado** (dev/homolog), para o analista avaliar as respostas.

---

## Pontos de atenção descobertos (não bloqueiam)

- **Instabilidade da SUPRA (2026-09-28):** (a) com ~15 chamadas simultâneas o proxy da SUPRA devolve
  "502 Proxy Error" para algumas — **tratado** (máx. 4 simultâneas + nova tentativa em 502/503/504);
  (b) mesmo com chamadas isoladas, às vezes ela **trava** (sem resposta até o timeout de 120 s) ou devolve
  corpo que não é JSON. Isso **não** é tratado: o tópico volta `ok: false` (os demais seguem). Numa execução
  com a SUPRA estável: 14/14 em ~2 s. Se virar rotina, avaliar timeout próprio da SUPRA (ex.: 30 s) com uma
  nova tentativa — *não implementado, aguarda decisão*.
- **Erro de timeout aparece sem mensagem** no resultado (`erro: ""`), porque a exceção do httpx não tem
  texto. Melhoria simples possível: incluir o tipo do erro (ex.: "ReadTimeout"). *Não implementado.*
- **Documento da SUPRA contém a `encryption_key`** (chave que assina TODOS os tokens — com ela, qualquer
  pessoa gera token de qualquer usuário). O `.docx` foi colocado no `.gitignore` e nunca foi versionado.
  Recomendação: não circular o documento com a chave; pedir à equipe da SUPRA que a remova da
  documentação (e, idealmente, que a rotacione, já que foi distribuída).
- **Como saber se a SUPRA respondeu bem num dry-run:** no resultado, abra "Mensagens que seriam enviadas"
  → mensagem `user`: texto/registros = dados OK; vazio ou `_nao_encontrado` com `mensagem` = SUPRA
  respondeu sem dados/recusou; selo **Erro** = falha de rede/HTTP/timeout. Nos logs, `WARNING … nova
  tentativa` indica 502 contornado.

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

### 2026-09-29 — Todos os tópicos da lista "Tópico do Relatório" viram cards
- 26 tópicos novos em `config/topicos_extras.yaml` (estratégia `json`, nascem desligados); os 40 itens
  de `topicos_relatorio.js` agora têm `chave`. Cards ordenados pela lista; excluir virou ícone de lixeira
  ao lado do interruptor.
- Endpoint SUPRA **confirmado** (fluxo n8n): `atividades_supervisora` (→ `atividades_supervisora_descricao`),
  `info_contratuais_construtora`, `termos_aditivos_construtora`, `apostilas_construtora` (os dois últimos
  copiam a config dos equivalentes da Supervisora).
- `documentacao_fotografica`: endpoint real, mas no fluxo genérico só manda os metadados à LLM — as
  imagens precisam de handler próprio (`gpt-4o`).
- **Endpoint provisório (= chave), A CONFIRMAR com a SUPRA** — dá erro ao executar até ser corrigido:
  `mobilizacao_supervisora`, `mobilizacao_construtora`, `atividades_construtora`,
  `acompanhamento_fisico_financeiro`, `acompanhamento_financeiro`, `acompanhamento_fisico`,
  `analise_cronogramas`, `resumo_avanco_fisico`, `componente_ambiental`, `gestao_qualidade`,
  `ensaios_laboratorio_construtora`, `ensaios_laboratorio_supervisora`, `pvegq`, `nao_conformidades`,
  `gestao_juridica`, `gestao_riscos`, `atas_correspondencias`, `gestao_tratativas`, `conclusao`,
  `termo_encerramento`, `anexos`.

### 2026-09-29 — Excluir prompt pela aba Tópicos

- Cartão de tópico com prompt salvo ganha o botão **Excluir** (2º clique confirma): apaga `prompts/<chave>.md`.
  O tópico continua na lista, sem prompt (se estiver ligado, volta `ok=false` "sem prompt" ao executar).
- Backend: `DELETE /api/prompts/{chave}` (admin + CSRF, só dev; idempotente; chave fora de `TOPICS` = 404;
  logado com o usuário) e `excluir_prompt()` em `app/prompts_store.py`. Testes em `test_prompts_store.py` e
  `test_admin_api.py`.

### 2026-09-29 — Ajuste de botões na aba Tópicos

- Removido da tela o botão "+ Novo tópico" (formulário de criar tópico) e o formulário dele.
- O botão "+ Novo Relatório" (modal Novo Prompt) passou a se chamar **"+ Novo tópico"**.
- Lista "Tópico do Relatório" do modal: removido o grupo "CHAT IA - AIRA" (item 0).
- A API `POST /api/topicos` e `config/topicos_extras.yaml` continuam no backend (com testes); só não há
  mais tela para criar tópico. Tópicos já criados continuam aparecendo com o selo "criado na tela".

### 2026-09-29 — Modal "Novo Prompt" (botão "+ Novo Relatório")

- Botão **+ Novo Relatório** na aba Tópicos abre o modal **Novo Prompt** (tema escuro próprio): Título *,
  Tópico do Relatório * (lista agrupada IN_51 com ~45 itens, rolagem interna, teclado), editor Markdown e
  **preview em tempo real** lado a lado; Cancelar/Salvar (Salvar só com os três campos preenchidos).
- A lista fica em `app/ui/static/topicos_relatorio.js`. Só os 14 itens que já são tópicos (`chave`) são
  selecionáveis; os demais aparecem como "em breve". Salvar grava `prompts/<chave>.md` (`PUT /api/prompts`);
  se o tópico já tem prompt (ou rascunho no editor), o modal avisa e pede um 2º clique para substituir.
- O **título não é gravado**: o sistema guarda um prompt por tópico, sem campo de título (vai só no aviso).
- Preview: conversor Markdown próprio que monta nós DOM (nunca `innerHTML`; links só http/https) — a CSP
  não permite bibliotecas externas. Testes: `test_ui.py` confere que toda `chave` da lista existe. **333 passando.**

### 2026-09-29 — Criar tópico pela tela ("+ Novo tópico")

- Botão **+ Novo tópico** na aba Tópicos: formulário com os mesmos campos de `TopicConfig` (título, grupo,
  chave, endpoint SUPRA, modelo, max_tokens, estratégia, campos com HTML, campos a manter/presença, `[]` se
  vazio) e **"Copiar configuração de"** um tópico existente. Só `campo` e `json` (os demais exigem handler).
- Backend: `POST /api/topicos` → `config/topicos_extras.yaml` (novo, versionado) via `app/topicos_extras.py`;
  entra em `TOPICS` na hora e em toda inicialização. Nasce **desligado e sem prompt**; ligar/prompt/"Só este ▶"
  funcionam como nos demais. Cartão mostra o selo "criado na tela". Como o arquivo está em `config/`, vai para
  homolog/prod no commit/imagem.
- Ajustes de suporte: `topics.yaml` agora agrupa por grupo (o tópico novo entra no grupo dele); limite de
  tópicos de `POST /api/executar` passou a ser dinâmico; `TOPICOS_BASE` = só os do código.
- Testes: `tests/test_topicos_extras.py` (novo) + casos em `test_admin_api.py` (inclusive sem sessão/CSRF e
  fora de dev). **325 passando.**
- Não há editar/excluir pela tela: corrigir um tópico criado = editar `config/topicos_extras.yaml` e reiniciar.

### 2026-09-29 — Tela de configuração organizada em abas (só layout)

- A tela única virou: **barra de execução** fixa no topo (contrato, período, dry-run, Executar — fica fora
  das abas porque o "Só este ▶" dos cartões usa esses campos) + abas **Tópicos | Resultado | Logs do servidor**.
- Ao iniciar uma execução a tela vai para a aba Resultado; se o resultado chegar com outra aba aberta, a aba
  ganha um marcador. A aba aberta fica no endereço (`#resultado`, `#logs`) e sobrevive ao F5. Setas/Home/End
  trocam de aba pelo teclado. Painel de logs ficou mais alto (acompanha a altura da janela).
- Nenhuma mudança de API, estado ou regra: todos os IDs e funções existentes foram mantidos; o JS novo só
  mostra/esconde painéis. `tests/test_ui.py`: 28 passando.
- Aba Resultado (dry-run): em "Mensagens que seriam enviadas", `system` e `user` ficam **lado a lado**, cada
  uma com rolagem própria (empilham em tela estreita), já abertas ao terminar a análise.

### 2026-09-28 — Acesso à SUPRA resolvido + proteção contra 502
- **Token SUPRA:** diagnosticadas as duas causas (senha trocada; assinatura errada por "secret base64
  encoded" no jwt.io) comparando o token com a documentação da SUPRA, sem expor valores. Token regerado.
- **Dry-run real com dados:** contrato `00 00493/2013` (out/2025) — capa, justificativa (~880 tokens),
  histórico (54 registros; usa o 1º, igual ao n8n), OAEs (9), RPFO (3), termos aditivos (15), apostilas (11),
  imagens do mapa (~940 KB) e diagrama (~660 KB), pluviométrico etc. Estimativa de uma execução completa:
  ~14,6 mil tokens de entrada em texto + 2 imagens no gpt-4o.
- **Proteção contra "502 Proxy Error"** (`app/clients/dnit.py`): no máximo 4 requisições simultâneas à
  SUPRA e até 2 novas tentativas em 502/503/504 (configurável: `DNIT_MAX_CONCORRENCIA`, `DNIT_RETRIES`,
  `DNIT_RETRY_ESPERA`). Nada muda nos dados, parâmetros, headers, prompts, OpenAI ou formato da resposta —
  14 testes novos verificam isso. Antes: 4 tópicos com 502 numa execução; depois: os 502 foram repetidos com
  sucesso, e numa execução com a SUPRA estável, 14/14 em ~2 s.
- `.gitignore`: documento da SUPRA com a `encryption_key`. `.env.example`: guia para gerar o token.

### 2026-09-28 — Fase 3: tela de configuração
- Página única em `http://localhost:8000/` (só `ENV=dev`), HTML/CSS/JS puro, tema claro/escuro:
  login; cartões de tópicos por grupo (ligar/desligar, ativar/desligar grupo, selo de custo `$$$`, estado
  do prompt) com barra "N alterações não salvas — Descartar/Salvar"; editor de prompt (rascunho vale na
  execução, "Salvar no arquivo" grava `prompts/<chave>.md`); Executar (dry-run marcado por padrão; execução
  real pede confirmação; "Só este ▶" por cartão); resultado por tópico com selos, `motivo`, JSON e `infos`;
  painel de logs ao vivo, filtrável pela execução.
- Segurança: nada inline (CSP), dados sempre como texto, CSRF só em memória; 28 testes novos (rotas por
  ambiente + verificação estática do front). 235 → 263 testes.
- **Smoke test** (servidor de demonstração com admin temporário e cópias da configuração): página e
  estáticos, login/logout, ligar tópico (com e sem CSRF), salvar prompt, executar em dry-run (prompt salvo e
  rascunho aplicados corretamente) e logs filtrados pela execução — tudo OK. A verificação visual no
  navegador ficou pendente (extensão do Chrome não conectada nesta sessão).

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
2. [x] ~~B2 — token SUPRA novo + contrato/período de teste com dados~~ (2026-09-28).
3. [ ] B3 — recuperar/redigir os 14 prompts.
4. [ ] Refazer o teste de integração **pela tela**: dry-run completo → "Só este ▶" real num tópico barato → todos.
5. [x] ~~Fase 3 — tela de configuração~~ (2026-09-28) · [ ] validação visual e ajustes pelo Lucas.
6. [ ] Fase 4 — tela de resultado.
