// @ts-check

/** A file dropped on the screen is a new version, or a question about where it goes. */

function projectId() {
  const match = location.pathname.match(/^\/p\/([^/]+)/);
  return match ? match[1] : "";
}

document.addEventListener("dragover", (event) => {
  if (projectId()) event.preventDefault();
});

document.addEventListener("drop", (event) => {
  const id = projectId();
  const file = event.dataTransfer?.files[0];
  if (!id || !file) return;
  event.preventDefault();
  const body = new FormData();
  body.append("file", file);
  fetch(`/p/${id}/incoming/drop`, { method: "POST", body }).then((response) => {
    if (response.redirected) {
      location.href = response.url;
      return;
    }
    response.text().then((html) => {
      const main = document.querySelector("#main");
      if (main instanceof HTMLElement) main.innerHTML = html;
    });
  });
});
