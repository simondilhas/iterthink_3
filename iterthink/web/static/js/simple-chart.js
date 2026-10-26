// @ts-check

/** A bar or line chart from a CSV. SVG only. */

const WIDTH = 480;
const HEIGHT = 200;
const PAD = 28;

class SimpleChart extends HTMLElement {
  connectedCallback() {
    queueMicrotask(() => this._start());
  }

  _start() {
    const path = this.getAttribute("src") || "";
    readText(this, path).then((text) => {
      const kind = this.getAttribute("type") || "bar";
      const svg = chart(text, kind, this.getAttribute("x") || "", this.getAttribute("y") || "");
      this.innerHTML = svg;
    });
  }
}

/**
 * @param {string} text
 * @param {string} kind
 * @param {string} xKey
 * @param {string} yKey
 */
function chart(text, kind, xKey, yKey) {
  const points = pairs(text, xKey, yKey);
  if (kind === "line") return lineChart(points);
  return barChart(points);
}

/**
 * @param {string} text
 * @param {string} xKey
 * @param {string} yKey
 */
function pairs(text, xKey, yKey) {
  const lines = text.split(/\r?\n/).filter((line) => line.length > 0);
  const header = (lines.shift() || "").split(",");
  const x = header.indexOf(xKey);
  const y = header.indexOf(yKey);
  return lines.map((line) => {
    const cells = line.split(",");
    const raw = cells[y] || "";
    const value = Number(raw);
    return { label: cells[x] || "", value: Number.isFinite(value) ? value : 0 };
  });
}

/**
 * @param {{label: string, value: number}[]} points
 */
function barChart(points) {
  const peak = points.reduce((max, point) => Math.max(max, point.value), 0);
  const slot = (WIDTH - 2 * PAD) / Math.max(points.length, 1);
  const parts = [openSvg()];
  points.forEach((point, index) => {
    const height = peak <= 0 ? 0 : (point.value / peak) * (HEIGHT - 2 * PAD);
    const left = PAD + index * slot + slot * 0.2;
    const top = HEIGHT - PAD - height;
    parts.push(rect(left, top, slot * 0.6, height));
    parts.push(label(left, point.label));
  });
  parts.push("</svg>");
  return parts.join("");
}

/**
 * @param {{label: string, value: number}[]} points
 */
function lineChart(points) {
  const peak = points.reduce((max, point) => Math.max(max, point.value), 0);
  const span = Math.max(points.length - 1, 1);
  const usable = WIDTH - 2 * PAD;
  const coords = [];
  const parts = [openSvg()];
  points.forEach((point, index) => {
    const left = PAD + (usable * index) / span;
    const height = peak <= 0 ? 0 : (point.value / peak) * (HEIGHT - 2 * PAD);
    const top = HEIGHT - PAD - height;
    coords.push(`${px(left)},${px(top)}`);
    parts.push(label(left, point.label));
  });
  parts.push(`<polyline points="${coords.join(" ")}" fill="none" stroke="currentColor"></polyline>`);
  parts.push("</svg>");
  return parts.join("");
}

function openSvg() {
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${WIDTH} ${HEIGHT}">`;
}

/**
 * @param {number} left
 * @param {number} top
 * @param {number} width
 * @param {number} height
 */
function rect(left, top, width, height) {
  return `<rect x="${px(left)}" y="${px(top)}" width="${px(width)}" height="${px(height)}"></rect>`;
}

/**
 * @param {number} left
 * @param {string} text
 */
function label(left, text) {
  return `<text x="${px(left)}" y="${HEIGHT - 8}">${escapeXml(text)}</text>`;
}

/** @param {number} value */
function px(value) {
  return String(Math.round(value));
}

/** @param {string} text */
function escapeXml(text) {
  return text.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
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

if (!customElements.get("simple-chart")) customElements.define("simple-chart", SimpleChart);
