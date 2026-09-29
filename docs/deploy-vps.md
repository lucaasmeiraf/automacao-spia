# Subindo o Supra IA na VPS

Passo a passo para colocar a aplicação no ar na VPS com Docker e acessá-la da sua máquina por túnel SSH.

## Onde fica cada coisa

| O quê | Onde |
|---|---|
| Pasta do projeto (repositório git) | `/srv/projetos/automacao-spia/app` |
| Arquivo de configuração com as chaves | `/srv/projetos/automacao-spia/app/.env` (fora do Git) |
| Container | `supra-ia` |
| Porta na VPS | `127.0.0.1:8010`, só acessível de dentro da VPS ou pelo túnel |

> Por que a 8010: as portas 3000, 8000 e 8001 já são usadas por outros sistemas desta VPS.
> A aplicação escuta só em `127.0.0.1`, então não fica exposta na internet; o acesso é pelo túnel SSH.

## 1. Pré-requisito: permissão no Docker

O usuário precisa estar no grupo `docker`. Para conferir:

```bash
docker ps
```

Se aparecer `permission denied`, há duas saídas:

- usar `sudo` na frente de cada comando `docker` (ex.: `sudo docker compose up --build -d`); ou
- incluir o usuário no grupo (uma vez só) e **sair e entrar de novo** no SSH:

  ```bash
  sudo usermod -aG docker lucas
  ```

  Atenção: quem está no grupo `docker` tem, na prática, poder de administrador na VPS.

## 2. Configurar o `.env` (só na primeira vez)

```bash
cd /srv/projetos/automacao-spia/app
cp .env.example .env
nano .env
```

Preencha conforme a seção **"Configurando o .env"** do `README.md`. No `nano`: `Ctrl+O` e Enter para salvar, `Ctrl+X` para sair.
Não use aspas nem espaços em volta do `=` (exceção: `ADMIN_USERS`, que vai entre aspas simples).

Para conferir se sobrou algum texto de exemplo (deve imprimir `0`):

```bash
grep -c "COLOQUE" .env
```

## 3. Subir a aplicação

```bash
cd /srv/projetos/automacao-spia/app
docker compose up --build -d
```

- `--build` monta a imagem com o código atual (use sempre depois de um `git pull`).
- `-d` deixa rodando em segundo plano. O container reinicia sozinho se a VPS reiniciar.

Para conferir se subiu:

```bash
docker compose ps                   # STATUS deve ficar "healthy" após ~30 s
curl http://localhost:8010/health
```

## 4. Acessar da sua máquina (túnel SSH)

No **seu computador**, conecte à VPS encaminhando a porta 8010:

```bash
ssh -L 8010:localhost:8010 lucas@IP_DA_VPS
```

Para acessar também o outro sistema da VPS (porta 3000) no mesmo SSH, use outra porta local para ele
(ex.: 3001, deixando a 3000 do seu computador livre):

```bash
ssh -L 3001:localhost:3000 -L 8010:localhost:8010 lucas@IP_DA_VPS
```

Com o SSH aberto, acesse no navegador: **http://localhost:8010**

Em `-L A:localhost:B`, **A** é a porta no seu computador (qualquer uma livre) e **B** é a porta na VPS
(sempre `8010` para este projeto). Se a 8010 já estiver em uso no seu computador, troque só o A:

```bash
ssh -L 9010:localhost:8010 lucas@IP_DA_VPS   # acesse http://localhost:9010
```

Se o SSH mostrar `bind: Address already in use`, a porta A está ocupada no seu computador. Escolha outra.

- A tela de configuração e o login só existem com `ENV=dev`.
- O login funciona por `http://localhost` mesmo com `COOKIE_SECURE=true`, porque os navegadores tratam `localhost` como seguro.
  Por `http://IP_DA_VPS` o login **não** funciona.
- O túnel fica ativo enquanto a sessão SSH estiver aberta.

## 5. Atualizar para uma versão nova do código

```bash
cd /srv/projetos/automacao-spia/app
git pull
docker compose up --build -d
```

O `.env` não é afetado pelo `git pull` (está no `.gitignore`).

## 6. Comandos do dia a dia

| Para… | Comando (dentro de `/srv/projetos/automacao-spia/app`) |
|---|---|
| Ver os logs ao vivo (`Ctrl+C` sai) | `docker compose logs -f` |
| Ver as últimas 100 linhas de log | `docker compose logs --tail 100` |
| Reiniciar (ex.: depois de editar o `.env`) | `docker compose up -d --force-recreate` |
| Parar | `docker compose down` |
| Ver o estado | `docker compose ps` |

> Depois de alterar o `.env` é preciso recriar o container (`--force-recreate`); um `restart` simples não relê o arquivo.

## Problemas comuns

| Sintoma | Causa provável / solução |
|---|---|
| `permission denied ... docker.sock` | Usuário fora do grupo `docker`, ver passo 1. |
| `port is already allocated` | Outro sistema usa a porta. Troque `8010` no `docker-compose.yml` (lado esquerdo) e no túnel. |
| Container reiniciando em loop | `docker compose logs --tail 50`. Normalmente é chave faltando ou inválida no `.env` (ex.: `WEBHOOK_API_KEY` com menos de 32 caracteres, `ADMIN_USERS` sem hash argon2). |
| Navegador não abre `localhost:8010` | O SSH com `-L 8010:localhost:8010` não está aberto, ou o container está parado. |
| Webhook responde 503 | `WEBHOOK_API_KEY` ausente no `.env`, ou `config/topics.yaml` inválido. |
| Login não "segura" (volta para a tela de login) | Acesso por IP em vez de `localhost`; use o túnel. |
