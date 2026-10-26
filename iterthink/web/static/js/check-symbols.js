// @ts-check

const mac = /Mac/.test(navigator.platform);

/**
 * @param {KeyboardEvent} event
 */
function isMod(event) {
  return mac ? event.metaKey : event.ctrlKey;
}

function togglePanel() {
  const node = document.querySelector("#checks-panel");
  if (node instanceof HTMLDetailsElement) node.open = !node.open;
}

/**
 * @param {KeyboardEvent} event
 */
function onKey(event) {
  if (!isMod(event) || !event.shiftKey || event.key.toLowerCase() !== "c") return;
  event.preventDefault();
  togglePanel();
}

class CheckSymbols extends HTMLElement {}

customElements.define("check-symbols", CheckSymbols);
document.addEventListener("keydown", onKey);
