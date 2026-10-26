// @ts-check

function readyForm(id) {
  return document.getElementById("ready-" + id);
}

function bindBoard() {
  document.querySelectorAll(".task-card[data-status=backlog]").forEach((card) => {
    card.addEventListener("dragstart", (event) => {
      if (!(event instanceof DragEvent) || event.dataTransfer === null) return;
      event.dataTransfer.setData("text/plain", card.getAttribute("data-task") || "");
    });
  });
  const ready = document.querySelector('[data-column="ready"]');
  if (ready === null) return;
  ready.addEventListener("dragover", (event) => {
    event.preventDefault();
  });
  ready.addEventListener("drop", (event) => {
    event.preventDefault();
    if (!(event instanceof DragEvent) || event.dataTransfer === null) return;
    const form = readyForm(event.dataTransfer.getData("text/plain"));
    if (form instanceof HTMLFormElement) form.requestSubmit();
  });
}

bindBoard();
