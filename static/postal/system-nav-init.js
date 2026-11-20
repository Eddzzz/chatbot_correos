// Restore the sidebar before styles and body can paint its default width.
(() => {
  "use strict";
  let state = 'expanded';
  try {
    if (localStorage.getItem('bolipost-admin-sidebar') === 'collapsed') state = 'collapsed';
  } catch { /* Navigation works without storage. */ }
  document.documentElement.dataset.adminNav = state;
})();
