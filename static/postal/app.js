(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const userId = JSON.parse($("user-id")?.textContent || "null");
  const apiIdentity = JSON.parse($("api-identity").textContent);
  let skills = JSON.parse($("assistant-skills")?.textContent || "{}");
  const columnLabels = JSON.parse($("column-labels").textContent) || {};
  const labelWords = JSON.parse($("label-words").textContent) || {};
  function columnLabel(column) {
    if (Object.hasOwn(columnLabels, column)) return columnLabels[column];
    const words = column.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/_/g, " ").split(/\s+/).filter(Boolean);
    const label = words.map(word => Object.hasOwn(labelWords, word.toLowerCase()) ? labelWords[word.toLowerCase()] : word).join(" ");
    return label.charAt(0).toUpperCase() + label.slice(1);
  }
  const csrf = document.querySelector('[name="csrfmiddlewaretoken"]')?.value;
  const terminal = new Set(["ok", "no_matches", "empty_table", "error", "cancelled"]);
  let view = "chat", db, conversations = [], conversation = null, active = null, epoch = 0, catalog = [], busy = false;
  const charts = new Set();
  const controllers = new Set();
  let toastTimer;
  let sessionInvalid = false;
  function invalidateSession() {
    if (sessionInvalid) return;
    sessionInvalid = true;
    stopActive(false);
    conversation = null; conversations = []; catalog = [];
    if (db) { db.close(); db = null; }
    charts.forEach(chart => chart.destroy()); charts.clear();
    ["messages", "history-list", "tracking-results", "dashboard-results", "catalog-list"].forEach(id => $(id).replaceChildren());
    $("question").value = ""; $("tracking-code").value = ""; $("history-search").value = "";
    document.querySelectorAll("input, textarea, select, button").forEach(node => { node.disabled = true; });
    window.location.replace("/accounts/login/");
  }
  function el(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (className) node.className = className;
    return node;
  }
  function button(label, fn, className = "text-button") {
    const node = el("button", label, className);
    node.type = "button";
    node.addEventListener("click", fn);
    return node;
  }
  function icon(name) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    for (const [key, value] of Object.entries({class:"icon", width:"20", height:"20", viewBox:"0 0 24 24", fill:"none", stroke:"currentColor", "stroke-width":"1.6", "stroke-linecap":"round", "stroke-linejoin":"round", "aria-hidden":"true"})) node.setAttribute(key, value);
    // Keep new action icons visible when the page still has an older SVG sprite.
    const actionPaths = {
      edit: "m15 5 4 4M4 20l4-1L20 7a2.8 2.8 0 0 0-4-4L4 15l-1 6Z",
      copy: "M10 8h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-8a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2ZM16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3",
      download: "M12 3v12m-5-5 5 5 5-5M4 16v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4",
      check: "m5 12 4 4L19 6"
    };
    if (actionPaths[name]) {
      const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
      path.setAttribute("d", actionPaths[name]); node.append(path);
      return node;
    }
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", "#icon-" + name); node.append(use);
    return node;
  }
  function closeSidebar() {
    $("sidebar").classList.remove("open");
    $("sidebar-backdrop").hidden = true;
    $("menu-toggle").setAttribute("aria-expanded", "false");
  }
  function scrollConversation() {
    $("conversation").scrollTo({top:$("conversation").scrollHeight, behavior:"instant"});
  }
  function announce(message) {
    $("announcement").textContent = message;
    $("announcement").hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { $("announcement").hidden = true; }, 4000);
  }
  function validResponse(url, data) {
    const object = value => value !== null && typeof value === "object" && !Array.isArray(value);
    const identifier = value => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
    if (!object(data)) return false;
    if (["/api/chat/", "/api/tracking/", "/api/dashboard/"].includes(url)) return identifier(data.id) && data.status === "queued";
    if (url === "/api/status/") return typeof data.assistant_configured === "boolean";
    if (url === "/api/catalog/") return Array.isArray(data.tables) && data.tables.every(table => object(table) && typeof table.name === "string" && Array.isArray(table.columns) && table.columns.every(column => object(column) && typeof column.name === "string"));
    if (url.startsWith("/api/results/")) {
      if (!identifier(data.id) || !["queued", "running", ...terminal].includes(data.status)) return false;
      if (url.includes("/cancel/")) return true;
      const panel = value => object(value) && Array.isArray(value.columns) && value.columns.every(column => typeof column === "string") &&
        Array.isArray(value.rows) && value.rows.every(row => object(row) && value.columns.every(column => Object.hasOwn(row, column))) &&
        Number.isSafeInteger(value.row_count) && value.row_count >= 0;
      return panel(data) && (data.panels === undefined || Array.isArray(data.panels) && data.panels.every(panel)) &&
        (data.answer === undefined || typeof data.answer === "string");
    }
    return true;
  }
  async function api(url, body, signal) {
    if (sessionInvalid) throw new DOMException("La cuenta cambió.", "AbortError");
    const controller = signal ? null : new AbortController();
    if (controller) controllers.add(controller);
    try {
      const response = await fetch(url, {
        method: body === undefined ? "GET" : "POST",
        credentials: "same-origin",
        headers: body === undefined ? {Accept: "application/json", "X-Bolipost-User": apiIdentity} : {Accept: "application/json", "Content-Type": "application/json", "X-CSRFToken": csrf, "X-Bolipost-User": apiIdentity},
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: signal || controller.signal
      });
      if (response.headers.get("X-Bolipost-User") !== apiIdentity) {
        invalidateSession();
        throw new DOMException("La cuenta cambió. Ingresa de nuevo.", "AbortError");
      }
      if (response.redirected || response.status === 401) {
        invalidateSession();
        throw Object.assign(new Error("La sesión finalizó. Ingresa de nuevo para continuar."), {status: 401});
      }
      let data;
      try { data = await response.json(); } catch { throw new Error("El servidor no devolvió una respuesta válida. Intenta de nuevo."); }
      if (data === null || typeof data !== "object" || Array.isArray(data) || response.ok && !validResponse(url, data)) {
        throw new Error("El servidor no devolvió una respuesta válida. Intenta de nuevo.");
      }
      if (!response.ok) throw Object.assign(new Error(data.error?.message || "No se pudo completar la consulta."), {status: response.status, code: data.error?.code});
      return data;
    } finally { if (controller) controllers.delete(controller); }
  }
  function cancelRequest(id) {
    return fetch("/api/results/" + encodeURIComponent(id) + "/cancel/", {method:"POST", credentials:"same-origin", headers:{"X-CSRFToken":csrf, "X-Bolipost-User":apiIdentity}, keepalive:true}).catch(() => {});
  }
  function stopActive(cancelServer = true) {
    epoch++;
    controllers.forEach(c => c.abort()); controllers.clear();
    const previous = active; active = null;
    if (previous) {
      clearTimeout(previous.timer);
      previous.disposeCharacter?.();
      if (cancelServer) {
        if (previous.id) cancelRequest(previous.id);
        renderResult(previous.host, {status:"cancelled", title:"Consulta cancelada"});
      }
    }
    setBusy(false);
  }
  function setBusy(value) {
    busy = value;
    ["tracking-form", "dashboard-form"].forEach(id => {
      $(id).querySelector('button[type="submit"], button:not([type])').disabled = value;
    });
    const send = $("chat-form").querySelector(".send");
    const stopping = value && view === "chat";
    send.disabled = $("question").disabled || value && !stopping;
    send.type = stopping ? "button" : "submit";
    send.setAttribute("aria-label", stopping ? "Detener consulta" : "Consultar");
    send.title = stopping ? "Detener consulta" : "Consultar";
    send.classList.toggle("is-stopping", stopping);
    send.replaceChildren(icon(stopping ? "stop" : "send"));
  }
  function showView(name) {
    if (name !== view) stopActive();
    view = name;
    document.querySelectorAll(".view").forEach(n => { n.hidden = n.id !== "view-" + name; });
    document.querySelectorAll("[data-view]").forEach(n => {
      n.classList.toggle("active", n.dataset.view === name);
      if (n.dataset.view === name) n.setAttribute("aria-current", "page"); else n.removeAttribute("aria-current");
    });
    $("current-view").textContent = {chat:"Asistente postal", tracking:"Rastrear envío", catalog:"Catálogo de datos", dashboard:"Estadísticas"}[name];
    closeSidebar();
    if (name === "catalog" && !catalog.length) loadCatalog();
  }
  function storageFailed() { $("storage-notice").hidden = false; }
  function transaction(mode, fn) {
    return new Promise((resolve, reject) => {
      if (!db) { resolve(); return; }
      const tx = db.transaction("conversations", mode);
      fn(tx.objectStore("conversations"));
      tx.oncomplete = resolve; tx.onerror = () => reject(tx.error);
    });
  }
  async function openHistory() {
    let legacy = [];
    try {
      db = await new Promise((resolve, reject) => {
        const request = indexedDB.open("bolipost-history-user-" + userId, 1);
        request.onupgradeneeded = () => request.result.createObjectStore("conversations", {keyPath:"id"});
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
        request.onblocked = () => reject(new Error("Almacenamiento bloqueado"));
      });
      if (sessionInvalid) { db.close(); db = null; return; }
      legacy = await new Promise((resolve, reject) => {
        const request = db.transaction("conversations").objectStore("conversations").getAll();
        request.onsuccess = () => resolve(request.result); request.onerror = () => reject(request.error);
      });
      if (sessionInvalid) return;
      legacy = legacy.filter(c => c && typeof c.id === "string" && typeof c.title === "string" && Array.isArray(c.messages));
    } catch { if (sessionInvalid) return; }
    try {
      for (const item of legacy) {
        try {
          const questions = item.messages.filter(message => message?.kind === "question");
          const imported = await api("/api/conversations/" + encodeURIComponent(item.id) + "/save/", {
            title:item.title, messages:questions,
            revision:0, import_only:true});
          if (!["imported", "already_imported"].includes(imported.import_status)) {
            throw new Error("No se confirmó la importación. Se conservó la copia local.");
          }
          await transaction("readwrite", store => store.delete(item.id));
          if (questions.length < item.messages.length) {
            announce("Se importaron las preguntas. Las respuestas antiguas no se pudieron verificar.");
          }
        } catch (error) { if (sessionInvalid) return; storageFailed(); announce(error.message); }
      }
      conversations = [];
      let page = 1, batch;
      do {
        batch = await api("/api/conversations/?page=" + page++);
        conversations.push(...batch.conversations);
      } while (batch.has_more);
    } catch (error) { if (sessionInvalid) return; storageFailed(); announce(error.message); }
    renderHistory();
    await restoreConversationFromUrl();
  }
  let saveQueue = Promise.resolve();
  let pendingSaves = 0;
  async function saveConversation() {
    if (!conversation || sessionInvalid) return;
    const current = conversation;
    const snapshot = current.messages.map(message => message.kind === "question"
      ? {kind:"question", text:message.text}
      : {kind:"result", proof:message.proof});
    pendingSaves++;
    const task = saveQueue.catch(() => {}).then(async () => {
      const saved = await api("/api/conversations/" + encodeURIComponent(current.id) + "/save/", {
        title:current.title, messages:snapshot, revision:current.revision || 0}, new AbortController().signal);
      Object.assign(current, saved);
      const index = conversations.findIndex(c => c.id === current.id);
      if (index < 0) conversations.unshift(current); else conversations[index] = current;
      $("storage-notice").hidden = true;
      renderHistory();
    });
    saveQueue = task;
    try { await task; } catch (error) { storageFailed(); announce(error.message); throw error; }
    finally { pendingSaves--; }
  }
  function renderHistory() {
    $("history-count").textContent = conversations.length;
    const container = $("history-list"); container.replaceChildren();
    const query = $("history-search").value.toLocaleLowerCase("es");
    const matches = conversations.filter(c => (c.title + " " + (c.messages || []).map(m => m.text || m.result?.answer || "").join(" ")).toLocaleLowerCase("es").includes(query)).sort((a,b) => b.updated - a.updated);
    if (!matches.length) container.append(el("p", query ? "No hay conversaciones que coincidan." : "Tus consultas aparecerán aquí.", "history-empty"));
    for (const item of matches) {
      const row = el("div", null, "history-item" + (conversation?.id === item.id ? " selected" : ""));
      row.append(button(item.title, () => restoreConversation(item), ""));
      const remove = button("", async () => {
        if (!window.confirm("¿Enviar esta conversación a la papelera durante 30 días?")) return;
        remove.disabled = true;
        try {
          if (conversation?.id === item.id) stopActive();
          await saveQueue.catch(() => {});
          await api("/api/conversations/" + encodeURIComponent(item.id) + "/trash/", {});
          conversations = conversations.filter(c => c.id !== item.id);
          if (conversation?.id === item.id) newConversation();
          renderHistory(); announce("Conversación enviada a la papelera. Puedes restaurarla durante 30 días.");
        } catch (error) { announce(error.message); remove.disabled = false; }
      }, "history-delete");
      remove.append(icon("trash"));
      remove.setAttribute("aria-label", "Eliminar conversación: " + item.title);
      row.append(remove); container.append(row);
    }
  }
  function syncConversationUrl(replace = false) {
    const path = conversation ? "/c/" + encodeURIComponent(conversation.id) : "/";
    if (window.location.pathname !== path) window.history[replace ? "replaceState" : "pushState"](null, "", path);
    $("conversation-id").textContent = conversation ? "ID del chat: " + conversation.id : "";
    $("conversation-id").hidden = !conversation;
  }
  async function restoreConversationFromUrl() {
    if (sessionInvalid) return;
    const match = window.location.pathname.match(/^\/c\/([^/]+)\/?$/);
    const item = match && conversations.find(c => c.id === match[1]);
    if (item) await restoreConversation(item, false);
    else {
      newConversation(false);
      if (match) announce("Esta conversación no está disponible en el historial de esta cuenta.");
    }
    syncConversationUrl(true);
  }
  function newConversation(updateUrl = true) {
    stopActive(); showView("chat"); conversation = null;
    if (updateUrl !== false) syncConversationUrl();
    charts.forEach(chart => { if ($("messages").contains(chart.canvas)) { chart.destroy(); charts.delete(chart); } });
    $("messages").replaceChildren(); $("chat-welcome").hidden = false;
    $("question").value = ""; renderHistory(); $("question").focus();
    $("conversation").scrollTop = 0;
  }
  async function restoreConversation(item, updateUrl = true) {
    stopActive();
    const requestEpoch = epoch;
    try {
      await saveQueue;
      if (requestEpoch !== epoch) return;
      const fresh = await api("/api/conversations/" + encodeURIComponent(item.id) + "/");
      if (requestEpoch !== epoch) return;
      Object.assign(item, fresh);
    } catch (error) { if (error.name !== "AbortError") announce(error.message); return; }
    showView("chat"); conversation = item;
    if (updateUrl) syncConversationUrl();
    charts.forEach(chart => { if ($("messages").contains(chart.canvas)) { chart.destroy(); charts.delete(chart); } });
    $("messages").replaceChildren(); $("chat-welcome").hidden = true;
    if (item.unverified_results) {
      $("messages").append(el("p", "Se ocultaron respuestas antiguas cuyo origen no se pudo verificar.", "notice"));
    }
    for (const message of item.messages) {
      if (message.kind === "question") appendQuestion(message.text, message);
      else if (message.result) {
        const host = el("div", null, "message"); $("messages").append(host);
        renderResult(host, message.result, {restored:true});
      }
    }
    renderHistory(); $("question").focus(); scrollConversation();
  }
  function appendQuestion(text, message) {
    const node = el("div", null, "message question-entry");
    const actions = el("div", null, "question-actions");
    const bubble = el("div", text, "question-message");
    const edit = button("", () => {
      if (busy) { announce("Espera a que termine la consulta para editarla."); return; }
      const form = el("form", null, "question-editor");
      const input = el("textarea");
      input.value = text; input.required = true; input.maxLength = $("question").maxLength;
      input.rows = 1;
      input.setAttribute("aria-label", "Editar consulta en el chat");
      const controls = el("div", null, "question-actions");
      const cancel = () => { form.replaceWith(bubble); actions.hidden = false; edit.focus(); };
      const close = button("", cancel, "question-action");
      close.append(icon("close")); close.title = "Cancelar edición"; close.setAttribute("aria-label", close.title);
      const send = el("button", null, "question-action"); send.type = "submit";
      send.append(icon("check")); send.title = "Enviar consulta editada"; send.setAttribute("aria-label", send.title);
      controls.append(close, send); form.append(input, controls);
      form.addEventListener("submit", event => {
        event.preventDefault();
        const question = input.value.trim();
        const index = conversation?.messages.indexOf(message) ?? -1;
        if (!question || busy || index < 0) return;
        const context = chatContext(conversation.messages.slice(0, index));
        stopActive();
        conversation.messages.splice(index);
        if (index === 0) conversation.title = question.slice(0, 75);
        while (node.nextSibling) node.nextSibling.remove();
        node.remove();
        charts.forEach(chart => { if (!chart.canvas.isConnected) { chart.destroy(); charts.delete(chart); } });
        submitJob("/api/chat/", {question, ...context}, $("messages"), question);
        saveConversation().catch(error => announce(error.message));
      });
      input.addEventListener("keydown", event => {
        if (event.key === "Escape") { event.preventDefault(); cancel(); }
        if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); form.requestSubmit(); }
      });
      actions.hidden = true; bubble.replaceWith(form); input.focus();
      input.setSelectionRange(text.length, text.length);
    }, "question-action");
    edit.append(icon("edit")); edit.setAttribute("aria-label", "Editar consulta"); edit.title = "Editar consulta";
    const copy = button("", async () => {
      try { await navigator.clipboard.writeText(text); announce("Consulta copiada."); }
      catch { announce("No se pudo copiar. Selecciona el texto de la consulta para copiarlo."); }
    }, "question-action");
    copy.append(icon("copy")); copy.setAttribute("aria-label", "Copiar consulta"); copy.title = "Copiar consulta";
    actions.append(edit, copy);
    node.append(bubble, actions);
    $("messages").append(node);
  }
  function resultHost(target) {
    const host = el("div", null, "message");
    if (target === $("messages")) target.append(host); else target.replaceChildren(host);
    return host;
  }
  async function submitJob(endpoint, body, target, question) {
    stopActive();
    const token = epoch;
    setBusy(true);
    if (question) {
      $("messages").querySelectorAll(".retry-result").forEach(button => button.remove());
      if (!conversation) conversation = {id:crypto.randomUUID(), title:question.slice(0,75), messages:[], updated:Date.now()};
      syncConversationUrl();
      const message = {kind:"question", text:question};
      conversation.messages.push(message);
      appendQuestion(question, message); $("chat-welcome").hidden = true; $("question").value = "";
    }
    if (epoch !== token) return;
    const host = resultHost(target);
    const pending = {id:null, token, host, target, isChat:endpoint === "/api/chat/", timer:null};
    active = pending;
    const chat = conversation;
    const turn = chat?.messages.at(-1);
    const retry = () => {
      if (busy || !host.isConnected ||
          pending.isChat && (conversation !== chat || chat?.messages.at(-1) !== turn)) return;
      host.remove();
      submitJob(endpoint, body, target);
    };
    host.append(el("div", "Preparando la consulta…", "result-state"));
    if (pending.isChat) scrollConversation();
    try {
      if (question) await saveConversation();
      if (pending.isChat && conversation) body = {...body, chat_id:conversation.id};
      if (epoch !== token) return;
      let job;
      try { job = await api(endpoint, body, new AbortController().signal); }
      catch (error) {
        if (error.status === 404 && body.previous_id) {
          throw Object.assign(new Error("La referencia de esta conversación caducó. Vuelve a ejecutar la pregunta original en una nueva conversación y después repite el seguimiento, para conservar sus filtros y referente."), {code:"CONTEXT_EXPIRED"});
        } else throw error;
      }
      if (epoch !== token) { cancelRequest(job.id); return; }
      pending.id = job.id;
      await poll(pending);
    } catch (error) {
      if (epoch !== token || error.name === "AbortError") return;
      pending.disposeCharacter?.();
      renderError(host, error.message, error.code === "CONTEXT_EXPIRED" ? null : retry);
      setBusy(false); active = null;
    }
  }
  function renderError(host, message, retry) {
    host.replaceChildren();
    const card = el("div", null, "result-card");
    const state = el("div", null, "result-state");
    state.append(el("p", message, "error-text"));
    if (retry) state.append(button("Volver a intentar", retry, "text-button retry-result"));
    card.append(state); host.append(card);
  }
  async function poll(job) {
    if (epoch !== job.token || active !== job) return;
    try {
      const data = await api("/api/results/" + encodeURIComponent(job.id) + "/?page=1");
      if (epoch !== job.token || active !== job) return;
      if (!terminal.has(data.status)) {
        const existing = job.host.querySelector(".pending-label");
        if (existing) {
          existing.textContent = data.status === "queued" ? "Consulta en espera…" : "Consultando los datos…";
          job.timer = setTimeout(() => poll(job), 850);
          return;
        }
        job.host.replaceChildren();
        const card = el("div", null, "result-card pending-card");
        const state = el("div", null, "result-state thinking-state");
        if (job.isChat && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
          const scene = el("div", null, "thinking-scene");
          scene.setAttribute("aria-hidden", "true");
          job.disposeCharacter = window.PostalThinking.mount(scene);
          state.append(scene);
        }
        const status = el("div", null, "thinking-status");
        status.setAttribute("role", "status");
        const dots = el("span", null, "thinking-dots");
        dots.setAttribute("aria-hidden", "true");
        for (let i = 0; i < 3; i++) dots.append(el("span"));
        status.append(dots, el("span", data.status === "queued" ? "Consulta en espera…" : "Consultando los datos…", "pending-label"));
        state.append(status);
        const actions = el("div", null, "result-actions");
        if (!job.isChat) actions.append(button("Cancelar consulta", () => cancelJob(job)));
        card.append(state);
        if (!job.isChat) card.append(actions);
        job.host.append(card);
        if (job.isChat) scrollConversation();
        job.timer = setTimeout(() => poll(job), 850);
        return;
      }
      job.disposeCharacter?.();
      renderResult(job.host, data);
      if (job.isChat) scrollConversation();
      if (job.isChat && conversation && data.history_proof) {
        const {history_proof:proof, ...result} = data;
        if (!conversation.messages.some(message => message.result?.id === result.id)) {
          conversation.messages.push({kind:"result", result, proof});
        }
        await saveConversation();
      }
      if (epoch === job.token && active === job) { active = null; setBusy(false); }
    } catch (error) {
      if (epoch !== job.token || error.name === "AbortError") return;
      job.disposeCharacter?.();
      active = null; setBusy(false);
      renderError(job.host, error.message, () => {
        if (job.token !== epoch) return;
        active = job; setBusy(true); poll(job);
      });
    }
  }
  async function cancelJob(job) {
    if (active !== job) return;
    if (!job.id) { stopActive(); return; }
    clearTimeout(job.timer);
    const send = $("chat-form").querySelector(".send");
    if (job.isChat) send.disabled = true;
    try {
      await api("/api/results/" + encodeURIComponent(job.id) + "/cancel/", {});
      if (active !== job) return;
      stopActive(false);
      renderResult(job.host, {status:"cancelled", title:"Consulta cancelada"});
    } catch (error) {
      if (active !== job) return;
      announce(error.message); setBusy(true);
      job.timer = setTimeout(() => poll(job), 850);
    }
  }
  function chatContext(messages = conversation?.messages || []) {
    const ids = [...new Set(messages.filter(message => message.kind === "result" && message.result?.id &&
      message.result.response_type !== "help" &&
      (["ok", "no_matches", "empty_table"].includes(message.result.status) ||
       message.result.status === "error" && message.result.error?.code === "clarification"))
      .map(message => message.result.id))].slice(-12);
    return ids.length ? {previous_id:ids.at(-1), history_ids:ids} : {};
  }
  function printable(value) {
    if (value === null || value === undefined) return "—";
    if (typeof value === "object") return JSON.stringify(value);
    return String(value);
  }
  function monthLabel(value) {
    const match = typeof value === "string" && /^(\d{4})-(0[1-9]|1[0-2])-01(?:[T ]00:00:00(?:\.0+)?(?:Z|[+-]00:00)?)?$/.exec(value);
    if (!match) return null;
    return new Intl.DateTimeFormat("es", {month:"short", year:"numeric", timeZone:"UTC"})
      .format(new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, 1))).replaceAll(".", "");
  }
  const dayFormat = new Intl.DateTimeFormat("es", {
    weekday:"short", day:"numeric", month:"short", year:"numeric", timeZone:"UTC"
  });
  const weightFormat = new Intl.NumberFormat("es-BO", {minimumFractionDigits:3, maximumFractionDigits:20});
  function reportDay(value) {
    const match = typeof value === "string" && /^(\d{4}-\d{2}-\d{2})(?:[T ]00:00:00(?:\.0+)?(?:Z|[+-]00:00)?)?$/.exec(value);
    if (!match) return null;
    const date = new Date(match[1] + "T00:00:00Z");
    if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== match[1]) return null;
    return date;
  }
  function metricNumber(value) {
    if (typeof value === "number") return Number.isFinite(value) ? value : null;
    if (typeof value !== "string" || !/^-?\d+(?:\.\d+)?$/.test(value)) return null;
    const number = Number(value);
    return Number.isFinite(number) && Math.abs(number) <= Number.MAX_SAFE_INTEGER ? number : null;
  }
  function metricText(value, column) {
    if (/^(mes|month)$/i.test(column)) return monthLabel(value) || printable(value);
    if (!/^(total_envios|total_paquetes|cantidad|total|peso_total|total_peso|peso_promedio)$/.test(column)) return printable(value);
    const number = metricNumber(value);
    if (number === null) return printable(value);
    const digits = /promedio|average/i.test(column) ? 2 : /peso|weight/i.test(column) ? 3 : Number.isInteger(number) ? 0 : 2;
    return new Intl.NumberFormat("es-BO", {minimumFractionDigits:digits, maximumFractionDigits:digits}).format(number);
  }
  function categoricalDashboard(data) {
    if (data.response_type !== "dashboard" && !/^dashboard\b/i.test(data.title || "")) return null;
    const chart = data.chart;
    const count = data.columns?.find(column => /^(total_envios|total_paquetes|cantidad|total|total_movimientos)$/.test(column));
    if (data.status !== "ok" || data.has_more || (data.page || 1) !== 1 || !count ||
        chart?.kind !== "bar" || !Array.isArray(chart.labels) || chart.labels.length < 2 ||
        !Array.isArray(chart.values) || chart.values.length !== chart.labels.length ||
        chart.values.length !== data.rows?.length || data.row_count !== data.rows.length ||
        !chart.values.every((value, index) => Number.isSafeInteger(value) && value >= 0 &&
          value === metricNumber(data.rows[index][count]))) return null;
    const total = chart.values.reduce((sum, value) => sum + value, 0);
    if (!Number.isSafeInteger(total)) return null;
    const points = chart.labels.map((label, index) => ({label:printable(label), value:chart.values[index]}))
      .sort((a, b) => b.value - a.value);
    return {points, total, count};
  }
  function addCategoricalDashboard(card, data, dashboard) {
    const {points, total, count} = dashboard;
    const format = value => new Intl.NumberFormat("es-BO", {maximumFractionDigits:1}).format(value);
    const percent = value => new Intl.NumberFormat("es-BO", {style:"percent", maximumFractionDigits:1}).format(total ? value / total : 0);
    const dimension = data.columns.find(column => column !== count);
    const category = dimension ? columnLabel(dimension).toLowerCase() : "categoría";
    const categoryLabel = {ciudad:"Ciudades", departamento:"Departamentos", servicio:"Servicios", estado:"Estados", sucursal:"Sucursales"}[category] || "Categorías con registros";
    card.classList.add("categorical-dashboard");
    const stats = el("dl", null, "categorical-kpis");
    const topThree = points.slice(0, 3).reduce((sum, point) => sum + point.value, 0);
    for (const [label, value, note] of [
      [columnLabel(count), format(total), "Resultado completo de la consulta"],
      [categoryLabel, format(points.length), "Agrupadas por " + category],
      ["Mayor participación", percent(points[0].value), points[0].label + " · " + format(points[0].value)],
      ["Concentración · top " + Math.min(3, points.length), percent(topThree), "Participación sobre el total"]
    ]) {
      const field = el("div");
      field.append(el("dt", label), el("dd", value), el("span", note)); stats.append(field);
    }
    card.append(stats);
    const grid = el("div", null, "categorical-grid");
    const distribution = el("section", null, "dashboard-distribution");
    distribution.append(el("h3", data.primary_title || data.title));
    addChart(distribution, data);
    const ranking = el("section", null, "dashboard-participation");
    ranking.append(el("h3", "Participación en el total"));
    const leader = el("p", null, "dashboard-finding");
    leader.append(el("strong", points[0].label), document.createTextNode(" concentra el " + percent(points[0].value) + " del total."));
    ranking.append(leader);
    const list = el("ol", null, "dashboard-share-list");
    for (const point of points) {
      const item = el("li"), line = el("div");
      line.append(el("span", point.label), el("strong", format(point.value)), el("span", percent(point.value), "dashboard-share-percent"));
      const track = el("div", null, "dashboard-share-track"), fill = el("span");
      fill.style.width = (total ? point.value / total * 100 : 0) + "%";
      track.setAttribute("aria-hidden", "true"); track.append(fill);
      item.append(line, track); list.append(item);
    }
    ranking.append(list); grid.append(distribution, ranking); card.append(grid);
    if (data.columns.length > 2) {
      const details = el("section", null, "dashboard-data");
      details.append(el("h3", "Detalle por " + category));
      const records = el("div", null, "dashboard-records");
      for (const row of data.rows) {
        const record = el("dl", null, "dashboard-record");
        for (const column of data.columns) {
          const field = el("div");
          field.append(el("dt", columnLabel(column)), el("dd", metricText(row[column], column)));
          record.append(field);
        }
        records.append(record);
      }
      details.append(records); card.append(details);
    }
  }
  function shipmentDashboard(data) {
    if (!data.panels || data.panels.length < 2) return null;
    const families = data.panels.map(panel => {
      const match = /^Resumen de env[ií]os\s+(EMS|CERTI|ORDI|INT|CONTRATO)$/i.exec(panel.title || "");
      return match ? {panel, name:match[1].toUpperCase()} : null;
    }).filter(Boolean);
    if (families.length < 2 || new Set(families.map(item => item.name)).size !== families.length) return null;
    const columns = families[0].panel.columns;
    if (columns?.length !== 2) return null;
    const count = columns.find(column => /^(total_envios|total_paquetes|cantidad|total)$/.test(column));
    const weight = columns.find(column => /^(peso_total|total_peso)$/.test(column));
    if (!count || !weight || families.some(({panel}) => panel.status !== "ok" || panel.chart || panel.has_more ||
        (panel.page || 1) !== 1 || panel.row_count !== 1 || panel.rows?.length !== 1 ||
        JSON.stringify(panel.columns) !== JSON.stringify(columns) ||
        !columns.every(column => metricNumber(panel.rows[0][column]) !== null && metricNumber(panel.rows[0][column]) >= 0) ||
        !Number.isSafeInteger(metricNumber(panel.rows[0][count])))) return null;
    if (families[0].panel.index !== data.panels[0].index) return null;
    return {families, columns, count, weight};
  }
  function addShipmentDashboard(card, dashboard) {
    const {families, columns, count, weight} = dashboard;
    card.classList.add("shipment-dashboard");
    const stats = el("dl", null, "dashboard-kpis");
    for (const column of columns) {
      const field = el("div");
      // Weight totals sum the displayed thousandths, avoiding floating-point drift.
      const scale = column === weight ? 1000 : 1;
      const total = families.reduce((sum, {panel}) => sum + Math.round(metricNumber(panel.rows[0][column]) * scale), 0) / scale;
      field.append(el("dt", columnLabel(column)), el("dd", metricText(total, column)));
      stats.append(field);
    }
    card.append(stats);
    const section = el("section", null, "shipment-summary");
    section.append(el("h3", "Envíos por familia"));
    const table = el("table"), head = el("thead"), header = el("tr");
    for (const column of ["Familia", ...columns]) {
      const th = el("th", columns.includes(column) ? columnLabel(column) : column, columns.includes(column) ? "numeric" : "");
      th.scope = "col"; header.append(th);
    }
    head.append(header); table.append(head);
    const body = el("tbody"), largest = Math.max(...families.map(({panel}) => metricNumber(panel.rows[0][count])));
    for (const {panel, name} of families) {
      const row = el("tr"), label = el("th", name); label.scope = "row";
      const track = el("span", null, "family-track"), fill = el("span");
      fill.style.width = (largest ? metricNumber(panel.rows[0][count]) / largest * 100 : 0) + "%";
      track.setAttribute("aria-hidden", "true"); track.append(fill); label.append(track); row.append(label);
      for (const column of columns) row.append(el("td", metricText(panel.rows[0][column], column), "numeric"));
      body.append(row);
    }
    table.append(body);
    const scroll = el("div", null, "table-scroll"); scroll.tabIndex = 0;
    scroll.setAttribute("role", "region"); scroll.setAttribute("aria-label", "Comparación de envíos por familia");
    scroll.append(table); section.append(scroll); card.append(section);
  }
  function addDailyVolume(card, data) {
    const {chart, columns, rows} = data;
    if (chart?.kind !== "line" || columns?.length !== 2 || !rows || rows.length < 2 ||
        rows.length > 31 || rows.length !== data.row_count || data.has_more || (data.page || 1) !== 1 ||
        !Array.isArray(chart.labels) || chart.labels.length !== rows.length ||
        !Array.isArray(chart.values) || chart.values.length !== rows.length) return false;
    const day = columns.find(column => /^(d[ií]a|fecha|day|date)$/.test(column));
    const count = columns.find(column => /^(total_envios|total_paquetes|cantidad|total)$/.test(column));
    if (!day || !count) return false;
    const points = rows.map(row => ({date:reportDay(row[day]), value:metricNumber(row[count])}));
    const first = points[0].date;
    if (!first || !points.every(({date, value}, index) =>
      date && date.getUTCFullYear() === first.getUTCFullYear() && date.getUTCMonth() === first.getUTCMonth() &&
      Number.isSafeInteger(value) && value >= 0 && chart.values[index] === value &&
      reportDay(chart.labels[index])?.getTime() === date.getTime()) ||
      new Set(points.map(({date}) => date.getUTCDate())).size !== points.length) return false;
    points.sort((a, b) => a.date - b.date);
    const peak = Math.max(...points.map(({value}) => value));
    const shortDay = new Intl.DateTimeFormat("es", {day:"numeric", month:"short", timeZone:"UTC"});
    const figure = el("figure", null, "daily-volume"), bars = el("ol");
    bars.setAttribute("role", "list");
    for (const {date, value} of points) {
      const item = el("li"), track = el("span", null, "daily-volume-track");
      const bar = el("span", null, value > 0 && value === peak ? "daily-volume-peak" : "");
      const time = el("time", shortDay.format(date));
      time.dateTime = date.toISOString().slice(0, 10);
      time.setAttribute("aria-label", dayFormat.format(date));
      track.setAttribute("aria-hidden", "true");
      bar.style.height = (peak ? value / peak * 100 : 0) + "%";
      track.append(bar);
      item.append(time, el("strong", metricText(value, "total")), track);
      bars.append(item);
    }
    figure.append(el("figcaption", "Detalle diario"), bars);
    card.append(figure);
    return true;
  }
  function addTable(card, data, {record = false, formatted = false} = {}) {
    if (!data.columns?.length || !data.rows?.length) return;
    // Only complete, numeric one-value answers are a metric; IDs stay literal.
    const metricColumn = data.columns[0];
    if (record && !data.chart && data.status === "ok" && !data.has_more &&
        (data.page || 1) === 1 && data.row_count === 1 && data.rows.length === 1 && data.columns.length === 1 &&
        /^(total_envios|total_paquetes|cantidad|total|peso_total|total_peso|peso_promedio)$/.test(metricColumn) &&
        metricNumber(data.rows[0][metricColumn]) !== null) {
      const metric = el("dl", null, "result-metric");
      const value = data.rows[0][metricColumn];
      // Group integer counts, but preserve fractional precision exactly as received.
      const display = Number.isSafeInteger(metricNumber(value)) ? new Intl.NumberFormat("es-BO").format(value) : printable(value);
      metric.append(el("dt", columnLabel(metricColumn)), el("dd", display));
      card.append(metric);
      return;
    }
    if (record && !data.chart && (data.columns.length >= 8 ||
        data.rows.length === 1 && data.row_count === 1 && data.columns.length >= 3)) {
      const multiple = data.rows.length > 1;
      const list = multiple ? el("ol", null, "record-list") : card;
      if (multiple) list.setAttribute("aria-label", "Registros de la consulta");
      for (const [index, row] of data.rows.entries()) {
        const item = multiple ? el("li") : card;
        if (multiple) item.append(el("h4", "Registro " + (index + 1), "record-title"));
        const fields = el("dl", null, "record-fields");
        for (const column of data.columns) {
          const field = el("div", null, "record-field");
          field.append(el("dt", columnLabel(column)), el("dd", formatted ? metricText(row[column], column) : printable(row[column])));
          fields.append(field);
        }
        item.append(fields);
        if (multiple) list.append(item);
      }
      if (multiple) card.append(list);
      return;
    }
    const day = data.chart?.kind === "line" && data.columns.find(column => /^(d[ií]a|fecha|day|date)$/.test(column));
    const city = data.chart?.kind === "bar" && data.columns.find(column => /^(ciudad|ciudad_destino|city)$/.test(column));
    const count = data.columns.find(column => /^(total_envios|total_paquetes|cantidad|total)$/.test(column));
    const dimension = count && (day || city);
    const detail = dimension && (day ? "Detalle diario" : "Detalle por ciudad");
    const weight = detail && data.columns.find(column => /^(peso_total|total_peso)$/.test(column));
    const maximum = detail ? Math.max(0, ...data.rows.map(row => metricNumber(row[count]))) : 0;
    const scroll = el("div", null, "table-scroll"); scroll.tabIndex = 0;
    scroll.setAttribute("role", "region"); scroll.setAttribute("aria-label", detail || "Resultados de la consulta");
    const table = el("table"), head = el("thead"), header = el("tr");
    if (detail) {
      table.classList.add("shipment-detail");
      table.append(el("caption", detail));
      if (data.rows.length <= 31) scroll.classList.add("shipment-detail-short");
    }
    for (const column of data.columns) {
      const th = el("th", day && column === dimension ? "Fecha" : columnLabel(column)); th.scope = "col";
      if (detail && column === count) th.classList.add("shipment-detail-count", "numeric");
      if (column === weight) th.classList.add("shipment-detail-weight", "numeric");
      if (data.rows.some(row => typeof row[column] === "number" ||
          formatted && column !== dimension && metricNumber(row[column]) !== null)) th.classList.add("numeric");
      header.append(th);
    }
    head.append(header); table.append(head);
    const body = el("tbody");
    for (const row of data.rows) {
      const tr = el("tr");
      for (const column of data.columns) {
        const value = row[column];
        const text = formatted ? metricText(value, column) : printable(value);
        if (column === dimension) {
          const label = el("th"); label.scope = "row";
          const date = day && reportDay(value);
          if (date) {
            const time = el("time", dayFormat.format(date));
            time.dateTime = date.toISOString().slice(0, 10);
            label.append(time);
          } else label.append(text);
          tr.append(label);
          continue;
        }
        const isDetailMetric = detail && (column === count || column === weight);
        const number = formatted || isDetailMetric ? metricNumber(value) : null;
        const cell = el("td", text, isDetailMetric || typeof value === "number" || number !== null ? "numeric" : "");
        if (detail && column === count && Number.isSafeInteger(number)) {
          const quantity = el("span", null, "shipment-detail-quantity");
          if (maximum > 0 && number >= 0) {
            const track = el("span", null, "comparison-track"), fill = el("span", null, "comparison-fill");
            track.setAttribute("aria-hidden", "true");
            fill.style.width = (number / maximum * 100) + "%";
            track.append(fill); quantity.append(track);
          }
          quantity.append(el("span", metricText(value, "total")));
          cell.replaceChildren(quantity);
        } else if (column === weight && number !== null) {
          cell.textContent = /\.\d{21}/.test(String(value)) ? printable(value) : weightFormat.format(value);
        }
        tr.append(cell);
      }
      body.append(tr);
    }
    table.append(body); scroll.append(table); card.append(scroll);
  }
  function addChart(card, data) {
    const chart = data.chart;
    if (!chart || !Array.isArray(chart.labels) || !Array.isArray(chart.values) || !chart.labels.length || chart.labels.length !== chart.values.length || !chart.values.every(v => typeof v === "number" && Number.isFinite(v))) return;
    const kind = chart.kind === "line" ? "line" : "bar";
    const missing = label => label === null || label === "" || /^(sin dato|sin fecha|—)$/i.test(label);
    const temporal = kind === "line" && chart.labels.some(label => monthLabel(label)) &&
      chart.labels.every(label => monthLabel(label) || missing(label));
    const points = chart.labels.map((label, index) => ({label, value:chart.values[index]}));
    const visible = temporal ? points.filter(point => !missing(point.label)) : points;
    if (temporal && visible.length !== points.length) {
      const total = points.filter(point => missing(point.label)).reduce((sum, point) => sum + point.value, 0);
      card.append(el("p", "Sin fecha: " + metricText(total, "total_envios") + " · incluido en el detalle.", "chart-note"));
    }
    const labels = visible.map(point => temporal ? monthLabel(point.label) : point.label);
    const values = visible.map(point => point.value);
    const format = value => new Intl.NumberFormat("es-BO", {maximumFractionDigits:2}).format(value);
    if (!values.length) return;
    if (values.length === 1 && !temporal) {
      const summary = el("dl", null, "chart-single");
      const value = el("dd");
      value.append(el("strong", format(values[0])), el("span", chart.label || "Total"));
      summary.append(el("dt", printable(labels[0])), value);
      card.append(summary);
      return;
    }
    const total = values.reduce((sum, value) => sum + value, 0);
    const canShare = values.every(value => value >= 0) && total > 0 && Number.isFinite(total);
    const figure = el("figure", null, "chart-figure");
    const toolbar = el("div", null, "chart-toolbar"), caption = el("figcaption");
    caption.append(el("strong", canShare ? format(total) : String(labels.length)),
      document.createTextNode(canShare ? " " + (chart.label || "Total").toLowerCase() + " · " + labels.length + " categorías" : " categorías"));
    if (data.has_more || (data.page || 1) > 1) caption.append(document.createTextNode(" · página visible"));
    const requestedView = chart.view;
    const view = kind === "line" ? "line" : requestedView === "pie" && canShare && !data.has_more && (data.page || 1) === 1 ? "pie" : requestedView === "bar" ? "bar" :
      requestedView === "horizontal" ? "horizontal" :
      canShare && values.length <= 5 && !data.has_more && (data.page || 1) === 1 &&
      (!requestedView || requestedView === "doughnut") ? "doughnut" : "horizontal";
    toolbar.append(caption);
    const body = el("div", null, "chart-body"), wrapper = el("div", null, "chart-wrapper"), canvas = el("canvas");
    const legend = el("ul", null, "chart-legend");
    canvas.setAttribute("role", "img"); canvas.setAttribute("aria-label", (chart.label || data.title || "Gráfico") + ". Valores disponibles en el detalle de datos.");
    wrapper.append(canvas); body.append(wrapper, legend); figure.append(toolbar, body); card.append(figure);
    if (!window.Chart) { body.replaceChildren(el("p", "No se pudo cargar el gráfico. Los valores siguen disponibles en la tabla.")); return; }
    let instance;
    function draw() {
      if (instance) { charts.delete(instance); instance.destroy(); }
      const style = getComputedStyle(document.documentElement);
      const color = style.getPropertyValue("--blue").trim(), muted = style.getPropertyValue("--muted").trim();
      const border = style.getPropertyValue("--border").trim(), ink = style.getPropertyValue("--ink").trim();
      const surface = style.getPropertyValue("--surface").trim();
      const ring = view === "doughnut" || view === "pie", horizontal = view === "horizontal", line = view === "line";
      const palette = document.documentElement.dataset.theme === "dark"
        ? [color, "#75a8e8", "#5491d5", "#a8cbdc", "#7996b4", "#c1d8ed"]
        : [color, "#3577b8", "#5498be", "#83b1c8", "#a5c9d8", "#657e9b"];
      const colors = labels.map((label, index) => /^sin departamento$/i.test(label) ? muted : palette[index % palette.length]);
      figure.dataset.view = view;
      wrapper.style.height = (ring ? 244 : horizontal ? Math.max(220, labels.length * 32 + 36) : 250) + "px";
      legend.hidden = !ring; legend.replaceChildren();
      if (ring) labels.forEach((label, index) => {
        const item = el("li"), swatch = el("span", null, "chart-swatch");
        swatch.style.backgroundColor = colors[index]; swatch.setAttribute("aria-hidden", "true");
        item.append(swatch, el("span", printable(label)), el("strong", format(values[index])),
          el("span", new Intl.NumberFormat("es-BO", {style:"percent", maximumFractionDigits:1}).format(values[index] / total), "chart-percent"));
        legend.append(item);
      });
      const categoryAxis = {grid:{display:false}, ticks:{color:muted, autoSkip:!horizontal,
        maxRotation:0, font:{size:11}}, border:{display:false}};
      const numberAxis = {beginAtZero:true, grid:{color:border, drawTicks:false},
        ticks:{color:muted, maxTicksLimit:5, precision:0, font:{size:11}}, border:{display:false}};
      instance = new Chart(canvas, {
        type:view === "pie" ? "pie" : ring ? "doughnut" : line ? "line" : "bar",
        data:{labels, datasets:[{label:chart.label || data.title, data:values,
          backgroundColor:ring ? colors : line ? color + "18" : color,
          borderColor:ring ? surface : color, borderWidth:ring ? 3 : line ? 2 : 0,
          borderRadius:line || ring ? 0 : 4, maxBarThickness:32,
          pointRadius:line ? 3 : 0, pointHoverRadius:5, pointHitRadius:12, tension:0,
          fill:line}]},
        options:{locale:"es-BO", responsive:true, maintainAspectRatio:false, animation:false,
          indexAxis:horizontal ? "y" : "x", cutout:view === "pie" ? 0 : "76%",
          layout:{padding:horizontal ? {right:64} : 8},
          plugins:{legend:{display:false}, tooltip:{padding:12, displayColors:ring,
            callbacks:{label:context => (chart.label || "Total") + ": " + format(context.raw) +
              (ring ? " (" + new Intl.NumberFormat("es-BO", {style:"percent", maximumFractionDigits:1}).format(context.raw / total) + ")" : "")}}},
          scales:ring ? {} : {x:horizontal ? numberAxis : categoryAxis, y:horizontal ? categoryAxis : numberAxis}},
        plugins:[{id:"reportValues", afterDraw(c) {
          const ctx = c.ctx; ctx.save(); ctx.fillStyle = ink;
          ctx.font = "500 11px " + style.fontFamily;
          if (ring) {
            const arc = c.getDatasetMeta(0).data[0];
            if (arc && view !== "pie") {
              ctx.textAlign = "center"; ctx.textBaseline = "middle";
              const text = format(total), diameter = arc.innerRadius * 1.7;
              const size = Math.min(28, 28 * diameter / Math.max(ctx.measureText(text).width * 28 / 11, 1));
              ctx.font = "600 " + size + "px " + style.fontFamily;
              ctx.fillText(text, arc.x, arc.y - 8);
              ctx.font = "12px " + style.fontFamily; ctx.fillStyle = muted;
              ctx.fillText("Total", arc.x, arc.y + 17);
            }
          } else if (horizontal) {
            ctx.textBaseline = "middle";
            c.getDatasetMeta(0).data.forEach((bar, index) => {
              ctx.textAlign = values[index] < 0 ? "right" : "left";
              ctx.fillText(format(values[index]), bar.x + (values[index] < 0 ? -7 : 7), bar.y);
            });
          }
          ctx.restore();
        }}]
      });
      instance.refreshTheme = draw;
      charts.add(instance);
    }
    draw();
  }
  function answerText(value) {
    return (value || "").split("\n").filter(line => !/^\s*Fuente\s*:/i.test(line)).join("\n").trim();
  }
  function explanationResult(data) {
    return data.is_explanation ?? (data.analysis?.presentation === "explanation" ||
      /^explicaci[oó]n\b/i.test(data.title || "") && !!(data.analysis?.generated || data.analysis?.citations?.length));
  }
  function shipmentBreakdownText(panel, dimension) {
    if (panel.has_more || (panel.page || 1) !== 1 || !Array.isArray(panel.rows) || panel.rows.length !== panel.row_count) return "";
    const points = panel.rows.map(row => ({label:row[dimension], count:metricNumber(row.total_envios)}));
    if (points.some(point => typeof point.label !== "string" || !point.label.trim() ||
        !Number.isSafeInteger(point.count) || point.count < 0) ||
        new Set(points.map(point => point.label)).size !== points.length) return "";
    points.sort((a, b) => b.count - a.count);
    const [peak, next] = points;
    if (!next || peak.count === next.count) return "";
    const count = metricText(peak.count, "total_envios");
    if (dimension === "dia") {
      const date = reportDay(peak.label);
      if (!date) return "";
      const day = new Intl.DateTimeFormat("es", {day:"numeric", month:"long", year:"numeric", timeZone:"UTC"})
        .format(date);
      return `El ${day} fue el día de mayor actividad del reporte, con ${count} envíos.`;
    }
    const city = peak.label === peak.label.toLocaleUpperCase("es")
      ? peak.label.toLocaleLowerCase("es").replace(/(^|[\s-])\p{L}/gu, letter => letter.toLocaleUpperCase("es"))
      : peak.label;
    return `Entre las ciudades del reporte, ${city} registró la mayor cantidad, con ${count} envíos.`;
  }
  function reportText(data) {
    const paragraphs = data.answer.split(/\n\s*\n/);
    const summaries = new Set();
    const panels = data.panels || [];
    for (const panel of panels) {
      const dimension = panel.chart?.kind === "line" && panel.columns?.includes("dia") ? "dia"
        : panel.chart?.kind === "bar" && panel.columns?.includes("ciudad") ? "ciudad" : null;
      if (!dimension || !panel.columns.includes("total_envios") ||
          panels.some(other => other !== panel && other.title === panel.title)) continue;
      const matches = [];
      for (const [index, paragraph] of paragraphs.entries()) {
        const sources = /^Fuente:\s*(.+)$/m.exec(paragraph)?.[1].split("; ");
        const cells = sources?.map(source => source.split(" · "));
        const row = cells?.[0]?.[2];
        if (cells?.length >= 2 && /^fila \d+$/.test(row) &&
            cells.every(cell => cell.length === 3 && cell[0] === panel.title && cell[2] === row)) {
          matches.push({index, row});
        }
      }
      if (new Set(matches.map(match => match.row)).size < 2) continue;
      const summary = shipmentBreakdownText(panel, dimension);
      if (!summary) continue;
      const first = matches[0].index;
      paragraphs[first] = summary;
      summaries.add(first);
      for (const match of matches.slice(1)) paragraphs[match.index] = "";
    }
    const prose = [];
    for (const [index, paragraph] of paragraphs.entries()) {
      const text = answerText(paragraph);
      if (!text) continue;
      if (summaries.has(index) && prose.length) prose[prose.length - 1] += " " + text;
      else prose.push(text);
    }
    return prose.join("\n\n");
  }
  function responseText(data) {
    if (explanationResult(data)) return answerText(data.answer);
    if (data.filters?.codigo && data.status !== "ok") return "";
    if (data.status === "ok" && data.answer && ["summary", "report", "dashboard"].includes(data.response_type)) {
      return reportText(data);
    }
    return answerText(data.answer);
  }
  async function downloadPDF(event, link, label, status, format = "PDF", mime = "application/pdf") {
    event.preventDefault();
    if (link.getAttribute("aria-busy") === "true" || sessionInvalid) return;
    const controller = new AbortController();
    controllers.add(controller);
    link.setAttribute("aria-busy", "true");
    link.setAttribute("aria-disabled", "true");
    const originalLabel = label.textContent;
    label.textContent = "Preparando " + format + "…";
    status.textContent = "Estamos preparando tu documento.";
    try {
      const response = await fetch(link.href, {credentials:"same-origin", signal:controller.signal,
        headers:{Accept:mime, "X-Bolipost-User":apiIdentity}});
      if (response.redirected || response.status === 401 || response.headers.get("X-Bolipost-User") !== apiIdentity) {
        invalidateSession();
        return;
      }
      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(data?.error?.message || "No se pudo descargar el archivo. Vuelve a intentarlo.");
      }
      if (!response.headers.get("Content-Type")?.includes(mime)) throw new Error("El servidor no devolvió un archivo válido. Vuelve a intentarlo.");
      const blob = await response.blob();
      if (controller.signal.aborted || sessionInvalid) return;
      const url = URL.createObjectURL(blob), file = el("a");
      file.href = url;
      file.download = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") || "")?.[1] || "reporte-bolipost.pdf";
      document.body.append(file); file.click(); file.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      status.textContent = format + " listo. Revisa tus descargas.";
      announce(status.textContent);
    } catch (error) {
      if (error.name !== "AbortError") { status.textContent = error.message; announce(error.message); }
    } finally {
      controllers.delete(controller);
      link.removeAttribute("aria-busy"); link.removeAttribute("aria-disabled");
      label.textContent = originalLabel;
    }
  }
  function addServiceComparison(card, panels) {
    if (!panels || panels.length < 2) return false;
    const columns = panels[0].columns;
    const serviceName = panel => /^Comparaci[oó]n\s+(EMS|CERTI|CONTRATO|INT|ORDI)$/i.exec(panel.title || "")?.[1].toUpperCase();
    if (!columns || columns.length < 2 || columns.length > 6 ||
        new Set(panels.map(serviceName)).size !== panels.length ||
        !panels.every(panel => serviceName(panel) && panel.status === "ok" && !panel.chart &&
          !panel.has_more && (panel.page || 1) === 1 && panel.row_count === 1 && panel.rows?.length === 1 &&
          JSON.stringify(panel.columns) === JSON.stringify(columns) &&
          columns.every(column => metricNumber(panel.rows[0][column]) !== null && metricNumber(panel.rows[0][column]) >= 0))) return false;
    const table = el("table", null, "service-comparison"), head = el("thead"), header = el("tr");
    table.setAttribute("aria-label", "Comparación por servicio");
    for (const label of ["Servicio", ...columns.map(columnLabel)]) {
      const cell = el("th", label); cell.scope = "col"; header.append(cell);
    }
    head.append(header); table.append(head);
    const body = el("tbody");
    for (const panel of panels) {
      const row = el("tr"), label = el("th", serviceName(panel)); label.scope = "row";
      row.append(label);
      const largest = Math.max(...columns.map(column => metricNumber(panel.rows[0][column])));
      for (const column of columns) {
        const value = metricNumber(panel.rows[0][column]);
        const cell = el("td"), track = el("span", null, "comparison-track"), fill = el("span", null, "comparison-fill");
        cell.append(el("span", new Intl.NumberFormat("es-BO", {maximumFractionDigits:20}).format(value), "comparison-value"));
        track.setAttribute("aria-hidden", "true");
        fill.style.width = (largest ? value / largest * 100 : 0) + "%";
        track.append(fill); cell.append(track); row.append(cell);
      }
      body.append(row);
    }
    table.append(body);
    const scroll = el("div", null, "table-scroll service-comparison-scroll"); scroll.tabIndex = 0;
    scroll.setAttribute("role", "region"); scroll.setAttribute("aria-label", "Comparación por servicio");
    scroll.append(table); card.append(scroll);
    return true;
  }
  function addCompactResults(card, panels) {
    if (!panels || panels.length < 2) return false;
    const column = panels[0].columns?.[0];
    if (!column || !panels.every(panel => panel.status === "ok" && !panel.chart &&
        !panel.has_more && panel.row_count === 1 && panel.rows?.length === 1 &&
        panel.columns?.length === 1 && panel.columns[0] === column &&
        typeof panel.rows[0][column] === "number" && Number.isFinite(panel.rows[0][column]))) return false;
    const table = el("table", null, "compact-results"), head = el("thead"), header = el("tr");
    table.setAttribute("aria-label", "Resultados por consulta");
    for (const label of ["Consulta", columnLabel(column)]) {
      const th = el("th", label); th.scope = "col"; header.append(th);
    }
    head.append(header); table.append(head);
    const body = el("tbody");
    for (const panel of panels) {
      const row = el("tr"), label = el("th", panel.title || "Consulta"); label.scope = "row";
      row.append(label, el("td", printable(panel.rows[0][column]))); body.append(row);
    }
    table.append(body); card.append(table);
    return true;
  }
  function addDataDownloads(actions, data, panelIndex, compact = false) {
    if (!data.id || data.response_type === "help" || !["ok", "no_matches", "empty_table"].includes(data.status)) return;
    const formats = [
      ["csv", "CSV", "text/csv", "Exportar CSV · todas las filas de este panel"],
      ["xlsx", "Excel", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "Exportar Excel · todas las filas del informe"]
    ];
    for (const [extension, name, mime, hint] of formats) {
      if (skills[extension] === false || panelIndex !== undefined && extension !== "csv") continue;
      const link = el("a", null, "question-action data-download");
      const label = el("span", name);
      const status = el("span", "", "report-export-status");
      status.setAttribute("role", "status");
      link.append(label); link.title = hint; link.setAttribute("aria-label", hint);
      const query = extension === "csv" || panelIndex !== undefined ? "?panel=" + (panelIndex ?? data.panel_index ?? 0) : "";
      link.href = "/api/results/" + encodeURIComponent(data.id) + "/" + extension + "/" + query;
      if (extension === "csv" && compact && data.panels?.length > 1) {
        const select = el("select", null, "csv-panel-select");
        select.setAttribute("aria-label", "Panel para exportar CSV");
        for (const panel of data.panels) {
          const option = el("option", panel.title);
          option.value = panel.index; select.append(option);
        }
        select.addEventListener("change", () => {
          link.href = "/api/results/" + encodeURIComponent(data.id) + "/csv/?panel=" + select.value;
          link.title = "Exportar CSV · " + select.selectedOptions[0].textContent;
          link.setAttribute("aria-label", link.title);
        });
        actions.append(select);
      }
      link.addEventListener("click", event => downloadPDF(event, link, label, status, name, mime));
      actions.append(link, status);
    }
  }
  function renderResult(host, data, options = {}) {
    const branchCodes = ["sucursal_codigo", "codigo_sucursal", "codigoSucursal"];
    if (!options.readOnly && !options.isPanel && !options.branchNamesRefreshed && data.id &&
        (data.panels?.length ? data.panels : [data]).some(panel => panel.refresh_branch_names ||
          panel.source_tables?.includes("sucursales") && panel.columns?.some(column => branchCodes.includes(column)))) {
      const token = epoch;
      const query = new URLSearchParams({page:String(data.page || 1)});
      if (data.panels?.length) query.set("panel_pages", data.panels.map(panel => panel.index + ":" + (panel.page || 1)).join(","));
      api("/api/results/" + encodeURIComponent(data.id) + "/?" + query).then(fresh => {
        if (token === epoch && host.isConnected) renderResult(host, fresh, {...options, branchNamesRefreshed:true});
      }).catch(() => {});
    }
    charts.forEach(chart => { if (host.contains(chart.canvas)) { chart.destroy(); charts.delete(chart); } });
    host.replaceChildren();
    const card = el(options.isPanel ? "section" : "article", null, options.isPanel ? "result-section" : "result-card"), head = el("div", null, "result-head");
    const clarification = data.status === "error" && data.error?.code === "clarification";
    if (!options.isPanel) {
      const title = el("div", null, "result-title");
      title.append(icon(clarification ? "chat" : "catalog"), el("h2", data.title || "Resultado de la consulta"));
      head.append(title);
      card.dataset.state = clarification ? "clarification" : data.status;
    } else head.append(el("h3", data.title || "Resultado de la consulta"));
    const narrativeText = responseText(data);
    if (narrativeText && !(data.status === "error" && narrativeText === data.error?.message)) {
      const narrative = el("div", null, "result-narrative");
      for (const paragraph of narrativeText.split(/\n\s*\n/)) {
        if (paragraph.trim()) narrative.append(el("p", paragraph));
      }
      head.append(narrative);
    }
    const note = data.note ?? data.analysis?.note;
    if (note) head.append(el("p", note, "result-meta"));
    if (data.filters?.choose_service && data.panels?.length > 1) {
      head.append(el("p", "El código " + data.filters.codigo + " tiene varios registros. Elige un servicio para precisar su rastreo.", "result-meta"));
    }
    if (data.demo && !options.isPanel) head.append(el("div", "Datos de demostración", "result-meta"));
    card.append(head);
    const explanation = explanationResult(data);
    const dashboard = !options.isPanel && !explanation && shipmentDashboard(data);
    const categorical = !options.isPanel && !explanation && !dashboard && categoricalDashboard(data);
    const states = {no_matches:"No se encontraron coincidencias para estos filtros.", empty_table:"La tabla de origen está vacía.", cancelled:"La consulta fue cancelada.", error:data.error?.message || "No se pudo ejecutar la consulta."};
    if (states[data.status]) card.append(el("div", states[data.status], "result-state" + (data.status === "error" && !clarification ? " error-text" : "")));
    const compact = !options.isPanel && !explanation && !dashboard && (addServiceComparison(card, data.panels) || addCompactResults(card, data.panels));
    if (!explanation && !dashboard && !categorical && !compact && data.primary_title && data.panels?.length > 1 && data.primary_title !== data.title) card.append(el("h3", data.primary_title, "panel-title"));
    if (dashboard) addShipmentDashboard(card, dashboard);
    else if (categorical) addCategoricalDashboard(card, data, categorical);
    else if (!explanation && !compact) {
      addChart(card, data);
      if (!addDailyVolume(card, data)) addTable(card, data, {record:true, formatted:options.formatted});
    }
    if (!explanation && !compact && !options.isPanel && data.panels?.length > 1) {
      const panels = el("div", null, "report-panels");
      for (const panel of data.panels.slice(1)) {
        if (dashboard?.families.some(item => item.panel.index === panel.index)) continue;
        if (categorical && panel.status === "ok" && !panel.chart && !panel.has_more && (panel.page || 1) === 1 &&
            panel.columns?.length === 1 && panel.columns[0] === categorical.count && panel.row_count === 1 &&
            panel.rows?.length === 1 && metricNumber(panel.rows[0][categorical.count]) === categorical.total) continue;
        const panelHost = el("div", null, "report-panel");
        panels.append(panelHost);
        renderResult(panelHost, {...panel, id:data.id, demo:data.demo, created_at:data.created_at, panels:[], answer:panel.filters?.codigo ? panel.answer : ""}, {...options, isPanel:true, panelIndex:panel.index, formatted:!!dashboard || options.formatted});
        if (dashboard && panel.chart?.kind === "line" && panel.columns.some(column => /^(mes|month)$/i.test(column))) {
          panelHost.classList.add("monthly-panel");
          const table = panelHost.querySelector(".table-scroll");
          if (table) {
            const detail = el("section", null, "monthly-detail");
            detail.append(el("h3", "Detalle mensual"), table);
            panelHost.append(detail);
          }
        }
      }
      if (panels.childElementCount) card.append(panels);
    }
    if (options.isPanel || options.readOnly) {
      if (options.isPanel && !options.readOnly) {
        const actions = el("div", null, "result-actions result-icon-actions section-actions");
        addDataDownloads(actions, data, options.panelIndex);
        card.append(actions);
      }
      host.append(card);
      return;
    }
    const actions = el("div", null, "result-actions result-icon-actions");
    actions.setAttribute("role", "group");
    actions.setAttribute("aria-label", "Acciones de la respuesta");
    const copyLabel = explanation ? "Copiar explicación" : data.panels?.length > 1 ? "Copiar informe" : "Copiar resultado";
    let copyTimer;
    const copy = button("", async () => {
      const panels = data.panels?.length ? data.panels : [data];
      const text = [data.title, responseText(data), data.note ?? data.analysis?.note, data.warning ?? data.analysis?.warning,
        ...(explanation ? [] : panels.flatMap(panel => [panel.title,
          (panel.columns || []).map(columnLabel).join("\t"), ...(panel.rows || []).map(row => (panel.columns || []).map(c => printable(row[c])).join("\t"))])),
        options.restored ? "Resultado histórico guardado en el navegador." : ""].filter(Boolean).join("\n");
      try {
        await navigator.clipboard.writeText(text);
        clearTimeout(copyTimer);
        copy.replaceChildren(icon("check")); copy.dataset.copied = "true"; copy.title = "Resultado copiado";
        announce("Resultado copiado.");
        copyTimer = setTimeout(() => {
          copy.replaceChildren(icon("copy")); delete copy.dataset.copied; copy.title = copyLabel;
        }, 2200);
      }
      catch { announce("No se pudo copiar. Selecciona el texto del resultado para copiarlo."); }
    }, "question-action");
    copy.append(icon("copy"));
    copy.setAttribute("aria-label", copyLabel); copy.title = copyLabel;
    actions.append(copy);
    if (data.id && data.status === "ok" && data.response_type !== "help" && skills.pdf !== false) {
      const multi = data.panels?.length > 1;
      const downloadLabel = multi ? "Descargar PDF · páginas visibles del informe" : "Descargar PDF · página " + (data.page || 1);
      const link = el("a", null, "question-action pdf-download");
      const label = el("span", "Descargar PDF", "sr-only");
      link.append(icon("download"), label);
      link.setAttribute("aria-label", downloadLabel); link.title = downloadLabel;
      const query = new URLSearchParams({page:String(data.page || 1)});
      if (multi) query.set("panel_pages", data.panels.map(panel => panel.index + ":" + (panel.page || 1)).join(","));
      link.href = "/api/results/" + encodeURIComponent(data.id) + "/pdf/?" + query;
      if (multi) link.title = "Incluye la página visible de cada panel, no todas las filas del respaldo.";
      link.target = "_blank"; link.rel = "noopener";
      const status = el("p", "", "report-export-status");
      status.setAttribute("role", "status"); status.setAttribute("aria-live", "polite");
      link.addEventListener("click", event => downloadPDF(event, link, label, status));
      actions.append(link, status);
    }
    addDataDownloads(actions, data, undefined, compact);
    host.append(card, actions);
  }
  async function loadCatalog() {
    $("catalog-list").replaceChildren(el("div", "Cargando catálogo…", "result-state"));
    try {
      const data = await api("/api/catalog/"); catalog = data.tables || [];
      renderCatalog();
    } catch (error) { if (error.name !== "AbortError") renderError($("catalog-list"), error.message, loadCatalog); }
  }
  function renderCatalog() {
    const query = $("catalog-search").value.toLocaleLowerCase("es").trim();
    const matches = catalog.filter(t => t.name.toLocaleLowerCase("es").includes(query) || t.columns.some(c => c.name.toLocaleLowerCase("es").includes(query)));
    $("catalog-count").textContent = matches.length + " de " + catalog.length + " tablas";
    $("catalog-list").replaceChildren();
    if (!matches.length) $("catalog-list").append(el("div", "No hay tablas o campos que coincidan con la búsqueda.", "empty-state"));
    for (const table of matches) {
      const details = el("details", null, "catalog-table"), summary = el("summary");
      summary.append(el("strong", table.name)); details.append(summary);
      const rows = table.columns.map(c => ({Campo:c.name, Tipo:c.type}));
      addTable(details, {columns:["Campo","Tipo"], rows});
      const relations = el("div", null, "relations"); relations.append(el("strong", "Relaciones"));
      if (!table.relations?.length) relations.append(el("p", "Sin relaciones documentadas."));
      for (const relation of table.relations || []) relations.append(el("p", relation.column + " → " + relation.table + "." + relation.target + (relation.inferred ? " (inferida)" : "")));
      details.append(relations); $("catalog-list").append(details);
    }
  }
  function applyTheme(value) {
    document.documentElement.dataset.theme = value === "system" ? (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light") : value;
    $("theme-toggle").replaceChildren(icon(document.documentElement.dataset.theme === "dark" ? "sun" : "moon"));
    $("theme-toggle").setAttribute("aria-label", "Cambiar tema. Tema actual: " + {system:"sistema",light:"claro",dark:"oscuro"}[value]);
    $("theme-toggle").title = "Tema: " + {system:"sistema",light:"claro",dark:"oscuro"}[value];
    $("theme-toggle").dataset.value = value;
    [...charts].forEach(c => c.refreshTheme());
  }
  // Review saved messages with the chat's renderer, without starting a chat session.
  if ($("inspect-conversation")) {
    const host = $("inspect-messages");
    host.replaceChildren();
    for (const message of JSON.parse($("inspect-conversation").textContent)) {
      const node = el("div", null, "message");
      if (message.kind === "question") {
        node.classList.add("question-entry");
        node.append(el("div", message.text, "question-message"));
      } else if (message.result) {
        renderResult(node, message.result, {readOnly:true});
      } else continue;
      host.append(node);
    }
    if (!host.children.length) host.append(el("p", "Esta conversación todavía no contiene mensajes.", "empty-state"));
    new MutationObserver(() => charts.forEach(chart => chart.refreshTheme()))
      .observe(document.documentElement, {attributes:true, attributeFilter:["data-theme"]});
    return;
  }
  $("theme-toggle").addEventListener("click", () => {
    const values = ["system", "light", "dark"];
    const next = values[(values.indexOf($("theme-toggle").dataset.value) + 1) % values.length];
    applyTheme(next); try { localStorage.setItem("bolipost-theme", next); } catch { /* Theme remains usable without storage. */ }
  });
  try { const theme = localStorage.getItem("bolipost-theme"); applyTheme(["light","dark"].includes(theme) ? theme : "system"); } catch { applyTheme("system"); }
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if ($("theme-toggle").dataset.value === "system") applyTheme("system");
  });
  $("menu-toggle").addEventListener("click", () => {
    const open = $("sidebar").classList.toggle("open");
    $("sidebar-backdrop").hidden = !open;
    $("menu-toggle").setAttribute("aria-expanded", String(open));
    if (open) $("menu-close").focus();
  });
  ["menu-close", "sidebar-backdrop"].forEach(id => $(id).addEventListener("click", () => { closeSidebar(); $("menu-toggle").focus(); }));
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && $("sidebar").classList.contains("open")) { closeSidebar(); $("menu-toggle").focus(); }
  });
  document.querySelectorAll("[data-view]").forEach(n => n.addEventListener("click", () => showView(n.dataset.view)));
  $("new-chat").addEventListener("click", newConversation);
  $("history-search").addEventListener("input", renderHistory);
  $("catalog-search").addEventListener("input", renderCatalog);
  $("chat-form").querySelector(".send").addEventListener("click", () => {
    if (busy && active?.isChat) cancelJob(active);
  });
  $("chat-form").addEventListener("submit", async event => {
    event.preventDefault();
    await historyReady;
    const question = $("question").value.trim(); if (!question || busy) return;
    submitJob("/api/chat/", {question, ...chatContext()}, $("messages"), question);
  });
  $("question").addEventListener("keydown", event => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); $("chat-form").requestSubmit(); }
  });
  document.querySelectorAll("[data-question]").forEach(n => n.addEventListener("click", () => {
    $("question").value = n.dataset.question; $("chat-form").requestSubmit();
  }));
  $("tracking-form").addEventListener("submit", event => {
    event.preventDefault(); const code = $("tracking-code").value.trim();
    const service = $("tracking-service").value;
    const codes = code.split(/[,;\n]+/).map(value => value.trim()).filter(Boolean);
    if (codes.length > 6) { announce("Puedes consultar hasta seis códigos a la vez."); return; }
    const payload = codes.length > 1 ? {codes} : {code:codes[0]};
    if (code && !busy) submitJob("/api/tracking/", {...payload, ...(service ? {service} : {})}, $("tracking-results"));
  });
  $("dashboard-form").addEventListener("submit", event => {
    event.preventDefault(); if (!busy) submitJob("/api/dashboard/", {metric:$("metric").value}, $("dashboard-results"));
  });
  $("logout-form").addEventListener("submit", () => {
    stopActive(); conversation = null; conversations = []; if (db) db.close();
    $("messages").replaceChildren(); $("history-list").replaceChildren();
  });
  window.addEventListener("pagehide", () => stopActive());
  window.addEventListener("offline", () => { $("connection-state").textContent = "Sin conexión"; });
  window.addEventListener("online", checkStatus);
  async function checkStatus() {
    try {
      const status = await api("/api/status/");
      skills = status.skills || skills;
      $("environment-notice").hidden = status.data_mode !== "demo";
      $("connection-state").textContent = status.data_mode === "demo" ? "Datos de demostración" : "Base institucional · Respaldo";
      const warnings = [];
      if (status.data_mode !== "demo" && !status.database_configured) warnings.push("La base postal aún no está configurada. Solicita su configuración al administrador.");
      if (!status.assistant_configured) warnings.push("El asistente de IA requiere configurar el proveedor. Puedes usar las herramientas disponibles de rastreo y estadísticas.");
      $("configuration-notice").textContent = warnings.join(" ");
      $("configuration-notice").hidden = !warnings.length;
    } catch (error) { if (error.name !== "AbortError") $("connection-state").textContent = error.message; }
  }
  const historyReady = openHistory();
  document.querySelectorAll('a[href="/system/"], a[href="/trash/"]').forEach(link => link.addEventListener("click", async event => {
    if (!pendingSaves || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    try { await saveQueue; window.location.assign(link.href); }
    catch (error) { announce(error.message); }
  }));
  window.addEventListener("popstate", async () => { await historyReady; restoreConversationFromUrl(); });
  historyReady.then(() => {
    if (sessionInvalid) return;
    $("question").disabled = false;
    setBusy(false);
    $("chat-form").removeAttribute("aria-busy");
    $("question").focus();
    checkStatus();
  });
})();
