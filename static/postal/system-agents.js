(() => {
  'use strict';
  const form = document.querySelector('.agents-workspace');
  if (!form?.dataset.editing) return;
  const tokenInput = form.querySelector('#id_AI_MAX_TOKENS');
  const range = form.querySelector('#agent-token-range');
  const fields = [...form.querySelectorAll('textarea, input[name]:not([type=hidden])')];
  const snapshot = () => JSON.stringify(fields.map(field => field.type === 'checkbox' ? field.checked : field.value));
  const initial = snapshot();
  const format = value => new Intl.NumberFormat('es-BO').format(value);
  const save = form.querySelector('[data-save]');
  const state = form.querySelector('[data-save-state]');
  let submitting = false;
  const dirty = () => snapshot() !== initial;
  form.querySelectorAll('[data-enhanced]').forEach(node => { node.hidden = false; });
  form.querySelectorAll('[data-agent]').forEach(card => {
    const textarea = card.querySelector('textarea');
    card.querySelector('input[type=checkbox]').setAttribute('role', 'switch');
    const hint = card.querySelector('[data-agent-hint]');
    hint.id = `${textarea.id}-hint`;
    textarea.setAttribute('aria-describedby', hint.id);
    textarea.placeholder = textarea.name === 'PLANNER_INSTRUCTIONS'
      ? 'Ej.: Prioriza los filtros de fecha y sucursal indicados en la pregunta.'
      : 'Ej.: Resume los hallazgos sin repetir las filas de las tablas.';
  });
  function sync() {
    form.querySelectorAll('[data-agent]').forEach(card => {
      const toggle = card.querySelector('input[type=checkbox]');
      const textarea = card.querySelector('textarea');
      card.querySelector('[data-agent-state]').textContent = toggle.checked ? 'Activo' : 'Inactivo';
      card.querySelector('[data-character-count]').textContent = `${format(textarea.value.length)} / 4.000`;
      textarea.readOnly = !toggle.checked;
      card.querySelector('[data-agent-hint]').textContent = toggle.checked
        ? 'Complementan las reglas existentes de SQL y evidencia.'
        : 'Instrucciones conservadas. Activa el agente para editarlas.';
      card.querySelectorAll('[data-example]').forEach(button => { button.disabled = !toggle.checked; });
    });
    const planner = form.querySelector('#id_PLANNER_ENABLED')?.checked;
    const analyst = form.querySelector('#id_ANALYST_ENABLED')?.checked;
    if (planner !== undefined) form.querySelector('[data-preview-planner]').textContent = planner ? 'Activo · Planificación mediante IA' : 'Inactivo · Consultas del chat deshabilitadas';
    if (analyst !== undefined) form.querySelector('[data-preview-analyst]').textContent = analyst ? 'Activo · Explicación de los resultados' : 'Inactivo · Solo tablas verificadas';
    if (tokenInput) {
    const valid = tokenInput.validity.valid && tokenInput.value !== '';
    const tokens = Number(tokenInput.value);
    if (valid) range.value = tokens;
    form.querySelector('[data-preview-budget]').textContent = valid ? `${format(tokens)} tokens` : 'Revisa el límite';
    form.querySelector('[data-retry-budget]').textContent = valid ? ` Con este ajuste: hasta ${format(Math.min(12000, tokens * 2))} tokens en el reintento.` : '';
    form.querySelectorAll('[data-tokens]').forEach(button => button.setAttribute('aria-pressed', String(valid && Number(button.dataset.tokens) === tokens)));
    }
    save.disabled = !dirty();
    state.textContent = dirty() ? 'Tienes cambios sin guardar' : 'Sin cambios pendientes';
  }
  form.addEventListener('input', sync);
  form.addEventListener('change', sync);
  range?.addEventListener('input', () => { tokenInput.value = range.value; sync(); });
  form.addEventListener('click', event => {
    const preset = event.target.closest('[data-tokens]');
    if (preset) { tokenInput.value = preset.dataset.tokens; sync(); }
    const example = event.target.closest('[data-example]');
    if (example) {
      const textarea = example.closest('[data-agent]').querySelector('textarea');
      if (textarea.readOnly || textarea.value.includes(example.dataset.example)) return;
      const value = [textarea.value.trim(), example.dataset.example].filter(Boolean).join('\n');
      if (value.length > textarea.maxLength) {
        state.textContent = 'El ejemplo supera los 4.000 caracteres. Acorta las instrucciones para agregarlo.';
        textarea.focus();
        return;
      }
      textarea.value = value;
      sync();
      textarea.focus();
    }
  });
  form.querySelector('[data-cancel]').addEventListener('click', () => { submitting = true; });
  form.addEventListener('submit', event => {
    if (submitting) { event.preventDefault(); return; }
    submitting = true;
    save.disabled = true;
    save.textContent = 'Guardando…';
    state.textContent = 'Guardando configuración';
  });
  window.addEventListener('beforeunload', event => {
    if (dirty() && !submitting) { event.preventDefault(); event.returnValue = ''; }
  });
  window.addEventListener('pageshow', () => { submitting = false; save.textContent = 'Guardar cambios'; sync(); });
  sync();
})();
