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
  node.dataset.state = name;
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
  setState("typing");
});

document.addEventListener("submit", (event) => {
  if (!(event.target instanceof HTMLFormElement)) return;
  if (event.target.querySelector("#line") === null) return;
  setState("working");
});

document.addEventListener("it-recall", () => {
  const line = document.querySelector("#line");
  if (line instanceof HTMLInputElement) line.focus();
});
