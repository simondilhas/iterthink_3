// @ts-check

/**
 * @param {KeyboardEvent} event
 */
function isMod(event) {
  return event.metaKey || event.ctrlKey;
}

function dot() {
  const node = document.querySelector(".dot");
  return node instanceof HTMLElement ? node : null;
}

/**
 * Idle, typing and working are local. A verdict or an error keeps its colour.
 * @param {string} name
 */
function setState(name) {
  const node = dot();
  if (node === null) return;
  if (node.dataset.state === "error" || node.dataset.state === "verdict") return;
  if (node.dataset.base === undefined) node.dataset.base = node.dataset.state ?? "idle";
  node.dataset.state = name;
}

/** Back to what the page said: typing while the line has text, else the server state. */
function settle() {
  const node = dot();
  const line = document.querySelector("#line");
  if (node === null || node.dataset.base === undefined) return;
  if (line instanceof HTMLInputElement && line.value.trim() !== "") setState("typing");
  else setState(node.dataset.base);
}

document.addEventListener(
  "keydown",
  (event) => {
    if (event.key !== "Enter" || !(event.target instanceof HTMLInputElement)) return;
    if (event.target.id !== "line") return;
    const form = event.target.form;
    if (!(form instanceof HTMLFormElement)) return;
    if (event.shiftKey) {
      event.preventDefault();
      return;
    }
    if (isMod(event)) {
      event.preventDefault();
      form.requestSubmit();
    }
  },
  true,
);

document.addEventListener("input", (event) => {
  if (!(event.target instanceof HTMLInputElement) || event.target.id !== "line") return;
  if (event.target.value.trim() === "") settle();
  else setState("typing");
});

document.addEventListener("submit", (event) => {
  if (!(event.target instanceof HTMLFormElement)) return;
  if (event.target.querySelector("#line") === null) return;
  setState("working");
});

document.addEventListener("htmx:afterRequest", (event) => {
  const source = event instanceof CustomEvent ? event.detail?.elt : null;
  if (!(source instanceof HTMLFormElement) || source.querySelector("#line") === null) return;
  const node = dot();
  if (node !== null && node.dataset.state === "working") settle();
});

document.addEventListener("it-recall", () => {
  const line = document.querySelector("#line");
  if (line instanceof HTMLInputElement) line.focus();
});
