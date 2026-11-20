(() => {
  "use strict";
  let theme = "system";
  try { const saved = localStorage.getItem("bolipost-theme"); if (["light", "dark"].includes(saved)) theme = saved; } catch { /* Theme works without storage. */ }
  const preference = window.matchMedia("(prefers-color-scheme: dark)");
  const apply = () => { document.documentElement.dataset.theme = theme === "system" ? (preference.matches ? "dark" : "light") : theme; };
  apply();
  // The workspace owns its chart-aware theme control; this also supports login.
  document.addEventListener("DOMContentLoaded", () => {
    const control = document.getElementById("login-theme-toggle");
    if (!control) return;
    const label = () => {
      const dark = document.documentElement.dataset.theme === "dark";
      control.setAttribute("aria-label", dark ? "Activar modo claro" : "Activar modo oscuro");
      control.querySelector("use").setAttribute("href", dark ? "#icon-sun" : "#icon-moon");
    };
    label();
    control.addEventListener("click", () => {
      theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      apply(); label();
      try { localStorage.setItem("bolipost-theme", theme); } catch { /* Theme works without storage. */ }
    });
    preference.addEventListener("change", () => { if (theme === "system") { apply(); label(); } });
  });
})();
