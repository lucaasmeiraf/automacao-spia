# Prompts por tópico

Cada tópico pode ter seu prompt de sistema (a instrução enviada à LLM) versionado aqui:

```
prompts/<chave_do_topico>.md        ex.: prompts/justificativa.md
```

- O nome do arquivo é a **chave** do tópico (a mesma de `app/topics.py` e `config/topics.yaml`).
  Arquivos com nome que não seja de um tópico conhecido são ignorados.
- Codificação **UTF-8**. O conteúdo inteiro do arquivo (sem espaços nas pontas) é o prompt.
- **Precedência:** se a requisição trouxer o prompt do tópico em `prompts[]`, ele vale; o arquivo é o
  padrão usado quando o payload não traz.
- Arquivo vazio ou ausente = tópico sem prompt. Se o tópico estiver ativo, a resposta traz
  `ok: false` com o motivo.

Chaves disponíveis: justificativa, resumo_projeto, historico, introducao, oaes, rpfo, mapa_situacao,
diagrama_ocorrencias, info_contratuais_supervisora, termos_aditivos_supervisora,
responsaveis_tecnicos_supervisora, paralisacao_reinicio, apostilas_supervisora, controle_pluviometrico.

> Prompts são instruções de negócio, não segredos — mas não coloque chaves, tokens ou dados de
> contratos reais dentro deles.
