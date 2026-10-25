// @ts-check

/** Parent of <app-frame>. Forwards allowlisted calls with this page's token. */

const allowed = ["listFiles", "readFile", "history", "search", "compare", "propose"];

function frameOf() {
  return document.querySelector("app-frame");
}

window.addEventListener("message", (event) => {
  const node = frameOf();
  const data = event.data;
  if (!(node instanceof HTMLElement) || !data || typeof data.name !== "string") return;
  if (!allowed.includes(data.name)) return;
  const url = node.getAttribute("data-call");
  const source = event.source;
  if (!url || source === null || !("postMessage" in source)) return;
  fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ name: data.name, args: data.args || {} }),
  })
    .then((response) => response.json())
    .then((result) => {
      source.postMessage({ id: data.id, result: result }, "*");
    });
});

const revise = document.querySelector("#app-revise");
const field = document.querySelector("#app-ask");
if (revise instanceof HTMLFormElement && field instanceof HTMLTextAreaElement) {
  field.addEventListener("keydown", (event) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    if (event.metaKey || event.ctrlKey) revise.requestSubmit();
  });
}
