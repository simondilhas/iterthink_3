// @ts-check

class MdPreview extends HTMLElement {
  connectedCallback() {
    const button = document.querySelector("#preview-toggle");
    if (!(button instanceof HTMLButtonElement) || button.dataset.bound === "1") return;
    button.dataset.bound = "1";
    const preview = this;
    button.addEventListener("click", () => {
      const show = preview.hasAttribute("hidden");
      preview.toggleAttribute("hidden", !show);
      const area = document.querySelector("md-editor textarea");
      if (area instanceof HTMLTextAreaElement) area.hidden = show;
      button.textContent = show ? "Edit" : "Preview";
    });
  }
}

if (!customElements.get("md-preview")) customElements.define("md-preview", MdPreview);
