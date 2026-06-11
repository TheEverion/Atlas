const sel = document.getElementById("sv");
const saved = document.getElementById("saved");
const darkToggle = document.getElementById("darkToggle");
const esToggle = document.getElementById("esToggle");

function applyDark(on) {
  document.body.classList.toggle("dark", on);
  darkToggle.checked = on;
}

chrome.storage.local.get({ sv: 1, dark: false, expectedScore: false }, cfg => {
  sel.value = String(cfg.sv);
  applyDark(!!cfg.dark);
  esToggle.checked = !!cfg.expectedScore;
});

sel.addEventListener("change", () => {
  const sv = parseInt(sel.value, 10) || 1;
  chrome.storage.local.set({ sv }, () => {
    saved.textContent = "Saved \u2014 applies on your next click.";
    setTimeout(() => (saved.textContent = ""), 2500);
  });
});

darkToggle.addEventListener("change", () => {
  const on = darkToggle.checked;
  document.body.classList.toggle("dark", on);
  chrome.storage.local.set({ dark: on });
});

esToggle.addEventListener("change", () => {
  chrome.storage.local.set({ expectedScore: esToggle.checked });
});
