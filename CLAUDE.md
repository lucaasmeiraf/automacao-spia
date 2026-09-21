# CLAUDE.md — Supra AI

Guia de trabalho para Claude Code neste projeto. Leia antes de qualquer implementação.

---

## Contexto do Projeto

Sistema de auditoria automatizada de Relatórios de Supervisão do DNIT (IN_51/2021).
Migração de fluxo n8n → Python com FastAPI. Consulte `docs/architecture.md` para a documentação completa.

**Stack**: Python 3.11+, FastAPI, asyncio, aiohttp, OpenAI API, PyYAML, python-dotenv.

---

## Estrutura e Convenções

### Pastas

```
config/          # settings.py + topics.yaml (toggles de tópicos)
src/clients/     # Clientes HTTP para APIs externas (SUPRA, OpenAI, Open-Meteo, Nominatim)
src/processors/  # 1 arquivo por tópico/seção; subpasta supervisora/ para a Apresentação Supervisora
src/utils/       # html.py (strip_html), llm_parser.py (parse de respostas LLM)
src/pipeline.py  # Orquestra todos os processors em paralelo com asyncio.gather
app.py           # FastAPI entry point
docs/            # Documentação de arquitetura e decisões
```

### Código

- Todo código de I/O (HTTP, arquivo) deve ser **async**.
- Cada processor herda `BaseProcessor` (`src/processors/base.py`). Não crie processors que não herdem dela.
- Cada processor implementa: `fetch()`, `prepare()`, `analyze()`, `clean_response()`, `run()`.
- `run()` é sempre o único método chamado externamente pelo pipeline.
- Não adicione lógica de negócio em `pipeline.py` — ele apenas decide quais processors rodar e os executa em paralelo.
- Clients HTTP (`src/clients/`) não têm lógica de negócio — apenas fazem chamadas e retornam dados brutos.

### Variáveis de Ambiente

- Credenciais **nunca** vão no código — sempre em `.env.{ENV}`.
- O ambiente ativo é determinado pela variável `ENV` (`dev`, `homolog`, `prod`).
- Arquivo carregado automaticamente pelo `config/settings.py`.

### Typo intencional

O parâmetro da query da API SUPRA é `periodo_incio` (sem "í"). **Não corrija**. É o parâmetro real da API.

---

## Sistema de Toggle de Tópicos

`config/topics.yaml` controla quais tópicos estão ativos. Um tópico só executa quando:
1. Está `true` no `topics.yaml`
2. O payload da requisição contém o prompt correspondente em `prompts[]`

Ao criar um novo processor, adicione sua chave no `topics.yaml` com `false` por padrão até estar testado.

---

## Sequência de Implementação (Etapa 1)

Sempre que iniciar uma nova sessão de implementação, siga esta ordem:

1. `config/settings.py` + `config/topics.yaml`
2. `src/clients/` — supra, openai_client, openmeteo, nominatim
3. `src/utils/html.py` + `src/utils/llm_parser.py`
4. `src/processors/base.py`
5. Processors por tópico (ordem: justificativa → resumo_projeto → oaes → rpfo → historico → introducao → mapa_situacao → diagrama_ocorrencias → supervisora/*)
6. `src/pipeline.py`
7. `app.py`

Marque cada etapa como concluída no `docs/architecture.md` (seção 7) ao finalizar.

---

## Antes de Implementar Qualquer Coisa

1. **Leia** `docs/architecture.md` inteiro.
2. **Verifique** se o tópico/seção já existe em `src/processors/`.
3. **Confirme** que o processor herda `BaseProcessor`.
4. **Confirme** que a chave do tópico está em `config/topics.yaml`.
5. Se for um novo client HTTP, **confirme** que não existe lógica de negócio no client.

---

## Testes Obrigatórios

Execute estes testes após qualquer mudança antes de considerar a tarefa concluída:

### 1. Validação de Estrutura
```bash
# Verifica imports e sintaxe sem executar
python -m py_compile src/processors/<arquivo>.py
python -m py_compile src/clients/<arquivo>.py
```

### 2. Teste Unitário do Processor
Cada processor deve ter pelo menos um teste em `tests/processors/test_<nome>.py` cobrindo:
- `prepare()` com dado de entrada mockado (não chama API real)
- `clean_response()` com resposta LLM mockada (string JSON válido e string inválida)

```bash
pytest tests/ -v
```

### 3. Teste de Integração (apenas em dev)
Antes de marcar um processor como pronto, execute uma chamada real contra a API SUPRA com um contrato de teste válido e verifique:
- O campo `conforme` retornou um valor válido: `"Conforme"`, `"Atenção"` ou `"Não Conforme"`
- O campo `motivo` é uma string não vazia
- O campo `infos` contém os dados brutos da API
- Nenhuma exception não tratada foi levantada

### 4. Teste de Paralelismo
Ao modificar `pipeline.py`, execute com pelo menos 3 tópicos simultâneos e verifique:
- Todos os resultados estão presentes no array `analises`
- Erros em um tópico não interrompem os demais (use `return_exceptions=True` no `asyncio.gather`)

### 5. Verificação de Ambiente
```bash
# Confirma que as variáveis de ambiente críticas estão carregadas
python -c "from config.settings import settings; print(settings.ENV, settings.SUPRA_TOKEN[:10])"
```

---

## Quando Atualizar `docs/architecture.md`

Atualize a documentação sempre que:

- Um novo processor for implementado e testado → marque na seção 7 (Sequência)
- Um novo endpoint SUPRA for descoberto ou corrigido → atualize a seção 4
- Uma issue do backlog for implementada → mova da lista de issues para a seção correspondente
- O formato de entrada/saída mudar → atualize a seção 5
- Uma decisão de arquitetura mudar → adicione à seção correspondente com data

**Nunca** espere acumular muitas mudanças para atualizar — atualize ao final de cada tarefa concluída.

---

## Padrões de Código

### Processor típico

```python
from src.processors.base import BaseProcessor
from src.utils.html import strip_html
from src.utils.llm_parser import parse_llm_response

class JustificativaProcessor(BaseProcessor):
    IDENTIFICADOR = "Justificativa"
    ENDPOINT = "justificativa"

    async def fetch(self) -> dict:
        return await self.supra.get(self.ENDPOINT, self.params)

    async def prepare(self, data: dict) -> str:
        resultado = data.get("resultado", [{}])[0]
        return strip_html(resultado.get("resumo", ""))

    async def analyze(self, content: str) -> dict:
        return await self.openai.chat(
            system=self.prompt,
            user=content,
            model="gpt-4o-mini",
            max_tokens=1200
        )

    async def clean_response(self, raw: dict) -> dict:
        content = raw["choices"][0]["message"]["content"]
        result = parse_llm_response(content, self.IDENTIFICADOR)
        result["infos"] = self._raw_data
        return result
```

### Tratamento de erro em processors

Nunca deixe um processor explodir silenciosamente. Se `fetch()` falhar, retorne um objeto de erro estruturado:

```python
async def run(self) -> dict:
    try:
        data = await self.fetch()
        ...
    except Exception as e:
        return {
            "identificador": self.IDENTIFICADOR,
            "conforme": "Erro",
            "motivo": f"Falha ao processar: {str(e)}",
            "infos": None
        }
```

### Limpeza de HTML

Use sempre `strip_html()` de `src/utils/html.py` para qualquer campo que possa conter HTML. Nunca replique a lógica de limpeza inline.

### Parse de resposta LLM

Use sempre `parse_llm_response()` de `src/utils/llm_parser.py`. Ela já trata:
- Remoção de blocos ` ```json ` 
- JSON inválido (fallback com regex)
- Campos ausentes

---

## Issues Ativas e Próximas Etapas

Ver `docs/architecture.md` seção 8 (Issues Futuras).

Antes de implementar qualquer issue do backlog, **confirme com o usuário** que ela faz parte do escopo atual.

---

## Observações Importantes

- Este é um projeto em múltiplos ambientes (dev → homolog → prod). Nunca hardcode credenciais.
- O Grupo 3 (Construtora) está parcialmente implementado no n8n mas **não deve ser migrado ainda** — tratado como issue futura.
- Os 4 nós desabilitados do n8n (Agente Construtora, Acomp. Físico, Análise Crítica, Pluviométrico agente) **não são migrados**.
- O processor de Documentação Fotográfica (`doc_fotografica.py`) existe mas fica `false` no `topics.yaml` por padrão para não consumir créditos de API desnecessariamente.
- Modelos: `gpt-4o-mini` para texto, `gpt-4o` para visão (imagens). Confirme isso nas variáveis de ambiente antes de testar.
