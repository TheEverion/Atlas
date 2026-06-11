// Background service worker. ALL Anki requests happen here (not in the page),
// so UWorld's in-page request blocking can't break them.

const ANKI_URL = "http://127.0.0.1:8765";

async function ankiInvoke(action, params = {}) {
  const res = await fetch(ANKI_URL, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, version: 6, params })
  });
  const data = await res.json();
  if (data && data.error) throw new Error(data.error);
  return data.result;
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.type === "anki") {
    ankiInvoke(msg.action, msg.params || {})
      .then(result => sendResponse({ ok: true, result }))
      .catch(err => sendResponse({ ok: false, error: String((err && err.message) || err) }));
    return true; // async response
  }
});
