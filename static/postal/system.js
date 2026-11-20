(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const backupPreview = $('backup-preview-list');
  if (backupPreview) {
    const updateBackupPreview = () => {
      const selected = document.querySelector('.catalog-backup-option input:checked');
      backupPreview.querySelectorAll('[data-preview-model]').forEach(row => {
        row.hidden = row.dataset.previewModel === selected?.value;
      });
      const option = selected?.closest('.catalog-backup-option');
      $('backup-preview-new').querySelector('strong').textContent = option ?
        option.querySelector('strong').textContent + ' · ' + option.querySelector('.catalog-backup-model').textContent :
        'Seleccione un modelo arriba';
    };
    document.querySelectorAll('.catalog-backup-option input').forEach(input => input.addEventListener('change', updateBackupPreview));
    updateBackupPreview();
  }
  const orderForm = $('catalog-order-form'), orderList = $('catalog-sort-list'), orderToggle = $('catalog-reorder-toggle');
  if (orderForm && orderList && orderToggle) {
    let editing = false, dragging = null, saving = false;
    const rows = () => [...orderList.querySelectorAll('[data-model-id]')];
    let savedOrder = rows();
    const status = $('catalog-order-status');
    function labels() {
      rows().forEach((row, index) => {
        row.querySelector('.catalog-chain-position').textContent = String(index + 1);
        row.querySelector('.catalog-chain-role').textContent = index ? 'Respaldo ' + index : 'Principal';
      });
    }
    async function saveOrder() {
      if (saving || rows().every((row, index) => row === savedOrder[index])) return;
      saving = true;
      orderList.setAttribute('aria-busy', 'true');
      orderToggle.disabled = true;
      status.textContent = 'Guardando orden…';
      const body = new FormData(orderForm);
      rows().forEach(row => body.append('model_ids', row.dataset.modelId));
      try {
        const response = await fetch(location.href, {method:'POST', body, credentials:'same-origin', headers:{Accept:'application/json'}});
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || 'No se pudo guardar el orden.');
        savedOrder = rows();
        status.textContent = 'Orden guardado. El primero es el principal.';
      } catch (error) {
        savedOrder.forEach(row => orderList.append(row));
        labels();
        status.textContent = error.message || 'No se pudo guardar. Intente de nuevo.';
      } finally {
        saving = false;
        orderToggle.disabled = false;
        orderList.removeAttribute('aria-busy');
      }
    }
    orderToggle.addEventListener('click', () => {
      editing = !editing;
      orderToggle.setAttribute('aria-pressed', String(editing));
      orderToggle.textContent = editing ? 'Terminar edición' : 'Reordenar';
      orderList.querySelectorAll('.catalog-drag-handle').forEach(handle => { handle.hidden = !editing; });
      if (editing) {
        status.textContent = 'Arrastre una fila o use las flechas del teclado. Se guarda al moverla.';
        orderList.querySelector('.catalog-drag-handle')?.focus();
      } else location.reload();
    });
    orderList.addEventListener('dragstart', event => {
      const handle = event.target.closest('.catalog-drag-handle');
      if (!editing || saving || !handle) { event.preventDefault(); return; }
      dragging = handle.closest('[data-model-id]');
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', dragging.dataset.modelId);
      event.dataTransfer.setDragImage(dragging, 24, 20);
      dragging.classList.add('is-dragging');
    });
    orderList.addEventListener('dragover', event => {
      if (!dragging) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = 'move';
      const target = event.target.closest('[data-model-id]');
      if (!target || target === dragging) return;
      const bounds = target.getBoundingClientRect();
      orderList.insertBefore(dragging, event.clientY < bounds.top + bounds.height / 2 ? target : target.nextSibling);
      labels();
    });
    orderList.addEventListener('drop', event => {
      if (!dragging) return;
      event.preventDefault();
      dragging.classList.remove('is-dragging');
      dragging = null;
      saveOrder();
    });
    orderList.addEventListener('dragend', () => {
      if (!dragging) return;
      dragging.classList.remove('is-dragging');
      dragging = null;
      savedOrder.forEach(row => orderList.append(row));
      labels();
    });
    orderList.addEventListener('keydown', event => {
      const handle = event.target.closest('.catalog-drag-handle');
      if (!handle || !editing || saving || !['ArrowUp', 'ArrowDown'].includes(event.key)) return;
      event.preventDefault();
      const row = handle.closest('[data-model-id]');
      const sibling = event.key === 'ArrowUp' ? row.previousElementSibling : row.nextElementSibling;
      if (!sibling?.dataset.modelId) return;
      orderList.insertBefore(row, event.key === 'ArrowUp' ? sibling : sibling.nextSibling);
      handle.focus();
      labels();
      saveOrder();
    });
    orderForm.addEventListener('submit', event => event.preventDefault());
  }
  const secretToggle = document.querySelector('[data-secret-toggle]');
  if (secretToggle) {
    const input = $(secretToggle.getAttribute('aria-controls'));
    const setVisible = visible => {
      input.type = visible ? 'text' : 'password';
      secretToggle.textContent = visible ? 'Ocultar' : 'Mostrar';
      secretToggle.setAttribute('aria-label', visible ? 'Ocultar clave API' : 'Mostrar clave API');
    };
    const clearSecret = () => {
      input.value = '';
      setVisible(false);
    };
    secretToggle.hidden = false;
    secretToggle.addEventListener('click', () => setVisible(input.type === 'password'));
    secretToggle.closest('dialog').addEventListener('close', clearSecret);
    window.addEventListener('pagehide', clearSecret);
  }
  document.querySelectorAll('.users-dialog:not(.table-confirm-dialog)').forEach(dialog => {
    let opener;
    function open(trigger) {
      opener = trigger;
      dialog.showModal();
      (dialog.querySelector('[aria-invalid="true"]') || dialog.querySelector('input:not([type=hidden])'))?.focus();
    }
    document.querySelectorAll('[data-open-dialog="' + dialog.id + '"]').forEach(trigger => {
      trigger.addEventListener('click', event => { event.preventDefault(); open(trigger); });
    });
    dialog.querySelectorAll('[data-close-dialog]').forEach(button => {
      button.addEventListener('click', event => { event.preventDefault(); dialog.close(); });
    });
    dialog.addEventListener('close', () => {
      if (dialog.hasAttribute('data-auto-open')) {
        const url = new URL(dialog.dataset.returnUrl || location.href, location.href);
        ['new', 'edit_user', 'reset_user'].forEach(key => url.searchParams.delete(key));
        url.hash = '';
        history.replaceState(null, '', url);
      }
      (opener || document.querySelector(dialog.dataset.returnFocus || '.users-directory-heading .button, .catalog-add-provider'))?.focus();
    });
    if (dialog.hasAttribute('data-auto-open')) open();
  });
  const period = $('analytics-days'), customRange = $('analytics-custom');
  if (period && customRange) {
    const start = customRange.querySelector('[name=start]'), end = customRange.querySelector('[name=end]');
    const syncRange = () => {
      const custom = period.value === 'custom';
      customRange.hidden = !custom;
      customRange.disabled = !custom;
      end.min = start.value;
    };
    period.addEventListener('change', () => { syncRange(); if (!customRange.hidden) start.focus(); });
    start.addEventListener('change', syncRange);
    syncRange();
  }
  const apiIdentity = JSON.parse($("api-identity").textContent);
  const menu = $("system-menu"), sidebar = $("system-sidebar"), backdrop = $("system-backdrop");
  const mobileNav = window.matchMedia('(max-width:1100px)');
  const collapse = $("system-collapse");
  let navCollapsed = document.documentElement.dataset.adminNav === 'collapsed';
  function syncCollapsedNav() {
    document.documentElement.dataset.adminNav = navCollapsed ? 'collapsed' : 'expanded';
    const label = navCollapsed ? 'Expandir barra lateral' : 'Contraer barra lateral';
    collapse?.setAttribute('aria-expanded', String(!navCollapsed));
    collapse?.setAttribute('aria-label', label);
    collapse?.setAttribute('title', label);
  }
  sidebar?.querySelectorAll('.system-nav a, .system-chat-shortcut').forEach(link => {
    const label = link.textContent.trim().replace(/\s+/g, ' ');
    link.setAttribute('aria-label', label);
    link.setAttribute('title', label);
  });
  collapse?.addEventListener('click', () => {
    navCollapsed = !navCollapsed;
    syncCollapsedNav();
    try { localStorage.setItem('bolipost-admin-sidebar', navCollapsed ? 'collapsed' : 'expanded'); } catch { /* The current state still works. */ }
  });
  syncCollapsedNav();
  function syncMenuAccessibility() {
    if (sidebar) sidebar.inert = mobileNav.matches && menu?.getAttribute('aria-expanded') !== 'true';
  }
  function closeMenu() {
    sidebar?.classList.remove("is-open");
    document.body.classList.remove("system-menu-open");
    if (backdrop) backdrop.hidden = true;
    menu?.setAttribute("aria-expanded", "false");
    syncMenuAccessibility();
  }
  menu?.addEventListener("click", () => {
    const open = menu.getAttribute("aria-expanded") !== "true";
    if (!open) { closeMenu(); return; }
    sidebar.classList.add("is-open"); backdrop.hidden = false;
    document.body.classList.add("system-menu-open"); menu.setAttribute("aria-expanded", "true");
    syncMenuAccessibility();
    sidebar.querySelector('a[aria-current="page"], a')?.focus();
  });
  backdrop?.addEventListener("click", closeMenu);
  document.addEventListener("keydown", event => {
    if (event.key === "Escape" && menu?.getAttribute("aria-expanded") === "true") { closeMenu(); menu.focus(); }
    if (event.key === 'Tab' && menu?.getAttribute('aria-expanded') === 'true') {
      const links = [...sidebar.querySelectorAll('a[href], button:not([disabled]), summary')].filter(node => node.getClientRects().length);
      if (event.shiftKey && document.activeElement === links[0]) { event.preventDefault(); links.at(-1).focus(); }
      else if (!event.shiftKey && document.activeElement === links.at(-1)) { event.preventDefault(); links[0].focus(); }
    }
  });
  mobileNav.addEventListener('change', () => { closeMenu(); syncMenuAccessibility(); });
  syncMenuAccessibility();
  sidebar?.querySelectorAll("a").forEach(link => link.addEventListener("click", closeMenu));
  const numbers = new Intl.NumberFormat("es-BO", {maximumFractionDigits:0});
  function formatNumbers() { document.querySelectorAll('[data-number]').forEach(node => {
    if (node.dataset.number !== "" && Number.isFinite(Number(node.dataset.number))) node.textContent = numbers.format(Number(node.dataset.number));
  }); }
  formatNumbers();
  const dashboard = $("dashboard-data");
  let chartData = dashboard ? JSON.parse(dashboard.textContent) : null;
  function drawCharts() {
    if (!chartData || !window.Charts) return;
    for (const [id, key, label] of [["tokens-chart", "tokens", "Tokens informados"], ["calls-chart", "calls", "Generaciones registradas"]]) {
      const target = $(id);
      if (!target) continue;
      target.replaceChildren();
      const maximum = Math.max(0, ...chartData.daily.map(day => day[key] || 0));
      const rawStep = Math.max(1, maximum / 4), magnitude = 10 ** Math.floor(Math.log10(rawStep));
      const step = [1, 2, 5, 10].map(value => value * magnitude).find(value => value >= rawStep);
      const count = Math.max(2, Math.floor(maximum / step) + 1);
      Charts.line(target, {labels:chartData.daily.map(day => day.label),
        series:[{name:label, values:chartData.daily.map(day => day[key])}],
        yTicks:Array.from({length:count + 1}, (_, index) => index * step),
        format:Charts.fmt.int, tickFormat:Charts.fmt.compact, height:205, fill:true});
    }
    document.querySelectorAll('.dashboard-ranking').forEach(ranking => {
      const bars = [...ranking.querySelectorAll('[data-bar]')];
      const maximum = Math.max(0, ...bars.map(bar => Number(bar.dataset.bar)));
      bars.forEach(bar => { bar.style.width = (maximum ? Number(bar.dataset.bar) / maximum * 100 : 0) + "%"; });
    });
  }
  function animateDashboard() {
    const reduced = window.matchMedia('(prefers-reduced-motion:reduce)');
    if (reduced.matches || !window.IntersectionObserver || !Element.prototype.animate) return;
    const styles = getComputedStyle($('system-content'));
    const duration = parseFloat(styles.getPropertyValue('--dashboard-motion-duration')) || 500;
    const stagger = parseFloat(styles.getPropertyValue('--dashboard-motion-stagger')) || 40;
    const easing = styles.getPropertyValue('--dashboard-motion-easing').trim() || 'ease-out';
    const active = new Set();
    function play(element, frames, delay, time = duration) {
      const animation = element.animate(frames, {duration:time, delay, easing, fill:'backwards'});
      active.add(animation);
      animation.onfinish = animation.oncancel = () => active.delete(animation);
    }
    const observer = new IntersectionObserver(entries => {
      let index = 0;
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const card = entry.target, delay = Math.min(index++, 3) * stagger;
        observer.unobserve(card);
        play(card, [{opacity:0, transform:'translateY(12px)'}, {opacity:1, transform:'translateY(0)'}], delay);
        card.querySelectorAll('.kpi-big-num, .agent-node-card strong').forEach(value => {
          play(value, [{opacity:0, transform:'translateY(6px)'}, {opacity:1, transform:'translateY(0)'}], delay + stagger);
        });
        card.querySelectorAll('.dashboard-chart path[stroke][fill="none"]').forEach(path => {
          const length = path.getTotalLength();
          if (length > 0) play(path, [
            {strokeDasharray:String(length), strokeDashoffset:String(length)},
            {strokeDasharray:String(length), strokeDashoffset:'0'}
          ], delay, duration * 1.6);
        });
        card.querySelectorAll('.dashboard-chart path:not([stroke])').forEach(area => {
          play(area, [{opacity:0}, {opacity:area.getAttribute('opacity') || 1}], delay + stagger, duration * 1.6);
        });
        card.querySelectorAll('[data-bar]').forEach(bar => {
          play(bar, [{transform:'scaleX(0)', transformOrigin:'left center'}, {transform:'scaleX(1)', transformOrigin:'left center'}], delay, duration * 1.6);
        });
        card.querySelectorAll('.sla-donut circle[stroke-dasharray]').forEach(ring => {
          play(ring, [{strokeDasharray:'0 100'}, {strokeDasharray:ring.getAttribute('stroke-dasharray')}], delay, duration * 1.6);
        });
      }
    }, {threshold:0.08});
    document.querySelectorAll('.dashboard-metrics>.bento-cell, .dashboard-grid>.bento-cell').forEach(card => observer.observe(card));
    reduced.addEventListener('change', () => {
      if (!reduced.matches) return;
      observer.disconnect();
      active.forEach(animation => animation.cancel());
    });
  }
  let resizeTimer;
  if (chartData) {
    document.fonts.ready.then(() => { drawCharts(); animateDashboard(); });
    window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(drawCharts, 120); });
    const live = $('dashboard-live');
    const url = new URL(location.href);
    url.searchParams.set('live', '1');
    let refreshing = false, stopped = false;
    async function refreshDashboard() {
      if (document.hidden || refreshing || stopped) return;
      refreshing = true;
      try {
        const response = await fetch(url, {credentials:'same-origin', cache:'no-store',
          headers:{'X-Bolipost-User':apiIdentity}, signal:AbortSignal.timeout(10000)});
        if (response.redirected || response.status === 401 || response.status === 403 ||
            (response.ok && response.headers.get('X-Bolipost-User') !== apiIdentity)) {
          stopped = true;
          live.replaceChildren();
          window.location.reload();
          return;
        }
        if (!response.ok) return;
        const html = await response.text();
        const fragment = document.createElement('template');
        fragment.innerHTML = html;
        const data = fragment.content.querySelector('#dashboard-data');
        if (!data) return;
        const nextData = JSON.parse(data.textContent);
        const details = [...live.querySelectorAll('details')].map(node => node.open);
        // Leave the existing charts in place when the data has not changed.
        const previous = live.dataset.snapshot;
        if (previous === html) return;
        if (live.contains(document.activeElement)) return;
        live.replaceChildren(fragment.content);
        live.dataset.snapshot = html;
        live.querySelectorAll('details').forEach((node, index) => { node.open = details[index]; });
        chartData = nextData;
        formatNumbers();
        drawCharts();
      } catch { /* Keep the current values and retry after a temporary connection failure. */ }
      finally { refreshing = false; }
    }
    setInterval(refreshDashboard, 3000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshDashboard(); });
    window.addEventListener('online', refreshDashboard);
  }
  const tableConfirmation = $('table-confirmation');
  if (tableConfirmation) {
    let pendingForm;
    let confirmedForm;
    document.querySelectorAll('form[data-table-confirm-title]').forEach(form => {
      form.addEventListener('submit', event => {
        if (confirmedForm === form) return;
        event.preventDefault();
        if (pendingForm) return;

        $('table-confirm-title').textContent = form.dataset.tableConfirmTitle;
        $('table-confirm-action').textContent = form.dataset.tableConfirmAction;
        $('table-confirm-empty').hidden = form.elements.action.value !== 'table_columns'
          || Boolean(form.querySelector('input[name="columns"]:checked'));
        tableConfirmation.returnValue = '';
        tableConfirmation.showModal();
        pendingForm = form;
      });
    });
    tableConfirmation.addEventListener('close', () => {
      const form = pendingForm;
      pendingForm = null;
      if (!form || tableConfirmation.returnValue !== 'confirm') return;

      confirmedForm = form;
      try {
        form.requestSubmit();
      } finally {
        confirmedForm = null;
      }
    });
  }
  document.querySelectorAll("form[data-confirm]").forEach(form => form.addEventListener("submit", event => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  }));
  $("system-theme").addEventListener("click", () => {
    const theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = theme;
    drawCharts();
    try { localStorage.setItem("bolipost-theme", theme); } catch { /* Theme remains usable without storage. */ }
  });
  const list = $("trash-list");
  if (!list) return;
  const csrf = document.querySelector('[name="csrfmiddlewaretoken"]').value;
  let page = 1;
  async function api(url, post) {
    const response = await fetch(url, {method:post ? "POST" : "GET", credentials:"same-origin",
      headers:{"Accept":"application/json", "X-Bolipost-User":apiIdentity, ...(post ? {"Content-Type":"application/json", "X-CSRFToken":csrf} : {})},
      body:post ? "{}" : undefined});
    if (response.status === 401 || response.headers.get("X-Bolipost-User") !== apiIdentity) {
      window.location.replace("/accounts/login/"); throw new Error("La cuenta cambió. Inicie sesión de nuevo.");
    }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || "No se pudo completar la acción.");
    return data;
  }
  function fail(error) { $("trash-error").textContent = error.message; $("trash-error").hidden = false; $("trash-retry").hidden = false; }
  async function load() {
    $("trash-error").hidden = true; $("trash-retry").hidden = true;
    $("trash-more").disabled = true;
    try {
      const data = await api("/api/conversations/?trash=1&page=" + page);
      if (page === 1) list.replaceChildren();
      for (const chat of data.conversations) {
        const row = document.createElement("div"); row.className = "system-trash-row";
        const text = document.createElement("div"), title = document.createElement("strong"), date = document.createElement("p");
        title.textContent = chat.title;
        const expires = new Date(new Date(chat.deleted_at).getTime() + 30 * 86400000);
        date.textContent = "Eliminación definitiva: " + expires.toLocaleString("es-BO", {timeZone:"America/La_Paz"});
        text.append(title, date);
        const restore = document.createElement("button"); restore.type = "button"; restore.className = "button"; restore.textContent = "Restaurar";
        restore.addEventListener("click", async () => {
          restore.disabled = true;
          try {
            await api("/api/conversations/" + encodeURIComponent(chat.id) + "/restore/", true);
            page = 1; await load();
            $("system-announcement").textContent = "Conversación restaurada. Está disponible en el historial del chat.";
            $("system-announcement").hidden = false;
          } catch (error) { fail(error); restore.disabled = false; }
        });
        row.append(text, restore); list.append(row);
      }
      if (!list.children.length) { const empty = document.createElement("p"); empty.textContent = "No tienes conversaciones en la papelera."; list.append(empty); }
      $("trash-more").hidden = !data.has_more;
      page++;
    } catch (error) { fail(error); }
    finally { $("trash-more").disabled = false; }
  }
  $("trash-more").addEventListener("click", load);
  $("trash-retry").addEventListener("click", load);
  load();
})();
