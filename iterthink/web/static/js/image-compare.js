// @ts-check

/** A before/after slider. Region boxes stay on the later image. */

class ImageCompare extends HTMLElement {
  connectedCallback() {
    queueMicrotask(() => this._bind());
  }

  _bind() {
    const range = this.querySelector("input");
    const after = this.querySelector(".image-after");
    const stage = this.querySelector(".image-stage");
    const picture = after instanceof HTMLElement ? after.querySelector("img") : null;
    if (!(range instanceof HTMLInputElement) || !(after instanceof HTMLElement)) return;
    if (!(picture instanceof HTMLImageElement) || !(stage instanceof HTMLElement)) return;
    const paint = () => {
      after.style.width = `${range.value}%`;
      picture.style.width = `${stage.clientWidth}px`;
      picture.style.height = `${stage.clientHeight}px`;
    };
    if (this.dataset.bound === "yes") {
      paint();
      return;
    }
    this.dataset.bound = "yes";
    range.addEventListener("input", paint);
    picture.addEventListener("load", paint);
    paint();
  }
}

if (!customElements.get("image-compare")) {
  customElements.define("image-compare", ImageCompare);
}

for (const node of document.querySelectorAll("image-compare")) {
  if (node instanceof ImageCompare) node._bind();
}
