// @ts-check

/** Panels that open on demand get an X at the top right that empties them. */
const PANELS = ["#left", "#right", "#search-results"];

/**
 * @param {HTMLElement} panel
 */
function hasContent(panel) {
  for (const node of panel.childNodes) {
    if (node instanceof HTMLElement && node.classList.contains("it-close")) continue;
    if (node.nodeType === Node.ELEMENT_NODE || (node.textContent || "").trim()) return true;
  }
  return false;
}

/**
 * @param {HTMLElement} panel
 */
function closeButton(panel) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "it-close";
  button.title = "Close";
  button.setAttribute("aria-label", "Close");
  button.textContent = "×";
  button.addEventListener("click", () => panel.replaceChildren());
  return button;
}

/**
 * @param {HTMLElement} panel
 */
function sync(panel) {
  const button = panel.querySelector(":scope > .it-close");
  if (!hasContent(panel) || panel.querySelector("[data-no-close]")) {
    button?.remove();
    return;
  }
  if (!button) panel.prepend(closeButton(panel));
}

for (const id of PANELS) {
  const panel = document.querySelector(id);
  if (!(panel instanceof HTMLElement)) continue;
  sync(panel);
  new MutationObserver(() => sync(panel)).observe(panel, { childList: true });
}
