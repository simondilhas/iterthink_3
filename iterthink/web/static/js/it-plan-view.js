// @ts-check

/** Zoom and pan a plan page. Swipe reveals the earlier page. */

class PlanViewer extends HTMLElement {
  connectedCallback() {
    const stage = this.querySelector(".plan-stage");
    if (!(stage instanceof HTMLElement)) return;
    this._watch(stage);
    this._swipe();
  }

  /**
   * @param {HTMLElement} stage
   */
  _watch(stage) {
    let zoom = 1;
    let x = 0;
    let y = 0;
    /** @type {{px: number, py: number, x: number, y: number} | null} */
    let drag = null;
    const paint = () => {
      stage.style.transform = `translate(${x}px, ${y}px) scale(${zoom})`;
    };
    this.addEventListener(
      "wheel",
      (event) => {
        event.preventDefault();
        const next = event.deltaY < 0 ? 1.1 : 0.9;
        zoom = Math.min(8, Math.max(1, zoom * next));
        paint();
      },
      { passive: false },
    );
    stage.addEventListener("pointerdown", (event) => {
      drag = { px: event.clientX, py: event.clientY, x: x, y: y };
    });
    window.addEventListener("pointermove", (event) => {
      if (drag === null) return;
      x = drag.x + event.clientX - drag.px;
      y = drag.y + event.clientY - drag.py;
      paint();
    });
    window.addEventListener("pointerup", () => {
      drag = null;
    });
  }

  _swipe() {
    const range = this.querySelector(".plan-swipe");
    const before = this.querySelector(".plan-before");
    if (!(range instanceof HTMLInputElement) || !(before instanceof HTMLElement)) return;
    range.addEventListener("input", () => {
      const cut = 100 - Number(range.value);
      before.style.clipPath = `inset(0 ${cut}% 0 0)`;
    });
  }
}

customElements.define("plan-viewer", PlanViewer);
