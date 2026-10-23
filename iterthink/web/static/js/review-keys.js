// @ts-check

/** @returns {HTMLElement[]} */
function changes() {
  return [...document.querySelectorAll(".change")].filter((node) => node instanceof HTMLElement);
}

/**
 * @param {HTMLElement[]} nodes
 */
function currentIndex(nodes) {
  const active = nodes.findIndex((node) => node.classList.contains("active"));
  return active < 0 ? 0 : active;
}

/**
 * @param {HTMLElement[]} nodes
 * @param {number} index
 */
function select(nodes, index) {
  nodes.forEach((node, item) => node.classList.toggle("active", item === index));
  nodes[index]?.scrollIntoView({ block: "nearest" });
}

/**
 * @param {KeyboardEvent} event
 */
function onKey(event) {
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  const target = event.target;
  if (target instanceof HTMLInputElement || target instanceof HTMLTextAreaElement) return;
  const nodes = changes();
  if (event.key === "j" || event.key === "k") {
    if (nodes.length === 0) return;
    event.preventDefault();
    const index = currentIndex(nodes);
    const next = event.key === "j" ? Math.min(index + 1, nodes.length - 1) : Math.max(index - 1, 0);
    select(nodes, next);
  } else if (event.key === "a") {
    const form = document.querySelector("#accept");
    if (form instanceof HTMLFormElement) form.requestSubmit();
  } else if (event.key === "r") {
    const reason = document.querySelector("#reject-reason");
    if (reason instanceof HTMLInputElement) reason.focus();
  }
}

document.addEventListener("keydown", onKey);
