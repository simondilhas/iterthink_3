// @ts-check

/**
 * @typedef {Window & { pywebview?: { api?: { choose_folder?: () => Promise<string | null> } } }} HostWindow
 */

class FolderPicker extends HTMLElement {
  connectedCallback() {
    const host = /** @type {HostWindow} */ (window);
    if (host.pywebview) {
      this.addButton();
    } else {
      window.addEventListener("pywebviewready", () => this.addButton(), { once: true });
    }
  }

  addButton() {
    if (this.querySelector("button[data-choose]")) return;
    const button = document.createElement("button");
    button.dataset.choose = "";
    button.type = "button";
    button.textContent = "Choose…";
    button.addEventListener("click", () => {
      void this.pick();
    });
    this.append(button);
  }

  async pick() {
    const host = /** @type {HostWindow} */ (window);
    const path = await host.pywebview?.api?.choose_folder?.();
    const input = this.querySelector("input");
    if (typeof path === "string" && input instanceof HTMLInputElement) input.value = path;
  }
}

customElements.define("it-folder-picker", FolderPicker);
