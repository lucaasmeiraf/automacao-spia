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
| Acesso à SUPRA (token JWT) | ✅ Resolvido — dry-run real com dados em 14/14 tópicos (com a SUPRA estável) |
| **Teste de integração real com OpenAI** | ⛔ **Bloqueado** pelo firewall (B1) |
| Prompts de cada tópico (`prompts/<chave>.md`) | ⚠️ Não existem ainda — ver "Bloqueios" |
| Tela de configuração (dev) — fase 3 | ✅ `http://localhost:8000/` — validada com dry-run (sem OpenAI) |
| Tela de resultado (dev/homolog) — fase 4 | ⏳ |
| Grupo 3 (Construtora), Documentação Fotográfica | 💤 Fora do escopo atual |

Testes automatizados: **277 passando** (`pytest`).

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
