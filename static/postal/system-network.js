(() => {
  'use strict';
  const form = document.querySelector('.network-config');
  if (form) {
  const fields = [...form.querySelectorAll('input:not([type=hidden]), select')];
  const state = () => JSON.stringify(fields.map(field => field.type === 'checkbox' ? field.checked : field.value));
  const initial = state();
  const hasErrors = !!form.querySelector('.system-errors');
  const status = document.getElementById('network-dirty');
  const defaults = document.getElementById('network-defaults');
  const reveal = document.getElementById('network-show-url');
  const url = form.elements.BUSINESS_DATABASE_URL;
  const update = () => {
    const dirty = state() !== initial;
    form.dataset.dirty = String(dirty);
    status.textContent = dirty ? 'Cambios sin guardar' : hasErrors ? 'Revisa los campos señalados' : 'Sin cambios';
    if (reveal) reveal.disabled = !url.value;
  };
  [defaults, reveal].filter(Boolean).forEach(button => { button.hidden = false; });
  fields.forEach(field => {
    const help = document.getElementById(field.id + '_helptext');
    if (help) field.setAttribute('aria-describedby', help.id);
  });
  form.addEventListener('input', update);
  form.addEventListener('change', update);
  defaults?.addEventListener('click', () => {
    Object.entries(JSON.parse(document.getElementById('network-default-values').textContent)).forEach(([name, value]) => {
      if (form.elements[name]) form.elements[name].value = value;
    });
    update();
    status.textContent = 'Tiempos predeterminados aplicados al formulario. Guarda para confirmar.';
  });
  reveal?.addEventListener('click', () => {
    const show = url.type === 'password';
    url.type = show ? 'text' : 'password';
    reveal.textContent = show ? 'Ocultar' : 'Mostrar';
    reveal.setAttribute('aria-pressed', String(show));
  });
  update();
  }
  // Keep the draft on screen: this request checks only the saved connection.
  document.getElementById('network-check').addEventListener('submit', async event => {
    event.preventDefault();
    const check = event.currentTarget;
    const button = check.querySelector('button');
    button.disabled = true;
    let result = document.querySelector('.network-result');
    if (!result) {
      result = document.createElement('p');
      result.className = 'notice network-result';
      result.setAttribute('role', 'status');
      check.closest('section').append(result);
    }
    result.textContent = 'Comprobando la conexión guardada…';
    try {
      const data = new FormData(check);
      data.set('action', 'check_database');
      const response = await fetch(check.getAttribute('action') || location.href, { method: 'POST', body: data });
      if (!response.ok || response.redirected) throw new Error('check failed');
      const documentResult = new DOMParser().parseFromString(await response.text(), 'text/html');
      const diagnostic = documentResult.querySelector('.network-result');
      if (!diagnostic) throw new Error('missing diagnostic');
      result.textContent = diagnostic.textContent;
    } catch {
      result.textContent = 'No se pudo completar la comprobación. Revisa la conexión o vuelve a iniciar sesión.';
    } finally {
      button.disabled = false;
    }
  });
})();
