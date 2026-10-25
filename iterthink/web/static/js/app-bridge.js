// @ts-check

/** Inside the frame. Talks to the parent. Does not fetch. */

const names = ["listFiles", "readFile", "history", "search", "compare", "propose"];

/**
 * @param {string} name
 * @param {object} args
 */
function call(name, args) {
  return new Promise(function (resolve) {
    const id = String(Date.now());
    function onMessage(event) {
      const data = event.data;
      if (!data || data.id !== id) return;
      window.removeEventListener("message", onMessage);
      resolve(data.result);
    }
    window.addEventListener("message", onMessage);
    parent.postMessage({ id: id, name: name, args: args || {} }, "*");
  });
}

/** @type {Record<string, (args?: object) => Promise<unknown>>} */
const bridge = {};
names.forEach(function (name) {
  bridge[name] = function (args) {
    return call(name, args || {});
  };
});
window.bridge = bridge;
