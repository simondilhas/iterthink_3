// @ts-check

const mac = /Mac/.test(navigator.platform);

/** @type {Record<string, string>} */
const DEFAULTS = { line: "Mod+K", save: "Mod+S", files: "Mod+E" };

/**
 * @returns {Record<string, string>}
 */
function configured() {
  const meta = document.querySelector('meta[name="it-shortcuts"]');
  if (!(meta instanceof HTMLMetaElement)) return DEFAULTS;
  try {
    return { ...DEFAULTS, ...JSON.parse(meta.content) };
  } catch {
    return DEFAULTS;
  }
}

/**
 * @param {string} combo such as "Mod+Shift+K"
 * @param {KeyboardEvent} event
 */
function matches(combo, event) {
  const parts = combo.split("+").map((part) => part.trim().toLowerCase());
  const key = parts.pop() || "";
  const wantMod = parts.includes("mod");
  const wantShift = parts.includes("shift");
  const wantAlt = parts.includes("alt");
  const mod = mac ? event.metaKey : event.ctrlKey;
  const pressed = event.key === " " ? "space" : event.key.toLowerCase();
  return pressed === key && mod === wantMod && event.shiftKey === wantShift && event.altKey === wantAlt;
}

function focusLine() {
  const line = document.querySelector("#line");
  if (line instanceof HTMLInputElement) line.focus();
}

function saveEditor() {
  const form = document.querySelector("#editor");
  if (form instanceof HTMLFormElement) form.requestSubmit();
}

function toggleFiles() {
  const left = document.querySelector("#left");
  const button = document.querySelector("#files-button");
  if (!(left instanceof HTMLElement)) return;
  if (left.childElementCount > 0) {
    left.replaceChildren();
    return;
  }
  if (button instanceof HTMLElement) button.click();
}

function closeMenus() {
  for (const menu of document.querySelectorAll("details.menu[open]")) {
    if (menu instanceof HTMLDetailsElement) menu.open = false;
  }
}

function closePanels() {
  closeMenus();
  for (const id of ["#search-results", "#left", "#right"]) {
    const node = document.querySelector(id);
    if (node instanceof HTMLElement) node.replaceChildren();
  }
}

/**
 * @param {SubmitEvent} event
 */
function onSubmit(event) {
  if (event.target instanceof Element && event.target.closest("details.menu")) closeMenus();
}

/** @type {Array<[string, () => void]>} */
const ACTIONS = [
  ["line", focusLine],
  ["save", saveEditor],
  ["files", toggleFiles],
];

/**
 * @param {KeyboardEvent} event
 */
function onKey(event) {
  const keys = configured();
  for (const [name, action] of ACTIONS) {
    if (keys[name] && matches(keys[name], event)) {
      event.preventDefault();
      action();
      return;
    }
  }
  if (event.key === "Escape" && !document.querySelector(".settings")) closePanels();
}

document.addEventListener("keydown", onKey);
document.addEventListener("submit", onSubmit);
