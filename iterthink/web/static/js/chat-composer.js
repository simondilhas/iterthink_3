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
 * Enter and Mod+Enter send. Shift+Enter stays a line break.
 * @param {KeyboardEvent} event
 */
function onKey(event) {
  const target = event.target;
  if (!(target instanceof HTMLTextAreaElement)) return;
  const form = target.form;
  if (!(form instanceof HTMLFormElement) || form.id !== "chat-form") return;
  if (event.key !== "Enter" || event.shiftKey) return;
  if (!isMod(event) && event.altKey) return;
  event.preventDefault();
  form.requestSubmit();
}

/**
 * @param {ParentNode} parent
 * @param {string} role
 * @param {string} text
 */
function appendMessage(parent, role, text) {
  const section = document.createElement("section");
  const who = document.createElement("p");
  who.textContent = role;
  const body = document.createElement("p");
  body.textContent = text;
  section.append(who, body);
  parent.append(section);
}

document.addEventListener("keydown", onKey, true);

document.addEventListener("htmx:configRequest", (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement) || form.id !== "chat-form") return;
  const detail = /** @type {{ parameters?: { text?: string } }} */ (event).detail;
  const text = detail?.parameters?.text?.trim() ?? "";
  const log = document.querySelector("#chat-log");
  if (text && log) appendMessage(log, "user", text);
  const area = form.querySelector("textarea");
  if (area instanceof HTMLTextAreaElement) area.value = "";
});

document.addEventListener("htmx:sseClose", () => {
  const pre = document.querySelector("#chat-text");
  const log = document.querySelector("#chat-log");
  if (!(pre instanceof HTMLElement) || !log) return;
  const text = pre.textContent?.trim() ?? "";
  if (!text) return;
  appendMessage(log, "assistant", text);
  pre.replaceChildren();
});
