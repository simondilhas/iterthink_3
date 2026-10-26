// @ts-check

/** Inputs for one row. Submit proposes the row. It does not write the file. */

class FormFields extends HTMLElement {
  connectedCallback() {
    const fields = schemaOf(this.getAttribute("schema") || "");
    const form = document.createElement("form");
    for (const field of fields) {
      const label = document.createElement("label");
      label.style.marginRight = "12px";
      label.textContent = field.name + " ";
      const input = document.createElement("input");
      input.name = field.name;
      input.type = field.type || "text";
      input.placeholder = field.name;
      input.setAttribute("aria-label", field.name);
      label.append(input);
      form.append(label);
    }
    const button = document.createElement("button");
    button.type = "submit";
    button.textContent = "Propose";
    form.append(button);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      this._send(form, fields);
    });
    this.replaceChildren(form);
  }

  /**
   * @param {HTMLFormElement} form
   * @param {{name: string, type: string}[]} fields
   */
  _send(form, fields) {
    const target = this.getAttribute("target") || "";
    const values = fields.map((field) => {
      const input = form.elements.namedItem(field.name);
      return input instanceof HTMLInputElement ? input.value : "";
    });
    if (values.every((value) => value.trim() === "")) return;
    const names = fields.map((field) => field.name);
    readText(this, target).then((text) => {
      const kind = target.endsWith(".json") ? "json" : "csv";
      const next = kind === "json" ? jsonRow(text, names, values) : csvRow(text, names, values);
      propose(this, target, next);
    });
  }
}

/**
 * @param {string} raw
 * @returns {{name: string, type: string}[]}
 */
function schemaOf(raw) {
  try {
    const loaded = JSON.parse(raw || "[]");
    if (!Array.isArray(loaded)) return [];
    return loaded.filter((item) => item && typeof item.name === "string");
  } catch {
    return [];
  }
}

/**
 * @param {string} existing
 * @param {string[]} fields
 * @param {string[]} values
 */
function csvRow(existing, fields, values) {
  const line = values.map(csvCell).join(",");
  if (!existing.trim()) return `${fields.join(",")}\n${line}\n`;
  const body = existing.endsWith("\n") ? existing : `${existing}\n`;
  return body + line + "\n";
}

/** @param {string} value */
function csvCell(value) {
  if (!/[",\n]/.test(value)) return value;
  return `"${value.replaceAll('"', '""')}"`;
}

/**
 * @param {string} existing
 * @param {string[]} fields
 * @param {string[]} values
 */
function jsonRow(existing, fields, values) {
  const row = {};
  fields.forEach((field, index) => {
    row[field] = values[index] || "";
  });
  let rows = [];
  try {
    const loaded = existing.trim() ? JSON.parse(existing) : [];
    if (Array.isArray(loaded)) rows = loaded;
    else if (loaded && typeof loaded === "object") rows = [loaded];
  } catch {
    rows = [];
  }
  rows.push(row);
  return `${JSON.stringify(rows, null, 2)}\n`;
}

/**
 * @param {HTMLElement} node
 * @param {string} path
 * @param {string} text
 */
function propose(node, path, text) {
  const changes = {};
  changes[path] = text;
  const args = { changes: changes, reason: "add a row" };
  const bridge = window.bridge;
  if (bridge && bridge.propose) {
    bridge.propose(args);
    return;
  }
  const url = node.getAttribute("data-call");
  if (!url) return;
  fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ name: "propose", args: args }),
  });
}

/**
 * @param {HTMLElement} node
 * @param {string} path
 */
function readText(node, path) {
  const bridge = window.bridge;
  if (bridge && bridge.readFile) {
    return bridge.readFile({ path: path }).then((result) => textOf(result));
  }
  const url = node.getAttribute("data-call");
  if (!url) return Promise.resolve("");
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ name: "readFile", args: { path: path } }),
  })
    .then((response) => response.json())
    .then((result) => textOf(result));
}

/** @param {unknown} result */
function textOf(result) {
  if (!result || typeof result !== "object" || !("text" in result)) return "";
  const text = result.text;
  return typeof text === "string" ? text : "";
}

if (!customElements.get("form-fields")) customElements.define("form-fields", FormFields);
