// @ts-check

/**
 * @param {KeyboardEvent} event
 */
function isMod(event) {
  return event.metaKey || event.ctrlKey;
}

document.addEventListener(
  "keydown",
  (event) => {
    if (event.key !== "Enter" || !(event.target instanceof HTMLInputElement)) return;
    if (event.target.id !== "line") return;
    const form = event.target.form;
    if (!(form instanceof HTMLFormElement)) return;
    if (event.shiftKey) {
      event.preventDefault();
      return;
    }
    if (isMod(event)) {
      event.preventDefault();
      form.requestSubmit();
    }
  },
  true,
);

document.addEventListener("it-recall", () => {
  const line = document.querySelector("#line");
  if (line instanceof HTMLInputElement) line.focus();
});
