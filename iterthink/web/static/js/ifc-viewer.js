// @ts-check
/**
 * <ifc-viewer model="…glb">: one model version.
 * <ifc-diff model-before model-after model-diff changes>: the diff GLB
 * coloured by category. Colours come from the --it-cat-* custom properties so
 * the legend, the table badges and the 3D view share one source.
 * Clicking an element emits `ifc-select` with { guid }; empty space clears it.
 */
import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

/** @type {Record<string, string>} */
const COLOUR = {
  added: "--it-cat-added",
  removed: "--it-cat-removed",
  reshaped: "--it-cat-reshaped",
  moved: "--it-cat-moved",
  props_only: "--it-cat-props",
  unchanged: "--it-cat-unchanged",
};

/** @param {THREE.Object3D} node */
function guidOf(node) {
  return String(node.userData.name || node.name || "");
}

/** A canvas, camera, controls and on-demand rendering. */
class Stage {
  /** @param {HTMLElement} host */
  constructor(host) {
    this.host = host;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.05, 5000);
    this.camera.position.set(10, 10, 10);
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(window.devicePixelRatio);
    host.append(this.renderer.domElement);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.addEventListener("change", () => this.draw());
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x888888, 3));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(30, 60, 20);
    this.scene.add(sun);
    this.root = new THREE.Group();
    this.root.rotation.x = -Math.PI / 2;
    this.scene.add(this.root);
    new ResizeObserver(() => this.resize()).observe(host);
    this._bindPick();
    this.resize();
  }

  resize() {
    const width = this.host.clientWidth || 300;
    const height = this.host.clientHeight || 300;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
    this.draw();
  }

  draw() {
    this.renderer.render(this.scene, this.camera);
  }

  /** @param {THREE.Object3D} target */
  frame(target) {
    const box = new THREE.Box3().setFromObject(target);
    if (box.isEmpty()) return;
    const centre = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3()).length() || 1;
    this.controls.target.copy(centre);
    this.camera.position.copy(centre).add(new THREE.Vector3(size, size * 0.8, size));
    this.camera.near = size / 1000;
    this.camera.far = size * 100;
    this.camera.updateProjectionMatrix();
    this.controls.update();
    this.draw();
  }

  _bindPick() {
    const canvas = this.renderer.domElement;
    let down = { x: 0, y: 0 };
    canvas.addEventListener("pointerdown", (event) => {
      down = { x: event.clientX, y: event.clientY };
    });
    canvas.addEventListener("pointerup", (event) => {
      if (Math.hypot(event.clientX - down.x, event.clientY - down.y) > 4) return;
      const hit = this.pick(event);
      this.host.dispatchEvent(new CustomEvent("ifc-select", {
        bubbles: true, detail: { guid: hit ? guidOf(hit) : "" },
      }));
    });
  }

  /** @param {PointerEvent} event */
  pick(event) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    const pointer = new THREE.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    );
    const ray = new THREE.Raycaster();
    ray.setFromCamera(pointer, this.camera);
    const hits = ray.intersectObject(this.root, true).filter((hit) => hit.object.visible);
    return hits.length ? hits[0].object : null;
  }

  /** @param {string} url */
  async load(url) {
    const gltf = await new GLTFLoader().loadAsync(url);
    return gltf.scene;
  }

  /** @param {THREE.Object3D} model */
  show(model) {
    this.root.clear();
    this.root.add(model);
    this.resize();
    this.frame(this.root);
  }
}

/** @param {THREE.Object3D} model @param {(mesh: THREE.Mesh) => void} each */
function eachMesh(model, each) {
  model.traverse((node) => {
    if (node instanceof THREE.Mesh) each(node);
  });
}

/** @param {THREE.Mesh} mesh @param {THREE.Mesh | null} chosen */
function highlight(mesh, chosen) {
  const material = /** @type {THREE.MeshLambertMaterial} */ (mesh.material);
  material.emissive.setHex(mesh === chosen ? 0x444444 : 0x000000);
}

class IfcViewer extends HTMLElement {
  static observedAttributes = ["model"];

  connectedCallback() {
    if (!this.stage) this.stage = new Stage(this);
    this._open();
  }

  attributeChangedCallback() {
    if (this.stage) this._open();
  }

  async _open() {
    const url = this.getAttribute("model");
    if (!url || !this.stage) return;
    const model = await this.stage.load(url);
    const grey = getComputedStyle(this).getPropertyValue(COLOUR.unchanged).trim() || "#999";
    eachMesh(model, (mesh) => {
      mesh.material = new THREE.MeshLambertMaterial({ color: new THREE.Color(grey) });
    });
    this.stage.show(model);
  }

  /** @param {string} guid */
  select(guid) {
    if (!this.stage) return;
    /** @type {THREE.Mesh | null} */
    let chosen = null;
    eachMesh(this.stage.root, (mesh) => {
      if (guidOf(mesh) === guid) chosen = mesh;
    });
    eachMesh(this.stage.root, (mesh) => highlight(mesh, chosen));
    if (chosen) this.stage.frame(chosen);
    else this.stage.draw();
  }
}

class IfcDiff extends IfcViewer {
  static observedAttributes = ["model-before", "model-after", "model-diff"];

  connectedCallback() {
    if (!this.stage) {
      this.stage = new Stage(this);
      /** @type {Map<string, THREE.Object3D>} */
      this.cache = new Map();
      /** @type {Set<string>} */
      this.hidden = new Set();
      this._bindControls();
    }
    this.view("diff");
  }

  attributeChangedCallback() {
    if (this.stage && this.cache) {
      this.cache.clear();
      this.view("diff");
    }
  }

  /** @param {"diff" | "before" | "after"} which */
  async view(which) {
    const url = this.getAttribute(`model-${which}`);
    if (!url || !this.stage || !this.cache) return;
    this.current = which;
    let model = this.cache.get(which);
    if (!model) {
      model = await this.stage.load(url);
      this._paint(model, which);
      this.cache.set(which, model);
    }
    this.stage.show(model);
    this._applyHidden();
  }

  /** @param {THREE.Object3D} model @param {string} which */
  _paint(model, which) {
    const style = getComputedStyle(this);
    eachMesh(model, (mesh) => {
      const category = String(mesh.userData.category || "unchanged");
      const part = String(mesh.userData.part || "after");
      const name = part === "added_volume" ? "added" : part === "removed_volume" ? "removed" : category;
      const css = style.getPropertyValue(COLOUR[which === "diff" ? name : "unchanged"] || "").trim();
      const opacity = this._opacity(which, category, part);
      mesh.material = new THREE.MeshLambertMaterial({
        color: new THREE.Color(css || "#999"),
        transparent: opacity < 1,
        opacity,
        depthWrite: opacity === 1,
      });
    });
  }

  /** @param {string} which @param {string} category @param {string} part */
  _opacity(which, category, part) {
    if (which !== "diff") return 1;
    if (category === "moved" && part === "before") return 0.25;
    if (category === "reshaped" && part === "after") return 0.2;
    if (category === "unchanged") return 0.25;
    return 1;
  }

  _applyHidden() {
    if (!this.stage || !this.hidden) return;
    const hidden = this.current === "diff" ? this.hidden : new Set();
    eachMesh(this.stage.root, (mesh) => {
      mesh.visible = !hidden.has(String(mesh.userData.category || "unchanged"));
    });
    this.stage.draw();
  }

  _bindControls() {
    const panel = this.closest(".model-3d") || this.parentElement;
    if (!panel) return;
    panel.addEventListener("change", (event) => {
      const input = event.target;
      if (!(input instanceof HTMLInputElement) || !this.hidden) return;
      if (input.name === "view") this.view(/** @type {"diff"} */ (input.value));
      if (input.name !== "show") return;
      if (input.checked) this.hidden.delete(input.value);
      else this.hidden.add(input.value);
      this._applyHidden();
    });
    this._loadChanges(panel);
  }

  /** @param {Element} panel */
  async _loadChanges(panel) {
    const url = this.getAttribute("changes");
    if (!url) return;
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) return;
    /** @type {{guid: string, class: string, name: string, category: string}[]} */
    const rows = await response.json();
    const byGuid = new Map(rows.map((row) => [row.guid, row]));
    const caption = panel.querySelector(".model-caption");
    this.addEventListener("ifc-select", (event) => {
      const guid = /** @type {CustomEvent} */ (event).detail.guid;
      const row = byGuid.get(guid);
      if (!caption) return;
      caption.textContent = row ? `${row.class} ${row.name} · ${row.category.replace("_", " ")}` : "";
    });
  }
}

if (!customElements.get("ifc-viewer")) customElements.define("ifc-viewer", IfcViewer);
if (!customElements.get("ifc-diff")) customElements.define("ifc-diff", IfcDiff);

/** Table and 3D select each other. */
document.addEventListener("ifc-select", (event) => {
  const guid = /** @type {CustomEvent} */ (event).detail.guid;
  const table = document.querySelector(".model-table");
  if (!table) return;
  table.classList.toggle("model-filtered", Boolean(guid));
  for (const row of table.querySelectorAll("tr[data-guid]")) {
    row.classList.toggle("model-selected", row.getAttribute("data-guid") === guid);
  }
  table.querySelector("tr.model-selected")?.scrollIntoView({ block: "nearest" });
  const viewer = event.target;
  if (viewer instanceof IfcViewer) viewer.select(guid);
});

document.addEventListener("click", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  const row = target?.closest(".model-table tr[data-guid]");
  if (!row) return;
  const viewer = document.querySelector("ifc-diff, ifc-viewer");
  if (viewer instanceof IfcViewer) viewer.select(row.getAttribute("data-guid") || "");
});
