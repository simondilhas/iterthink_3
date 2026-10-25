// @ts-check

/** A CSV table. Sort, filter, and mark changed cells. */

class DataTable extends HTMLElement {
  connectedCallback() {
    queueMicrotask(() => this._start());
  }

  _start() {
    ensureStyle();
    const path = this.getAttribute("src") || "";
    readText(this, path).then((text) => this._paint(text));
  }

  /**
   * @param {string} text
   */
  _paint(text) {
    const parsed = parseCsv(text);
    this._rows = parsed.rows;
    this._header = parsed.header;
    this._query = "";
    this._sort = "";
    this._dir = 1;
    this.replaceChildren();
    const filter = document.createElement("input");
    filter.type = "search";
    filter.setAttribute("aria-label", "Filter");
    filter.addEventListener("input", () => {
      this._query = filter.value;
      this._body();
    });
    this.append(filter, this._table());
  }

  _table() {
    const table = document.createElement("table");
    const head = document.createElement("tr");
    this._header.forEach((name, index) => {
      const cell = document.createElement("th");
      cell.textContent = name;
      cell.addEventListener("click", () => {
        this._dir = this._sort === String(index) ? -this._dir : 1;
        this._sort = String(index);
        this._body();
      });
      head.append(cell);
    });
    table.append(head);
    const body = document.createElement("tbody");
    table.append(body);
    this._bodyHost = body;
    this._body();
    return table;
  }

  _body() {
    const host = this._bodyHost;
    if (!(host instanceof HTMLElement)) return;
    host.replaceChildren();
    const query = this._query.toLowerCase();
    const rows = this._rows.filter((row) => row.join(" ").toLowerCase().includes(query));
    const index = Number(this._sort);
    if (this._sort !== "") {
      rows.sort((a, b) => a[index].localeCompare(b[index]) * this._dir);
    }
    const marks = changedMarks(this.getAttribute("changed") || "");
    for (const row of rows) {
      host.append(rowElement(this._header, row, marks));
    }
  }
}

/**
 * @param {string} raw
 */
function ensureStyle() {
  if (document.getElementById("data-table-style")) return;
  const style = document.createElement("style");
  style.id = "data-table-style";
  style.textContent = [
    "data-table td.changed { outline: 2px solid var(--accent, #1d4ed8); }",
    "data-table td, data-table th { border: 1px solid var(--line, #ccc); padding: 4px 8px; }",
    "data-table table { border-collapse: collapse; }",
  ].join(" ");
}

function changedMarks(raw) {
  try {
    const loaded = JSON.parse(raw || "[]");
    return Array.isArray(loaded) ? loaded : [];
  } catch {
    return [];
  }
}

/**
 * @param {string[]} header
 * @param {string[]} row
 * @param {object[]} marks
 */
function rowElement(header, row, marks) {
  const tr = document.createElement("tr");
  row.forEach((value, index) => {
    const cell = document.createElement("td");
    cell.textContent = value;
    const mark = marks.find((item) => item.row === row[0] && item.column === header[index]);
    if (mark && typeof mark.before === "string") {
      cell.className = "changed";
      cell.title = mark.before;
    }
    tr.append(cell);
  });
  return tr;
}

/**
 * @param {string} text
 */
function parseCsv(text) {
  const lines = text.split(/\r?\n/).filter((line) => line.length > 0);
  const rows = lines.map((line) => line.split(","));
  const header = rows.shift() || [];
  return { header: header, rows: rows };
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
  return postCall(url, "readFile", { path: path }).then((result) => textOf(result));
}

/**
 * @param {unknown} result
 */
function textOf(result) {
  if (!result || typeof result !== "object" || !("text" in result)) return "";
  const text = result.text;
  return typeof text === "string" ? text : "";
}

/**
 * @param {string} url
 * @param {string} name
 * @param {object} args
 */
function postCall(url, name, args) {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ name: name, args: args }),
  }).then((response) => response.json());
}

if (!customElements.get("data-table")) customElements.define("data-table", DataTable);
