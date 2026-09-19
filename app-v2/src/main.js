// Valte v2 adapter entry — minimal shell for Task 7 build verification.
// Full gateway/projection wiring lands in Tasks 8-10.

const statusEl = document.getElementById("v2-status");
const contentEl = document.getElementById("v2-content");

function setStatus(text) {
  if (statusEl) statusEl.textContent = text;
}

async function init() {
  setStatus("v2 shell · tokens ok");
  if (contentEl) {
    // Keep fixed canvas visible; future adapter will replace this region
    // with jurisdiction-scoped projection (coordination/authority/responder).
    contentEl.setAttribute("data-v2-ready", "true");
  }
  // Verify design tokens are loaded (CSS variable check)
  const styles = getComputedStyle(document.documentElement);
  const surface = styles.getPropertyValue("--surface-000").trim();
  if (surface && contentEl) {
    setStatus(`v2 shell · tokens ${surface.slice(0, 7)}`);
  }
}

init();

// HMR acceptance for vite dev
if (import.meta.hot) {
  import.meta.hot.accept();
}
