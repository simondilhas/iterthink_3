// @ts-check

const mac = /Mac/.test(navigator.platform);

/**
 * @param {KeyboardEvent} event
 */
function isMod(event) {
  return mac ? event.metaKey : event.ctrlKey;
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

/**
 * @param {KeyboardEvent} event
 */
function onKey(event) {
  const key = event.key.toLowerCase();
  if (isMod(event) && key === "k") {
    event.preventDefault();
    focusLine();
  } else if (isMod(event) && key === "s") {
    event.preventDefault();
    saveEditor();
  } else if (isMod(event) && key === "e") {
    event.preventDefault();
    toggleFiles();
  } else if (event.key === "Escape") {
    closePanels();
  }
}

document.addEventListener("keydown", onKey);
document.addEventListener("submit", onSubmit);
