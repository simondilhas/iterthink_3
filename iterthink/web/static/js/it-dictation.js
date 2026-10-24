// @ts-check

/** Hold Mod+Shift+Space, or the dot, to speak. Releasing stops. Enter is never sent. */

let currentKey = "Mod+Shift+Space";
let handsFree = false;
let active = false;
let downAt = 0;
/** @type {EventSource | null} */
let stream = null;

function projectBase() {
  const form = document.querySelector("form[action*='/p/']");
  if (!(form instanceof HTMLFormElement)) return "/dictation";
  const match = form.action.match(/\/p\/([^/]+)\//);
  return match ? `/p/${match[1]}/dictation` : "/dictation";
}

function setDot(name) {
  const node = document.querySelector(".dot");
  if (!(node instanceof HTMLElement)) return;
  const state = node.dataset.state;
  if (state === "error" || state === "verdict") return;
  node.dataset.state = name;
}

function field() {
  const activeNode = document.activeElement;
  if (activeNode instanceof HTMLInputElement || activeNode instanceof HTMLTextAreaElement) {
    return activeNode;
  }
  const fallback = document.querySelector("#line, textarea, input[name='text']");
  if (fallback instanceof HTMLInputElement || fallback instanceof HTMLTextAreaElement) return fallback;
  return null;
}

function insert(text) {
  const target = field();
  if (target === null || text === "") return;
  const start = target.selectionStart ?? target.value.length;
  const end = target.selectionEnd ?? start;
  target.setRangeText(text, start, end, "end");
  target.dispatchEvent(new Event("input", { bubbles: true }));
}

function begin() {
  if (active) return;
  active = true;
  setDot("listening");
  const root = projectBase();
  fetch(`${root}/start`, { method: "POST" });
  const source = new EventSource(`${root}/events`);
  stream = source;
  source.addEventListener("state", (event) => {
    if (event.data === "listening" || event.data === "transcribing") setDot(event.data);
  });
  source.addEventListener("transcript", (event) => {
    setDot("transcribing");
    insert(event.data);
  });
  source.addEventListener("done", () => {
    active = false;
    setDot("idle");
    source.close();
    if (stream === source) stream = null;
  });
}

function end() {
  if (!active) return;
  setDot("transcribing");
  fetch(`${projectBase()}/stop`, { method: "POST" });
}

function matches(event, spec) {
  const parts = spec.split("+");
  if (parts.length < 2) return false;
  const key = parts[parts.length - 1];
  const mods = parts.slice(0, -1);
  const bare = mods.length === 1 && mods[0] === "Ctrl" && key === "Space";
  if (bare) return false;
  if (mods.includes("Mod") && !(event.metaKey || event.ctrlKey)) return false;
  if (mods.includes("Shift") !== event.shiftKey) return false;
  if (mods.includes("Alt") !== event.altKey) return false;
  if (key === "Space") return event.key === " ";
  return event.key.toLowerCase() === key.toLowerCase();
}

document.addEventListener("keydown", (event) => {
  if (event.repeat || !matches(event, currentKey)) return;
  event.preventDefault();
  begin();
}, true);

document.addEventListener("keyup", (event) => {
  if (!matches(event, currentKey)) return;
  event.preventDefault();
  end();
}, true);

document.addEventListener("pointerdown", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement) || !target.classList.contains("dot")) return;
  downAt = Date.now();
  if (handsFree) {
    if (active) end();
    else begin();
    return;
  }
  begin();
});

document.addEventListener("pointerup", () => {
  if (!handsFree) end();
});

document.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement) || !target.classList.contains("dot")) return;
  const held = Date.now() - downAt > 250;
  if (!handsFree && !held) return;
  event.preventDefault();
  event.stopPropagation();
}, true);

fetch(`${projectBase()}/key`, { headers: { Accept: "text/plain" } })
  .then((response) => (response.ok ? response.text() : ""))
  .then((body) => {
    const [key, flag] = body.split("\n");
    if (key) currentKey = key.trim();
    handsFree = (flag || "").trim() === "1";
  })
  .catch(() => undefined);
