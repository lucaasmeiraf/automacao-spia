/*
 * Supra IA — tela de configuração (ENV=dev, somente admin).
 *
 * É só um cliente da API (docs/architecture.md §10.5). Regras de segurança deste arquivo:
 *   - TODO dado vindo da API (respostas da LLM, dados da SUPRA, logs) entra na página como TEXTO
 *     (textContent / nós de texto). Nunca innerHTML — um teste automatizado verifica isso;
 *   - o token CSRF fica só em memória (variável), nunca em localStorage/cookie legível;
 *   - a sessão é o cookie HttpOnly: o JavaScript não o vê.
 */
"use strict";

(() => {
  // ---------------------------------------------------------------------------
  // Estado
  // ---------------------------------------------------------------------------
  const estado = {
    usuario: null,
    csrf: null,
    topicos: [],              // lista do servidor (ordem de TOPICS)
    salvo: new Map(),         // chave -> ativo no config/topics.yaml
    tela: new Map(),          // chave -> ativo na tela (pode diferir do salvo)
    prompts: new Map(),       // chave -> conteúdo salvo em prompts/<chave>.md (ou null)
    rascunhos: new Map(),     // chave -> texto editado e ainda não salvo
    maxPrompt: 50000,
    refs: new Map(),          // chave -> elementos do cartão
    executando: false,
    ultimaResposta: null,
    ultimaExecucao: null,
    logSeq: 0,
    logTimer: null,
    dlgChave: null,
  };

  const $ = (id) => document.getElementById(id);

  /** Cria um elemento. Filhos string viram NÓS DE TEXTO (nunca HTML). */
  function el(tag, attrs, ...filhos) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") e.className = v;
      else if (k === "text") e.textContent = v;
      else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
      else e.setAttribute(k, v === true ? "" : String(v));
    }
    for (const f of filhos.flat()) {
      if (f === null || f === undefined || f === false) continue;
      e.append(f instanceof Node ? f : document.createTextNode(String(f)));
    }
    return e;
  }

  function limpar(no) { no.replaceChildren(); }

  let toastTimer = null;
  function toast(msg, erro = false) {
    const t = $("toast");
    t.textContent = msg;
    t.classList.toggle("erro", erro);
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, erro ? 6000 : 3000);
  }

  // ---------------------------------------------------------------------------
  // API
  // ---------------------------------------------------------------------------
  class ErroApi extends Error {
    constructor(status, mensagem) { super(mensagem); this.status = status; }
  }

  function mensagemDeErro(status, dados, retryAfter) {
    const d = dados && dados.detail;
    if (Array.isArray(d)) {
      return d.map((e) => {
        const campo = (e.loc || []).filter((p) => p !== "body").join(".");
        return campo ? `${campo}: ${e.msg}` : e.msg;
      }).join("; ");
    }
    if (typeof d === "string") return status === 429 && retryAfter ? `${d} (aguarde ${retryAfter} s)` : d;
    return `Erro ${status}.`;
  }

  async function api(metodo, caminho, corpo) {
    const headers = { Accept: "application/json" };
    if (corpo !== undefined) headers["Content-Type"] = "application/json";
    if (metodo !== "GET" && estado.csrf) headers["X-CSRF-Token"] = estado.csrf;

    let resp;
    try {
      resp = await fetch(caminho, {
        method: metodo,
        headers,
        body: corpo === undefined ? undefined : JSON.stringify(corpo),
        credentials: "same-origin",
        cache: "no-store",
      });
    } catch {
      throw new ErroApi(0, "Sem conexão com o servidor.");
    }

    let dados = null;
    try { dados = await resp.json(); } catch { /* corpo vazio ou não-JSON */ }
    if (resp.ok) return dados;

    const msg = mensagemDeErro(resp.status, dados, resp.headers.get("Retry-After"));
    if (resp.status === 401 && estado.usuario) sessaoExpirada();
    throw new ErroApi(resp.status, msg);
  }

  // ---------------------------------------------------------------------------
  // Sessão
  // ---------------------------------------------------------------------------
  function mostrarLogin(mensagem) {
    $("tela-app").hidden = true;
    $("topo-sessao").hidden = true;
    $("barra-pendentes").hidden = true;
    $("tela-login").hidden = false;
    const erro = $("login-erro");
    erro.textContent = mensagem || "";
    erro.hidden = !mensagem;
    $("login-senha").value = "";
    $("login-usuario").focus();
  }

  function sessaoExpirada() {
    estado.usuario = null;
    estado.csrf = null;
    pararPollingLogs();
    for (const id of ["dlg-prompt", "dlg-novo-prompt"]) if ($(id).open) $(id).close();
    mostrarLogin("Sua sessão expirou. Entre novamente — rascunhos de prompts e alterações não salvas foram mantidos.");
  }

  async function entrou(sessao) {
    estado.usuario = sessao.usuario;
    estado.csrf = sessao.csrf_token;
    $("usuario").textContent = sessao.usuario;
    $("tela-login").hidden = true;
    $("tela-app").hidden = false;
    $("topo-sessao").hidden = false;
    await carregar();
    carregarLogs(true);
  }

  async function onLogin(ev) {
    ev.preventDefault();
    const usuario = $("login-usuario").value.trim();
    const senha = $("login-senha").value;
    if (!usuario || !senha) { mostrarLogin("Informe usuário e senha."); return; }
    const btn = $("btn-entrar");
    btn.disabled = true;
    try {
      const sessao = await api("POST", "/api/auth/login", { usuario, senha });
      $("login-senha").value = "";
      await entrou(sessao);
    } catch (e) {
      mostrarLogin(e.message);
    } finally {
      btn.disabled = false;
    }
  }

  async function onSair() {
    try { await api("POST", "/api/auth/logout"); } catch { /* já deslogado */ }
    estado.usuario = null;
    estado.csrf = null;
    pararPollingLogs();
    mostrarLogin("");
  }

  // ---------------------------------------------------------------------------
  // Tópicos
  // ---------------------------------------------------------------------------
  async function carregar() {
    const [topicos, prompts] = await Promise.all([api("GET", "/api/topicos"), api("GET", "/api/prompts")]);
    aplicarTopicos(topicos, true);
    estado.maxPrompt = prompts.max_caracteres;
    estado.prompts = new Map(prompts.prompts.map((p) => [p.chave, p.conteudo]));
    renderTopicos();
  }

  /** Atualiza o estado a partir do servidor. `manterTela`: preserva alterações pendentes. */
  function aplicarTopicos(resp, manterTela) {
    const pendentesAntes = manterTela ? pendentes() : new Map();
    estado.topicos = resp.topicos;
    estado.salvo = new Map(resp.topicos.map((t) => [t.chave, t.ativo]));
    estado.tela = new Map(estado.salvo);
    for (const [chave, valor] of pendentesAntes) if (estado.salvo.has(chave)) estado.tela.set(chave, valor);

    const aviso = $("aviso-config");
    aviso.textContent = resp.configuracao_valida ? "" : resp.mensagem || "Configuração de tópicos inválida.";
    aviso.hidden = resp.configuracao_valida;
  }

  function pendentes() {
    const m = new Map();
    for (const [chave, ativo] of estado.tela) if (estado.salvo.get(chave) !== ativo) m.set(chave, ativo);
    return m;
  }

  function selecionados() {
    return estado.topicos.filter((t) => estado.tela.get(t.chave)).map((t) => t.chave);
  }

  function info(chave) { return estado.topicos.find((t) => t.chave === chave); }

  function renderTopicos() {
    const raiz = $("grupos");
    limpar(raiz);
    estado.refs.clear();

    // Cartões na ordem da lista "Tópico do Relatório"; o que não estiver lá vai para o fim do grupo.
    const ordem = new Map();
    for (const g of window.TOPICOS_RELATORIO || []) {
      for (const it of g.itens) if (it.chave && !ordem.has(it.chave)) ordem.set(it.chave, ordem.size);
    }
    const topicos = [...estado.topicos].sort((a, b) => (ordem.get(a.chave) ?? Infinity) - (ordem.get(b.chave) ?? Infinity));

    const grupos = new Map();
    for (const t of topicos) {
      const g = t.grupo || "Outros";
      if (!grupos.has(g)) grupos.set(g, []);
      grupos.get(g).push(t);
    }

    let n = 0;
    for (const [nome, lista] of grupos) {
      n += 1;
      const cont = el("span", { class: "grupo-cont" });
      const secao = el("section", { class: "grupo" },
        el("div", { class: "grupo-cab" },
          el("h3", { text: `Grupo ${n} — ${nome}` }),
          cont,
          el("div", { class: "grupo-acoes" },
            el("button", { class: "btn btn-fantasma btn-mini", type: "button", text: "Ativar todos",
              onclick: () => marcarGrupo(lista, true) }),
            el("button", { class: "btn btn-fantasma btn-mini", type: "button", text: "Desligar todos",
              onclick: () => marcarGrupo(lista, false) }),
          ),
        ),
        el("div", { class: "cartoes" }, lista.map(cartao)),
      );
      secao.dataset.grupo = nome;
      estado.refs.set(`grupo:${nome}`, { cont, lista });
      raiz.append(secao);
    }
    atualizarResumo();
  }

  function cartao(t) {
    const input = el("input", { type: "checkbox", "aria-label": `Ativar ${t.titulo}` });
    input.checked = !!estado.tela.get(t.chave);
    input.addEventListener("change", () => {
      estado.tela.set(t.chave, input.checked);
      atualizarCartao(t.chave);
      atualizarResumo();
    });

    const selo = el("span");
    const pendente = el("span", { class: "selo-pendente", text: "alterado" });
    const excluir = el("button", { class: "btn btn-fantasma btn-mini btn-excluir", type: "button", text: "Excluir",
      title: `Excluir o prompt salvo (prompts/${t.chave}.md)`, onclick: (ev) => excluirPrompt(t.chave, ev.currentTarget) });
    const card = el("article", { class: "cartao" },
      el("div", { class: "cartao-cab" },
        el("h4", { text: t.titulo }),
        el("label", { class: "interruptor", title: "Ligar/desligar" }, input, el("span")),
      ),
      el("div", { class: "cartao-meta" },
        `${t.estrategia} · ${t.modelo}`,
        t.custo === "alto" ? el("span", { class: "custo-alto", title: "Modelo de visão: custo alto por chamada", text: "$$$" }) : null,
        t.no_codigo === false ? el("span", { class: "selo selo-neutro", title: "Definido em config/topicos_extras.yaml", text: "criado na tela" }) : null,
      ),
      el("div", { class: "cartao-endpoint", text: `GET …/secao_ws/${t.endpoint}` }),
      el("div", { class: "cartao-rodape" },
        selo,
        pendente,
        el("span", { class: "espaco" }),
        excluir,
        el("button", { class: "btn btn-fantasma btn-mini", type: "button", text: "Prompt",
          title: "Ver/editar o prompt", onclick: () => abrirPrompt(t.chave) }),
        el("button", { class: "btn btn-fantasma btn-mini", type: "button", text: "Só este ▶",
          title: "Executar apenas este tópico (usa o contrato/período e o dry-run do formulário)",
          onclick: (ev) => executar([t.chave], ev.currentTarget) }),
      ),
    );
    estado.refs.set(t.chave, { card, input, selo, pendente, excluir });
    atualizarCartao(t.chave);
    return card;
  }

  function atualizarCartao(chave) {
    const r = estado.refs.get(chave);
    if (!r) return;
    const ativo = !!estado.tela.get(chave);
    r.input.checked = ativo;
    r.card.classList.toggle("ativo", ativo);
    r.card.classList.toggle("pendente", estado.salvo.get(chave) !== ativo);
    r.pendente.hidden = estado.salvo.get(chave) === ativo;
    r.excluir.hidden = !estado.prompts.get(chave);

    let classe = "selo selo-neutro", texto = "Sem prompt", titulo = "Crie um prompt para este tópico rodar";
    if (estado.rascunhos.has(chave)) {
      classe = "selo selo-info"; texto = "Rascunho"; titulo = "Prompt editado e não salvo (vale na execução pela tela)";
    } else if (estado.prompts.get(chave)) {
      classe = "selo selo-ok"; texto = "Prompt salvo"; titulo = `${estado.prompts.get(chave).length} caracteres`;
    } else if (ativo) {
      classe = "selo selo-atencao"; titulo = "Ativo, mas sem prompt: voltará ok=false";
    }
    r.selo.className = classe;
    r.selo.textContent = texto;
    r.selo.title = titulo;
  }

  function marcarGrupo(lista, ativo) {
    for (const t of lista) {
      estado.tela.set(t.chave, ativo);
      atualizarCartao(t.chave);
    }
    atualizarResumo();
  }

  function atualizarResumo() {
    const sel = selecionados();
    const total = estado.topicos.length;
    const pend = pendentes();
    $("resumo-ativos").textContent = `${sel.length} de ${total} ativos${pend.size ? " (não salvo)" : ""}`;

    for (const [chave, ref] of estado.refs) {
      if (!chave.startsWith("grupo:")) continue;
      const ativos = ref.lista.filter((t) => estado.tela.get(t.chave)).length;
      ref.cont.textContent = `${ativos} de ${ref.lista.length} ativos`;
    }

    $("barra-pendentes").hidden = pend.size === 0;
    $("txt-pendentes").textContent = `${pend.size} alteraç${pend.size === 1 ? "ão" : "ões"} não salva${pend.size === 1 ? "" : "s"}`;
    atualizarResumoExecucao();
  }

  function descartar() {
    estado.tela = new Map(estado.salvo);
    for (const t of estado.topicos) atualizarCartao(t.chave);
    atualizarResumo();
  }

  async function salvarTopicos() {
    const pend = pendentes();
    if (!pend.size) return;
    const btn = $("btn-salvar");
    btn.disabled = true;
    try {
      const resp = await api("PUT", "/api/topicos", { topicos: Object.fromEntries(pend) });
      aplicarTopicos(resp, false);
      renderTopicos();
      toast("Configuração de tópicos salva.");
    } catch (e) {
      toast(`Não foi possível salvar: ${e.message}`, true);
    } finally {
      btn.disabled = false;
    }
  }

  // ---------------------------------------------------------------------------
  // Editor de prompt
  // ---------------------------------------------------------------------------
  function abrirPrompt(chave) {
    const t = info(chave);
    estado.dlgChave = chave;
    $("dlg-titulo").textContent = `Prompt — ${t ? t.titulo : chave}`;
    $("dlg-arquivo").textContent = `prompts/${chave}.md`;
    const texto = $("dlg-texto");
    texto.maxLength = estado.maxPrompt;
    texto.value = estado.rascunhos.has(chave) ? estado.rascunhos.get(chave) : (estado.prompts.get(chave) || "");
    atualizarStatusPrompt();
    $("dlg-prompt").showModal();
    texto.focus();
  }

  function atualizarStatusPrompt() {
    const chave = estado.dlgChave;
    const valor = $("dlg-texto").value;
    const salvo = estado.prompts.get(chave) || "";
    if (valor === salvo) estado.rascunhos.delete(chave);
    else estado.rascunhos.set(chave, valor);

    const status = $("dlg-status");
    const n = valor.length;
    const rascunho = estado.rascunhos.has(chave);
    status.textContent = `${n.toLocaleString("pt-BR")} / ${estado.maxPrompt.toLocaleString("pt-BR")} caracteres` +
      (rascunho ? " · rascunho não salvo" : (salvo ? " · salvo" : " · sem prompt salvo"));
    status.className = "dialogo-status" + (n > estado.maxPrompt ? " excedido" : rascunho ? " rascunho" : "");
    $("dlg-salvar").disabled = !rascunho || !valor.trim();
    $("dlg-restaurar").disabled = !rascunho;
    atualizarCartao(chave);
  }

  async function salvarPrompt() {
    const chave = estado.dlgChave;
    const valor = $("dlg-texto").value;
    const btn = $("dlg-salvar");
    btn.disabled = true;
    try {
      const resp = await api("PUT", `/api/prompts/${encodeURIComponent(chave)}`, { conteudo: valor });
      estado.prompts.set(chave, resp.conteudo);
      estado.rascunhos.delete(chave);
      $("dlg-texto").value = resp.conteudo || "";
      atualizarStatusPrompt();
      toast(`Prompt de "${chave}" salvo.`);
    } catch (e) {
      toast(`Não foi possível salvar o prompt: ${e.message}`, true);
      atualizarStatusPrompt();
    }
  }

  /** Apaga prompts/<chave>.md (2º clique confirma). O tópico continua na lista, sem prompt. */
  async function excluirPrompt(chave, btn) {
    if (!confirmar(btn, "Confirmar exclusão")) return;
    btn.disabled = true;
    try {
      const resp = await api("DELETE", `/api/prompts/${encodeURIComponent(chave)}`);
      estado.prompts.set(chave, resp.conteudo);
      atualizarCartao(chave);
      atualizarResumoExecucao();
      const t = info(chave);
      toast(`Prompt de "${t ? t.titulo : chave}" excluído.` +
        (estado.tela.get(chave) ? " O tópico está ligado: sem prompt, voltará com erro ao executar." : ""));
    } catch (e) {
      toast(`Não foi possível excluir o prompt: ${e.message}`, true);
    } finally {
      btn.disabled = false;
    }
  }

  function restaurarPrompt() {
    $("dlg-texto").value = estado.prompts.get(estado.dlgChave) || "";
    atualizarStatusPrompt();
  }

  // ---------------------------------------------------------------------------
  // Markdown → DOM (preview do "Novo Prompt"). Só nós de elemento/texto: nunca HTML cru.
  // Cobre títulos, parágrafos, **negrito**, *itálico*, ~~riscado~~, `código`, blocos ```,
  // listas (aninhadas por recuo), citações, linha horizontal, tabelas (GFM) e links http(s).
  // ---------------------------------------------------------------------------
  const MD_INLINE = [
    { re: /`([^`]+)`/, tag: "code", literal: true },
    { re: /\*\*(.+?)\*\*|__(.+?)__/, tag: "strong" },
    { re: /~~(.+?)~~/, tag: "del" },
    { re: /\*(?!\s)(.+?)\*|(?<!\w)_(?!\s)(.+?)_(?!\w)/, tag: "em" },
    { re: /\[([^\]]+)\]\(([^)\s]+)\)/, tag: "a" },
  ];

  function mdInline(texto) {
    const nos = [];
    let resto = texto;
    while (resto) {
      let melhor = null;
      for (const regra of MD_INLINE) {
        const m = regra.re.exec(resto);
        if (m && (!melhor || m.index < melhor.m.index)) melhor = { regra, m };
      }
      if (!melhor) { nos.push(resto); break; }
      const { regra, m } = melhor;
      if (m.index) nos.push(resto.slice(0, m.index));
      const miolo = m[1] ?? m[2] ?? "";
      if (regra.literal) nos.push(el(regra.tag, { text: miolo }));
      else if (regra.tag === "a") {
        nos.push(/^https?:\/\//i.test(m[2])
          ? el("a", { href: m[2], target: "_blank", rel: "noopener noreferrer" }, mdInline(m[1]))
          : el("span", {}, mdInline(m[1])));
      } else nos.push(el(regra.tag, {}, mdInline(miolo)));
      resto = resto.slice(m.index + m[0].length);
    }
    return nos;
  }

  const MD_ITEM = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
  const MD_SEP_TABELA = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/;
  const recuo = (linha) => linha.match(/^\s*/)[0].replace(/\t/g, "    ").length;
  const celulas = (linha) => linha.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());

  /** Lista a partir de linhas[i] (mesmo recuo); devolve [elemento, próxima linha]. */
  function mdLista(linhas, i) {
    const base = recuo(linhas[i]);
    const ordenada = /\d/.test(MD_ITEM.exec(linhas[i])[2]);
    const lista = el(ordenada ? "ol" : "ul");
    let li = null;
    while (i < linhas.length) {
      const linha = linhas[i];
      if (!linha.trim()) {
        const prox = linhas[i + 1];
        if (prox !== undefined && MD_ITEM.test(prox) && recuo(prox) >= base) { i += 1; continue; }
        break;
      }
      const m = MD_ITEM.exec(linha);
      const r = recuo(linha);
      if (m && r === base && /\d/.test(m[2]) !== ordenada) break; // troca de tipo = lista nova
      if (m && r === base) {
        li = el("li", {}, mdInline(m[3]));
        lista.append(li);
        i += 1;
      } else if (m && r > base && li) {
        const [sub, j] = mdLista(linhas, i);
        li.append(sub);
        i = j;
      } else if (!m && r > base && li) {
        li.append(" ", ...mdInline(linha.trim()));
        i += 1;
      } else break;
    }
    return [lista, i];
  }

  function mdBlocos(texto) {
    const linhas = texto.replace(/\r\n?/g, "\n").split("\n");
    const frag = document.createDocumentFragment();
    let i = 0;
    const inicioDeBloco = (l, prox) => /^\s*(```|#{1,6}\s|>)/.test(l) || MD_ITEM.test(l) ||
      /^\s*([-*_])(\s*\1){2,}\s*$/.test(l) || (l.includes("|") && prox !== undefined && MD_SEP_TABELA.test(prox));

    while (i < linhas.length) {
      const linha = linhas[i];
      if (!linha.trim()) { i += 1; continue; }

      if (/^\s*```/.test(linha)) {
        const codigo = [];
        i += 1;
        while (i < linhas.length && !/^\s*```/.test(linhas[i])) codigo.push(linhas[i++]);
        i += 1;
        frag.append(el("pre", {}, el("code", { text: codigo.join("\n") })));
        continue;
      }
      const titulo = /^\s*(#{1,6})\s+(.*?)\s*#*\s*$/.exec(linha);
      if (titulo) { frag.append(el(`h${titulo[1].length}`, {}, mdInline(titulo[2]))); i += 1; continue; }
      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(linha)) { frag.append(el("hr")); i += 1; continue; }
      if (/^\s*>/.test(linha)) {
        const citacao = [];
        while (i < linhas.length && /^\s*>/.test(linhas[i])) citacao.push(linhas[i++].replace(/^\s*>\s?/, ""));
        frag.append(el("blockquote", {}, mdBlocos(citacao.join("\n"))));
        continue;
      }
      if (linha.includes("|") && linhas[i + 1] !== undefined && MD_SEP_TABELA.test(linhas[i + 1])) {
        const alinh = celulas(linhas[i + 1]).map((c) => (c.endsWith(":") ? (c.startsWith(":") ? "center" : "right") : null));
        const classe = (k) => (alinh[k] ? `al-${alinh[k]}` : null);
        const thead = el("thead", {}, el("tr", {}, celulas(linha).map((c, k) => el("th", { class: classe(k) }, mdInline(c)))));
        const tbody = el("tbody");
        i += 2;
        while (i < linhas.length && linhas[i].trim() && linhas[i].includes("|")) {
          tbody.append(el("tr", {}, celulas(linhas[i++]).map((c, k) => el("td", { class: classe(k) }, mdInline(c)))));
        }
        frag.append(el("div", { class: "md-tabela" }, el("table", {}, thead, tbody)));
        continue;
      }
      if (MD_ITEM.test(linha)) { const [lista, j] = mdLista(linhas, i); frag.append(lista); i = j; continue; }

      const paragrafo = [];
      while (i < linhas.length && linhas[i].trim() && !(paragrafo.length && inicioDeBloco(linhas[i], linhas[i + 1]))) {
        paragrafo.push(linhas[i++].trim());
      }
      const p = el("p");
      paragrafo.forEach((l, k) => { if (k) p.append(el("br")); p.append(...mdInline(l)); });
      frag.append(p);
    }
    return frag;
  }

  // ---------------------------------------------------------------------------
  // Novo Prompt (botão "+ Novo tópico"): título + tópico do relatório + markdown com preview.
  // Salvar grava prompts/<chave>.md do tópico escolhido (PUT /api/prompts/{chave}).
  // ---------------------------------------------------------------------------
  const np = { topicoId: null, aberto: false, ativo: -1, opcoes: [], salvando: false, ignorarCancel: false, quadro: 0 };

  function itemRelatorio(id) {
    for (const g of window.TOPICOS_RELATORIO || []) for (const it of g.itens) if (it.id === id) return it;
    return null;
  }

  function construirListaRelatorio() {
    const ul = $("np-lista");
    limpar(ul);
    np.opcoes = [];
    (window.TOPICOS_RELATORIO || []).forEach((g, gi) => {
      if (gi) ul.append(el("li", { class: "np-divisor", role: "separator" }));
      const idGrupo = `np-grupo-${gi}`;
      const opcoes = g.itens.map((it) => {
        const disponivel = !!(it.chave && info(it.chave));
        const li = el("li", {
          id: `np-op-${it.id.replace(/\W/g, "_")}`, class: "np-opcao", role: "option",
          "aria-selected": "false", "aria-disabled": disponivel ? null : "true",
          title: disponivel ? `Grava prompts/${it.chave}.md` : "Este tópico ainda não existe no sistema",
        }, el("span", { text: it.label }), disponivel ? null : el("span", { class: "np-embreve", text: "em breve" }));
        const indice = np.opcoes.length;
        np.opcoes.push({ it, li, disponivel });
        li.addEventListener("mousedown", (ev) => ev.preventDefault()); // foco fica no combobox
        li.addEventListener("click", () => { if (disponivel) { selecionarTopicoRelatorio(it.id); fecharListaRelatorio(); } });
        li.addEventListener("mousemove", () => { if (disponivel && np.ativo !== indice) ativarOpcao(indice, false); });
        return li;
      });
      ul.append(el("li", { role: "presentation" },
        el("div", { id: idGrupo, class: "np-grupo", text: g.grupo, "aria-hidden": "true" }),
        el("ul", { role: "group", "aria-labelledby": idGrupo }, opcoes),
      ));
    });
  }

  function atualizarIndicadorLista() {
    const ul = $("np-lista");
    document.querySelector(".np-mais").hidden = ul.scrollTop + ul.clientHeight >= ul.scrollHeight - 4;
  }

  function ativarOpcao(indice, rolar = true) {
    np.opcoes.forEach((o, k) => o.li.classList.toggle("ativo", k === indice));
    np.ativo = indice;
    const o = np.opcoes[indice];
    if (o) {
      $("np-topico").setAttribute("aria-activedescendant", o.li.id);
      if (rolar) o.li.scrollIntoView({ block: "nearest" });
    } else $("np-topico").removeAttribute("aria-activedescendant");
    atualizarIndicadorLista();
  }

  function moverOpcao(passo) {
    const n = np.opcoes.length;
    let k = np.ativo;
    for (let tentativas = 0; tentativas < n; tentativas++) {
      k = k < 0 ? (passo > 0 ? 0 : n - 1) : (k + passo + n) % n;
      if (np.opcoes[k].disponivel) { ativarOpcao(k); return; }
    }
  }

  function extremoOpcao(fim) {
    const lista = fim ? [...np.opcoes.keys()].reverse() : [...np.opcoes.keys()];
    const k = lista.find((i) => np.opcoes[i].disponivel);
    if (k !== undefined) ativarOpcao(k);
  }

  function abrirListaRelatorio() {
    if (np.aberto) return;
    np.aberto = true;
    document.querySelector(".np-popup").hidden = false;
    $("np-topico").setAttribute("aria-expanded", "true");
    const sel = np.opcoes.findIndex((o) => o.it.id === np.topicoId);
    if (sel >= 0) ativarOpcao(sel); else { np.ativo = -1; moverOpcao(1); }
    atualizarIndicadorLista();
  }

  function fecharListaRelatorio() {
    if (!np.aberto) return;
    np.aberto = false;
    document.querySelector(".np-popup").hidden = true;
    $("np-topico").setAttribute("aria-expanded", "false");
    $("np-topico").removeAttribute("aria-activedescendant");
  }

  function selecionarTopicoRelatorio(id) {
    np.topicoId = id;
    const it = itemRelatorio(id);
    for (const o of np.opcoes) o.li.setAttribute("aria-selected", String(o.it.id === id));
    const texto = $("np-topico-texto");
    texto.textContent = it ? it.label : "Selecione um tópico";
    texto.classList.toggle("np-placeholder", !it);

    // Salvar substitui o prompt do tópico: avisa se já existe prompt salvo ou rascunho no editor.
    const aviso = $("np-aviso");
    const partes = [];
    if (it && it.chave) {
      const salvo = estado.prompts.get(it.chave);
      if (salvo) partes.push(`Este tópico já tem um prompt salvo (${salvo.length.toLocaleString("pt-BR")} caracteres): salvar vai substituí-lo.`);
      if (estado.rascunhos.has(it.chave)) partes.push("O rascunho não salvo deste tópico no editor de prompt será descartado.");
    }
    aviso.textContent = partes.join(" ");
    aviso.hidden = !partes.length;
    resetarConfirmacao($("np-salvar"));
    atualizarSalvarNovoPrompt();
  }

  function onTeclaTopicoRelatorio(ev) {
    const teclas = {
      ArrowDown: () => (np.aberto ? moverOpcao(1) : abrirListaRelatorio()),
      ArrowUp: () => (np.aberto ? moverOpcao(-1) : abrirListaRelatorio()),
      Home: () => np.aberto && extremoOpcao(false),
      End: () => np.aberto && extremoOpcao(true),
      Enter: () => {
        if (!np.aberto) { abrirListaRelatorio(); return; }
        const o = np.opcoes[np.ativo];
        if (o && o.disponivel) selecionarTopicoRelatorio(o.it.id);
        fecharListaRelatorio();
      },
      Escape: () => {
        if (!np.aberto) return false;
        fecharListaRelatorio();
        np.ignorarCancel = true; // o Esc fecha só a lista, não o modal
        setTimeout(() => { np.ignorarCancel = false; }, 0);
        return true;
      },
    };
    teclas[" "] = teclas.Enter;
    if (ev.key === "Tab") { fecharListaRelatorio(); return; }
    const acao = teclas[ev.key];
    if (!acao) return;
    if (acao() === false) return;
    ev.preventDefault();
    if (ev.key === "Escape") ev.stopPropagation();
  }

  function renderPreviewNovoPrompt() {
    cancelAnimationFrame(np.quadro);
    np.quadro = requestAnimationFrame(() => {
      const caixa = $("np-preview");
      const texto = $("np-markdown").value;
      limpar(caixa);
      if (!texto.trim()) caixa.append(el("p", { class: "np-vazio", text: "O preview aparecerá aqui..." }));
      else caixa.append(mdBlocos(texto));
    });
  }

  function atualizarSalvarNovoPrompt() {
    const completo = $("np-titulo").value.trim() && np.topicoId && $("np-markdown").value.trim();
    $("np-salvar").disabled = np.salvando || !completo;
  }

  function erroNovoPrompt(msg) {
    const p = $("np-erro");
    p.textContent = msg || "";
    p.hidden = !msg;
  }

  function abrirNovoPrompt() {
    construirListaRelatorio();
    $("np-markdown").maxLength = estado.maxPrompt;
    resetarNovoPrompt();
    $("dlg-novo-prompt").showModal();
    $("np-titulo").focus();
  }

  function resetarNovoPrompt() {
    $("form-novo-prompt").reset();
    fecharListaRelatorio();
    selecionarTopicoRelatorio(null);
    erroNovoPrompt("");
    renderPreviewNovoPrompt();
  }

  /** Grava o prompt do tópico escolhido. Rejeita (exceção) em caso de erro. */
  async function onSaveNovoPrompt({ titulo, topicoId, topicoLabel, conteudoMarkdown }) {
    const it = itemRelatorio(topicoId);
    if (!it || !it.chave || !info(it.chave)) throw new Error("Este tópico ainda não existe no sistema.");
    const resp = await api("PUT", `/api/prompts/${encodeURIComponent(it.chave)}`, { conteudo: conteudoMarkdown });
    estado.prompts.set(it.chave, resp.conteudo);
    estado.rascunhos.delete(it.chave);
    atualizarCartao(it.chave);
    atualizarResumoExecucao();
    toast(`Prompt "${titulo}" salvo em ${topicoLabel}.`);
  }

  async function salvarNovoPrompt(ev) {
    ev.preventDefault();
    const btn = $("np-salvar");
    if (btn.disabled) return;
    erroNovoPrompt("");
    if (!$("np-aviso").hidden && !confirmar(btn, "Confirmar: substituir")) return;

    const it = itemRelatorio(np.topicoId);
    np.salvando = true;
    btn.classList.add("salvando");
    btn.textContent = "Salvando…";
    atualizarSalvarNovoPrompt();
    try {
      await onSaveNovoPrompt({
        titulo: $("np-titulo").value.trim(),
        topicoId: np.topicoId,
        topicoLabel: it ? it.label : "",
        conteudoMarkdown: $("np-markdown").value,
      });
      $("dlg-novo-prompt").close();
    } catch (e) {
      erroNovoPrompt(`Não foi possível salvar: ${e.message}`);
    } finally {
      np.salvando = false;
      btn.classList.remove("salvando");
      btn.textContent = "Salvar";
      atualizarSalvarNovoPrompt();
    }
  }

  function ligarNovoPrompt() {
    const dlg = $("dlg-novo-prompt");
    $("btn-novo-relatorio").addEventListener("click", abrirNovoPrompt);
    $("form-novo-prompt").addEventListener("submit", salvarNovoPrompt);
    $("np-fechar").addEventListener("click", () => dlg.close());
    $("np-cancelar").addEventListener("click", () => dlg.close());
    dlg.addEventListener("close", resetarNovoPrompt);
    dlg.addEventListener("cancel", (ev) => {
      if (np.ignorarCancel || np.aberto || np.salvando) { ev.preventDefault(); fecharListaRelatorio(); }
    });
    // Clique no overlay (fora da caixa): o alvo é o próprio <dialog>, que não tem padding.
    dlg.addEventListener("click", (ev) => { if (ev.target === dlg && !np.salvando) dlg.close(); });

    $("np-topico").addEventListener("click", () => (np.aberto ? fecharListaRelatorio() : abrirListaRelatorio()));
    $("np-topico").addEventListener("keydown", onTeclaTopicoRelatorio);
    $("np-lista").addEventListener("scroll", atualizarIndicadorLista);
    document.addEventListener("mousedown", (ev) => {
      if (np.aberto && !document.querySelector(".np-select").contains(ev.target)) fecharListaRelatorio();
    });

    $("np-titulo").addEventListener("input", atualizarSalvarNovoPrompt);
    $("np-markdown").addEventListener("input", () => {
      atualizarSalvarNovoPrompt();
      renderPreviewNovoPrompt();
    });
  }

  // ---------------------------------------------------------------------------
  // Executar
  // ---------------------------------------------------------------------------
  const CHAVE_FORM = "supra-ia:exec";   // sessionStorage: só contrato/período (nada sensível)

  function restaurarFormulario() {
    try {
      const f = JSON.parse(sessionStorage.getItem(CHAVE_FORM) || "{}");
      if (f.contrato) $("exec-contrato").value = f.contrato;
      if (f.inicio) $("exec-inicio").value = f.inicio;
      if (f.fim) $("exec-fim").value = f.fim;
    } catch { /* ignora */ }
  }

  function guardarFormulario() {
    try {
      sessionStorage.setItem(CHAVE_FORM, JSON.stringify({
        contrato: $("exec-contrato").value, inicio: $("exec-inicio").value, fim: $("exec-fim").value,
      }));
    } catch { /* ignora */ }
  }

  function atualizarResumoExecucao() {
    const alvo = selecionados();
    const caros = alvo.filter((c) => (info(c) || {}).custo === "alto").length;
    const semPrompt = alvo.filter((c) => !estado.rascunhos.get(c) && !estado.prompts.get(c)).length;
    const dry = $("exec-dry").checked;
    const p = $("exec-resumo");
    limpar(p);
    if (!alvo.length) { p.append("Nenhum tópico ligado na tela."); return; }
    p.append("Serão executados ", el("strong", { text: String(alvo.length) }), ` tópico${alvo.length > 1 ? "s" : ""}`);
    if (dry) p.append(" em dry-run (sem custo).");
    else p.append(caros ? `, ${caros} com gpt-4o (visão, custo alto).` : ".");
    if (semPrompt) p.append(` ${semPrompt} sem prompt voltará${semPrompt > 1 ? "ão" : ""} com erro.`);
  }

  const timersConfirmacao = new WeakMap();

  /**
   * Execução REAL custa dinheiro: exige um segundo clique no mesmo botão em até 6 s
   * (sem diálogos do navegador). Devolve true quando já está confirmado.
   */
  function confirmar(btn, texto) {
    if (btn.dataset.confirmar === "1") { resetarConfirmacao(btn); return true; }
    btn.dataset.confirmar = "1";
    btn.dataset.textoOriginal = btn.textContent;
    btn.classList.add("btn-perigo");
    btn.textContent = texto;
    clearTimeout(timersConfirmacao.get(btn));
    timersConfirmacao.set(btn, setTimeout(() => resetarConfirmacao(btn), 6000));
    return false;
  }

  function resetarConfirmacao(btn) {
    if (btn.dataset.confirmar !== "1") return;
    clearTimeout(timersConfirmacao.get(btn));
    btn.classList.remove("btn-perigo");
    btn.textContent = btn.dataset.textoOriginal;
    delete btn.dataset.confirmar;
    delete btn.dataset.textoOriginal;
  }

  function resetarBotaoExecutar() { resetarConfirmacao($("btn-executar")); }

  function erroExec(msg) {
    const p = $("exec-erro");
    p.textContent = msg || "";
    p.hidden = !msg;
  }

  async function executar(alvo, btn) {
    if (estado.executando) return;
    erroExec("");
    const contrato = $("exec-contrato").value.trim();
    const inicio = $("exec-inicio").value;
    const fim = $("exec-fim").value;
    const dry = $("exec-dry").checked;

    if (!contrato || !inicio || !fim) { erroExec("Preencha contrato, início e fim do período."); return; }
    if (inicio > fim) { erroExec("O início do período é posterior ao fim."); return; }
    if (!alvo.length) { erroExec("Ligue ao menos um tópico na tela."); return; }

    const texto = alvo.length === 1 ? "Confirmar (real) ▶" : `Confirmar execução real (${alvo.length}) ▶`;
    if (!dry && !confirmar(btn, texto)) return;
    guardarFormulario();

    const prompts = alvo
      .filter((c) => estado.rascunhos.has(c) && estado.rascunhos.get(c).trim())
      .map((c) => ({ topico: c, conteudo: estado.rascunhos.get(c) }));
    const corpo = { contrato, periodo_inicio: inicio, periodo_fim: fim, dry_run: dry, topicos: alvo, prompts };

    estado.executando = true;
    $("btn-executar").disabled = true;
    const inicioMs = Date.now();
    const status = el("p", { class: "carregando" });
    const tick = () => {
      const s = Math.round((Date.now() - inicioMs) / 1000);
      status.textContent = `Executando ${alvo.length} tópico${alvo.length > 1 ? "s" : ""}${dry ? " (dry-run)" : ""}… ${s} s`;
    };
    tick();
    const relogio = setInterval(tick, 1000);
    limpar($("resultado"));
    $("resultado").append(status);
    $("btn-copiar").hidden = true;
    iniciarPollingLogs();

    try {
      const resp = await api("POST", "/api/executar", corpo);
      estado.ultimaResposta = resp;
      estado.ultimaExecucao = resp.execucao_id;
      $("logs-execucao").disabled = false;
      renderResultado(resp);
    } catch (e) {
      limpar($("resultado"));
      $("resultado").append(el("p", { class: "msg-erro", text: `A execução falhou: ${e.message}` }));
    } finally {
      clearInterval(relogio);
      estado.executando = false;
      $("btn-executar").disabled = false;
      pararPollingLogs();
      carregarLogs(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Resultado
  // ---------------------------------------------------------------------------
  function semAcento(s) { return String(s).normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().trim(); }

  /** Classifica um resultado em {rotulo, classe} para o selo e a borda. */
  function classificar(t) {
    if (!t.ok) return { rotulo: "Erro", classe: "erro" };
    const c = t.conteudo;
    if (c && typeof c === "object" && !Array.isArray(c)) {
      if (c.dry_run) return { rotulo: "Dry-run", classe: "info" };
      if (typeof c.conforme === "string") {
        const v = semAcento(c.conforme);
        if (v === "conforme") return { rotulo: c.conforme, classe: "ok" };
        if (v === "atencao") return { rotulo: c.conforme, classe: "atencao" };
        if (v === "nao conforme") return { rotulo: c.conforme, classe: "nao-conforme" };
        return { rotulo: c.conforme, classe: "neutro" };
      }
    }
    return { rotulo: "Sem classificação", classe: "neutro" };
  }

  const CLASSE_SELO = { ok: "selo-ok", atencao: "selo-atencao", "nao-conforme": "selo-erro", erro: "selo-erro", info: "selo-info", neutro: "selo-neutro" };

  /** JSON legível, encurtando textos enormes (ex.: imagens em base64). */
  function jsonLegivel(valor) {
    return JSON.stringify(valor, (_k, v) => {
      if (typeof v === "string" && v.length > 3000) {
        return `${v.slice(0, 200)}… [${v.length.toLocaleString("pt-BR")} caracteres omitidos da exibição]`;
      }
      return v;
    }, 2);
  }

  function blocoJson(titulo, valor) {
    const texto = typeof valor === "string" ? valor : jsonLegivel(valor);
    return el("details", {}, el("summary", { text: titulo }), el("pre", { class: "json", text: texto }));
  }

  function renderResultado(resp) {
    const raiz = $("resultado");
    limpar(raiz);

    const ordem = new Map(estado.topicos.map((t, i) => [t.chave, i]));
    const itens = [...resp.topicos].sort((a, b) => (ordem.get(a.topico) ?? 999) - (ordem.get(b.topico) ?? 999));

    const contagem = new Map();
    for (const t of itens) {
      const { rotulo, classe } = classificar(t);
      const k = `${classe}|${rotulo}`;
      contagem.set(k, (contagem.get(k) || 0) + 1);
    }

    raiz.append(el("div", { class: "res-cab" },
      el("span", {}, "Contrato ", el("strong", { text: resp.contrato })),
      el("span", {}, "Período ", el("strong", { text: `${resp.periodo_inicio} a ${resp.periodo_fim}` })),
      el("span", {}, el("strong", { text: String(itens.length) }), ` tópico${itens.length === 1 ? "" : "s"}`),
      el("span", {}, el("strong", { text: `${(resp.duracao_ms / 1000).toLocaleString("pt-BR", { maximumFractionDigits: 1 })} s` })),
      resp.dry_run ? el("span", { class: "selo selo-info", text: "DRY-RUN — OpenAI não chamada" }) : null,
      el("span", { class: "res-chave", title: "Id da execução (filtra os logs)", text: resp.execucao_id }),
      el("div", { class: "res-contagem" },
        [...contagem].map(([k, n]) => {
          const [classe, rotulo] = k.split("|");
          return el("span", { class: `selo ${CLASSE_SELO[classe]}`, text: `${rotulo}: ${n}` });
        }),
      ),
    ));

    raiz.append(el("div", { class: "res-lista" }, itens.map(itemResultado)));
    if (!itens.length) raiz.append(el("p", { class: "vazio", text: "Nenhum tópico executado." }));
    $("btn-copiar").hidden = false;
  }

  function itemResultado(t) {
    const { rotulo, classe } = classificar(t);
    const cfg = info(t.topico);
    const item = el("article", { class: `res-item st-${classe}` },
      el("div", { class: "res-item-cab" },
        el("h4", { text: cfg ? cfg.titulo : t.topico }),
        el("span", { class: "res-chave", text: t.topico }),
        el("span", { class: `selo ${CLASSE_SELO[classe]}`, text: rotulo }),
      ),
    );

    if (!t.ok) {
      item.append(el("p", { class: "res-erro", text: t.erro || "Erro sem mensagem." }));
      return item;
    }

    const c = t.conteudo;
    if (c && typeof c === "object" && !Array.isArray(c) && c.dry_run) {
      if (!c.chamadas_llm.length) {
        item.append(el("p", { class: "res-chamada", text: c.observacao || "Sem chamada à LLM." }));
        if (c.resultado !== undefined) item.append(blocoJson("Resultado sem LLM", c.resultado));
      }
      for (const ch of c.chamadas_llm) {
        item.append(el("p", { class: "res-chamada",
          text: `${ch.modelo} · ~${ch.tokens_texto_estimados.toLocaleString("pt-BR")} tokens de entrada (texto) · ` +
                `${ch.caracteres_texto.toLocaleString("pt-BR")} caracteres · max_tokens ${ch.max_tokens}` +
                (ch.imagens ? ` · ${ch.imagens} imagem(ns)` : "") }));
        // Cada mensagem (system, user…) numa coluna com rolagem própria, lado a lado.
        const grade = el("div", { class: "msgs-grade" });
        for (const m of ch.mensagens) {
          const texto = typeof m.conteudo === "string" ? m.conteudo : jsonLegivel(m.conteudo);
          grade.append(el("div", { class: "msg" },
            el("div", { class: "msg-papel", text: m.role }),
            el("pre", { class: "json", text: texto }),
          ));
        }
        item.append(el("details", { open: true }, el("summary", { text: "Mensagens que seriam enviadas" }), grade));
      }
      return item;
    }

    if (c && typeof c === "object" && !Array.isArray(c)) {
      if (c.motivo) item.append(el("p", { class: "res-motivo", text: String(c.motivo) }));
      const { infos, ...resto } = c;
      item.append(blocoJson("Resposta completa (JSON)", resto));
      if (infos !== undefined) item.append(blocoJson("Dados enviados à LLM (infos)", infos));
    } else {
      item.append(blocoJson("Resposta da LLM (texto, não era JSON)", c ?? ""));
    }
    return item;
  }

  async function copiarJson() {
    if (!estado.ultimaResposta) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(estado.ultimaResposta, null, 2));
      toast("JSON copiado.");
    } catch {
      toast("Não foi possível copiar (permissão do navegador).", true);
    }
  }

  // ---------------------------------------------------------------------------
  // Logs
  // ---------------------------------------------------------------------------
  function linhaLog(l) {
    const hora = new Date(l.hora);
    const hh = isNaN(hora) ? "" : hora.toLocaleTimeString("pt-BR", { hour12: false });
    const linha = el("div", { class: `log-linha log-${l.nivel}` },
      el("span", { class: "log-hora", text: hh }),
      el("span", { class: "log-nivel", text: l.nivel }),
      el("span", { class: "log-origem", text: l.origem }),
      el("span", { class: "log-msg", text: l.mensagem }),
    );
    if (l.excecao) linha.append(el("span", { class: "log-exc", text: `↳ ${l.excecao}` }));
    return linha;
  }

  async function carregarLogs(reiniciar) {
    const caixa = $("logs");
    const params = new URLSearchParams({ nivel: $("logs-nivel").value, limite: "500" });
    const soExecucao = $("logs-execucao").checked && estado.ultimaExecucao;
    if (soExecucao) params.set("execucao", estado.ultimaExecucao);
    if (!reiniciar && !soExecucao) params.set("apos", String(estado.logSeq));

    let resp;
    try {
      resp = await api("GET", `/api/logs?${params}`);
    } catch {
      return; // logs são auxiliares: falha silenciosa
    }
    const noFim = caixa.scrollTop + caixa.clientHeight >= caixa.scrollHeight - 20;
    if (reiniciar || soExecucao) limpar(caixa);
    const vazio = caixa.querySelector(".vazio");
    if (vazio && resp.linhas.length) vazio.remove();
    for (const l of resp.linhas) {
      caixa.append(linhaLog(l));
      estado.logSeq = Math.max(estado.logSeq, l.seq);
    }
    if (!caixa.children.length) caixa.append(el("p", { class: "vazio", text: "Sem linhas." }));
    while (caixa.children.length > 1500) caixa.firstChild.remove();
    if (noFim || reiniciar) caixa.scrollTop = caixa.scrollHeight;
  }

  function iniciarPollingLogs() {
    pararPollingLogs();
    $("logs-execucao").checked = false;
    estado.logTimer = setInterval(() => carregarLogs(false), 1500);
  }

  function pararPollingLogs() {
    clearInterval(estado.logTimer);
    estado.logTimer = null;
  }

  // ---------------------------------------------------------------------------
  // Abas (só layout: mostram/escondem painéis, não mudam dados nem chamam a API)
  // ---------------------------------------------------------------------------
  const ABAS = ["topicos", "resultado", "logs"];

  function abaAtiva() {
    return ABAS.find((a) => !$(`painel-${a}`).hidden) || "topicos";
  }

  function mostrarAba(nome, focar = false) {
    if (!ABAS.includes(nome)) nome = "topicos";
    for (const a of ABAS) {
      const ativa = a === nome;
      const aba = $(`aba-${a}`);
      aba.setAttribute("aria-selected", String(ativa));
      aba.tabIndex = ativa ? 0 : -1;
      $(`painel-${a}`).hidden = !ativa;
    }
    if (nome === "resultado") $("aba-resultado-novo").hidden = true;
    if (nome === "logs") { const caixa = $("logs"); caixa.scrollTop = caixa.scrollHeight; }
    if (focar) $(`aba-${nome}`).focus();
    // Hash na URL: F5 volta na mesma aba (sem rolar a página).
    history.replaceState(null, "", nome === "topicos" ? location.pathname + location.search : `#${nome}`);
  }

  function ligarAbas() {
    for (const a of ABAS) {
      const aba = $(`aba-${a}`);
      aba.addEventListener("click", () => mostrarAba(a));
      aba.addEventListener("keydown", (ev) => {
        const i = ABAS.indexOf(a);
        let alvo = null;
        if (ev.key === "ArrowRight") alvo = ABAS[(i + 1) % ABAS.length];
        else if (ev.key === "ArrowLeft") alvo = ABAS[(i - 1 + ABAS.length) % ABAS.length];
        else if (ev.key === "Home") alvo = ABAS[0];
        else if (ev.key === "End") alvo = ABAS[ABAS.length - 1];
        if (alvo) { ev.preventDefault(); mostrarAba(alvo, true); }
      });
    }
    // Uma execução começando leva à aba Resultado; se o resultado chegar com outra aba aberta,
    // a aba Resultado ganha um marcador de "novo".
    new MutationObserver(() => {
      if ($("resultado").querySelector(".carregando")) mostrarAba("resultado");
      else if (abaAtiva() !== "resultado") $("aba-resultado-novo").hidden = false;
    }).observe($("resultado"), { childList: true });
    mostrarAba(location.hash.slice(1));
  }

  // ---------------------------------------------------------------------------
  // Eventos
  // ---------------------------------------------------------------------------
  function ligarEventos() {
    $("form-login").addEventListener("submit", onLogin);
    $("btn-sair").addEventListener("click", onSair);
    $("btn-descartar").addEventListener("click", descartar);
    $("btn-salvar").addEventListener("click", salvarTopicos);

    $("form-exec").addEventListener("submit", (ev) => { ev.preventDefault(); executar(selecionados(), $("btn-executar")); });
    $("exec-dry").addEventListener("change", () => { resetarBotaoExecutar(); atualizarResumoExecucao(); });
    for (const id of ["exec-contrato", "exec-inicio", "exec-fim"]) $(id).addEventListener("input", resetarBotaoExecutar);

    $("btn-copiar").addEventListener("click", copiarJson);
    $("btn-logs-atualizar").addEventListener("click", () => carregarLogs(true));
    $("btn-logs-limpar").addEventListener("click", () => { limpar($("logs")); $("logs").append(el("p", { class: "vazio", text: "Sem linhas." })); });
    $("logs-nivel").addEventListener("change", () => carregarLogs(true));
    $("logs-execucao").addEventListener("change", () => carregarLogs(true));

    $("dlg-texto").addEventListener("input", atualizarStatusPrompt);
    $("dlg-salvar").addEventListener("click", salvarPrompt);
    $("dlg-restaurar").addEventListener("click", restaurarPrompt);
    $("dlg-fechar").addEventListener("click", () => $("dlg-prompt").close());
    $("dlg-prompt").addEventListener("close", () => { atualizarResumoExecucao(); });

    window.addEventListener("beforeunload", (ev) => {
      if (estado.usuario && (pendentes().size || estado.rascunhos.size)) { ev.preventDefault(); ev.returnValue = ""; }
    });
  }

  async function iniciar() {
    ligarEventos();
    ligarAbas();
    ligarNovoPrompt();
    restaurarFormulario();
    try {
      const sessao = await api("GET", "/api/auth/me");
      await entrou(sessao);
    } catch (e) {
      mostrarLogin(e.status === 401 ? "" : e.message);
    }
  }

  document.addEventListener("DOMContentLoaded", iniciar);
})();
