// @ts-check

const mac = /Mac/.test(navigator.platform);

/**
 * @param {KeyboardEvent} event
 * @returns {boolean}
 */
function isMod(event) {
  return mac ? event.metaKey : event.ctrlKey;
}

/**
 * @param {HTMLTextAreaElement} textarea
 * @returns {boolean}
 */
function atEmptyStart(textarea) {
  const at = textarea.selectionStart;
  if (at !== textarea.selectionEnd) return false;
  const before = textarea.value.slice(0, at);
  const split = before.lastIndexOf("\n\n");
  const paragraph = split === -1 ? before : before.slice(split + 2);
  return paragraph.length === 0;
}

/**
 * @param {HTMLElement} editor
 * @param {HTMLTextAreaElement} textarea
 */
function fill(editor, textarea) {
  const offset = editor.querySelector("input[name=offset]");
  const selection = editor.querySelector("input[name=selection]");
  const draft = editor.querySelector("input[name=draft]");
  if (offset instanceof HTMLInputElement) offset.value = String(textarea.selectionStart);
  if (selection instanceof HTMLInputElement) {
    const start = textarea.selectionStart;
    const end = textarea.selectionEnd;
    selection.value = start === end ? "" : textarea.value.slice(start, end);
  }
  if (draft instanceof HTMLInputElement) draft.value = textarea.value;
}

class MdEditor extends HTMLElement {
  connectedCallback() {
    const textarea = this.querySelector("textarea");
    if (!(textarea instanceof HTMLTextAreaElement)) return;
    const editor = this;
    textarea.addEventListener("keydown", (event) => {
      if (isMod(event) && event.key === "Enter") {
        event.preventDefault();
        event.stopPropagation();
        const menu = editor.querySelector("#margin-menu");
        if (menu instanceof HTMLDetailsElement) menu.open = true;
        fill(editor, textarea);
      } else if (event.key === "/" && atEmptyStart(textarea)) {
        event.preventDefault();
        const path = editor.dataset.path || "";
        document.dispatchEvent(new CustomEvent("it-recall", { detail: { path } }));
      }
    });
    const form = editor.querySelector("#margin");
    if (form instanceof HTMLFormElement) {
      form.addEventListener("submit", () => fill(editor, textarea));
    }
  }
}

if (!customElements.get("md-editor")) customElements.define("md-editor", MdEditor);
