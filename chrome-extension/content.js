(() => {
  "use strict";
  const BTN_HOST_ID = "akuts-buttons";
  const PANEL_ID = "akuts-resources";
  const OVERLAY_ID = "akuts-overlay";
  const SUMMARY_ID = "akuts-summary";
  const ANKING_VER = "v*"; // matches any AnKing version

  // ---------- talk to Anki via the background worker ----------
  function anki(action, params) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage({ type: "anki", action, params: params || {} }, resp => {
        if (chrome.runtime.lastError) return reject(chrome.runtime.lastError.message);
        if (!resp || !resp.ok) return reject((resp && resp.error) || "unknown error");
        resolve(resp.result);
      });
    });
  }
  function getSv() {
    return new Promise(r => chrome.storage.local.get({ sv: 1 }, c => r(c.sv)));
  }

  // ---------- styles (tuned to blend with UWorld) ----------
  const style = document.createElement("style");
  style.textContent = `
    #${BTN_HOST_ID}{display:inline-flex;gap:8px;margin-left:8px;vertical-align:middle}
    .akuts-btn{background:#2f7bd6;color:#fff;border:none;border-radius:6px;padding:8px 14px;font-size:14px;font-family:inherit;cursor:pointer;line-height:1.2}
    .akuts-btn:hover{filter:brightness(1.08)}
    .akuts-toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:#222;color:#fff;padding:10px 16px;border-radius:8px;font-size:14px;z-index:2147483647;box-shadow:0 4px 14px rgba(0,0,0,.3);max-width:80vw;text-align:center}

    /* resource card - mimics a UWorld panel */
    #${PANEL_ID}{margin:14px 0;font-family:inherit;color:#333;background:#fff;border:1px solid #dde2e7;border-radius:8px;display:block;position:relative;z-index:1}
    #${PANEL_ID}.akuts-float{position:fixed;right:16px;bottom:16px;width:400px;max-height:60vh;overflow:auto;z-index:2147483646;box-shadow:0 6px 20px rgba(0,0,0,.18)}
    #${PANEL_ID} table{border-collapse:collapse;width:100%;font-size:14px;background:#fff}
    #${PANEL_ID} td{border:none;border-bottom:1px solid #eef1f4;padding:9px 12px;vertical-align:top;line-height:1.45}
    #${PANEL_ID} tr:last-child td{border-bottom:none}
    #${PANEL_ID} td.akuts-res{font-weight:600;white-space:nowrap;color:#16395b;border-left:3px solid #ccc;width:96px}
    #${PANEL_ID} a{color:#1b69b6;text-decoration:underline;display:block;margin:3px 0}
    #${PANEL_ID} a:hover{color:#0f4f8c}
    #${PANEL_ID} .akuts-path{display:block;margin:3px 0;color:#555}
    #${PANEL_ID} .akuts-group{margin:0 0 9px}
    #${PANEL_ID} .akuts-group:last-child{margin-bottom:0}
    #${PANEL_ID} .akuts-parent{font-size:12px;color:#8a8f98;margin-bottom:2px}
    #${PANEL_ID} .akuts-leaf-row{padding:1px 0 1px 10px}
    #${PANEL_ID} .akuts-leaf{font-weight:600;color:#243240}
    #${PANEL_ID} .akuts-watch{display:inline-block;color:#1b69b6;text-decoration:underline;font-size:12px;margin-left:8px;white-space:nowrap}
    #${PANEL_ID} .akuts-msg{font-size:13px;color:#667;padding:11px 12px}
    #${PANEL_ID} .akuts-note{font-size:12px;color:#778;padding:8px 12px;border-top:1px solid #eef1f4;background:#fafbfc}

    /* fullscreen image overlay (modal) */
    #${OVERLAY_ID}{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:2147483646;align-items:flex-start;justify-content:center;padding:4vh 0}
    #${OVERLAY_ID} .akuts-dialog{background:#fff;width:90vw;max-height:92vh;overflow:auto;border-radius:10px;padding:14px 16px 18px;box-shadow:0 12px 40px rgba(0,0,0,.4);font-family:inherit;color:#333}
    #${OVERLAY_ID} .akuts-ovl-head{display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #e6e9ec;padding-bottom:8px;margin-bottom:12px}
    #${OVERLAY_ID} .akuts-ovl-head b{font-size:16px;color:#16395b}
    #${OVERLAY_ID} .akuts-ovl-hint{font-size:12px;color:#999;margin-left:8px}
    #${OVERLAY_ID} .akuts-x{border:none;background:transparent;font-size:28px;line-height:1;cursor:pointer;color:#666;padding:0 6px;border-radius:6px}
    #${OVERLAY_ID} .akuts-x:hover{color:#000;background:#f0f0f0}
    #${OVERLAY_ID} .akuts-ovl-img{display:block;width:100%;height:auto;margin:0 0 12px}

    /* dark mode */
    #${PANEL_ID}.akuts-dark{background:#1f2430;border-color:#3a4150;color:#d8dce4}
    #${PANEL_ID}.akuts-dark table{background:transparent}
    #${PANEL_ID}.akuts-dark td{border-bottom-color:#2c3340}
    #${PANEL_ID}.akuts-dark tr:last-child td{border-bottom:none}
    #${PANEL_ID}.akuts-dark td.akuts-res{color:#e6ebf4}
    #${PANEL_ID}.akuts-dark a{color:#5aa9f0}
    #${PANEL_ID}.akuts-dark a:hover{color:#8cc4f7}
    #${PANEL_ID}.akuts-dark .akuts-path{color:#9aa3b2}
    #${PANEL_ID}.akuts-dark .akuts-parent{color:#8b94a3}
    #${PANEL_ID}.akuts-dark .akuts-leaf{color:#e6ebf4}
    #${PANEL_ID}.akuts-dark .akuts-msg{color:#9aa3b2}
    #${PANEL_ID}.akuts-dark .akuts-note{color:#8b94a3;border-top-color:#2c3340;background:#181c26}
    #${OVERLAY_ID}.akuts-dark .akuts-dialog{background:#1f2430;color:#d8dce4}
    #${OVERLAY_ID}.akuts-dark .akuts-ovl-head{border-bottom-color:#3a4150}
    #${OVERLAY_ID}.akuts-dark .akuts-ovl-head b{color:#e6ebf4}
    #${OVERLAY_ID}.akuts-dark .akuts-ovl-hint{color:#8b94a3}
    #${OVERLAY_ID}.akuts-dark .akuts-x{color:#aab2c0}
    #${OVERLAY_ID}.akuts-dark .akuts-x:hover{color:#fff;background:#2c3340}

    .akuts-es{background:#2a9d8f}
    #${PANEL_ID} .akuts-expected{font-size:12.5px;padding:7px 10px;border-radius:6px;margin-bottom:10px;border-left:3px solid #b9bdc4;background:#f4f6f8;color:#333}
    #${PANEL_ID} .akuts-expected.good{border-left-color:#2e9e4f;background:#eef7f0}
    #${PANEL_ID} .akuts-expected.warn{border-left-color:#e0901f;background:#fdf4e6}
    #${PANEL_ID}.akuts-dark .akuts-expected{background:#262c38;color:#cdd6e5;border-left-color:#5a6472}
    #${PANEL_ID}.akuts-dark .akuts-expected.good{background:#1f2e25;border-left-color:#3fa05f}
    #${PANEL_ID}.akuts-dark .akuts-expected.warn{background:#322a1c;border-left-color:#c8881f}

    #${SUMMARY_ID}{display:none;position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:2147483646;align-items:flex-start;justify-content:center;padding:6vh 0;font-family:system-ui,Arial,sans-serif}
    #${SUMMARY_ID} .akuts-sum-dialog{background:#fff;width:min(560px,92vw);max-height:86vh;overflow:auto;border-radius:10px;padding:16px 18px 20px;box-shadow:0 12px 40px rgba(0,0,0,.4);color:#333}
    #${SUMMARY_ID} .akuts-sum-head{display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #e6e9ec;padding-bottom:8px;margin-bottom:12px}
    #${SUMMARY_ID} .akuts-sum-head span{font-weight:600;font-size:16px;color:#16395b}
    #${SUMMARY_ID} .akuts-sum-row{display:flex;gap:10px;margin-bottom:10px}
    #${SUMMARY_ID} .akuts-metric{flex:1;background:#f4f6f8;border-radius:8px;padding:10px 12px;text-align:center}
    #${SUMMARY_ID} .akuts-metric-v{font-size:22px;font-weight:600;color:#16395b}
    #${SUMMARY_ID} .akuts-metric-l{font-size:12px;color:#667;margin-top:2px}
    #${SUMMARY_ID} .akuts-sum-note{font-size:12.5px;color:#667;margin-bottom:12px;line-height:1.5}
    #${SUMMARY_ID} .akuts-sum-lbl{font-size:13px;font-weight:600;color:#243240;margin:6px 0}
    #${SUMMARY_ID} .akuts-sum-item{display:flex;align-items:baseline;justify-content:space-between;gap:10px;padding:6px 0;border-top:1px solid #eef1f4;font-size:13px}
    #${SUMMARY_ID} a{color:#1b69b6;text-decoration:underline;font-size:12px;white-space:nowrap}
    #${SUMMARY_ID} .akuts-sum-score{text-align:center;margin:2px 0 14px}
    #${SUMMARY_ID} .akuts-score-v{font-size:34px;font-weight:700;color:#16395b;line-height:1.1}
    #${SUMMARY_ID} .akuts-score-l{display:block;font-size:12px;color:#778;margin-top:3px}
    #${SUMMARY_ID} .akuts-cov{margin:0 0 14px}
    #${SUMMARY_ID} .akuts-cov-bar{height:8px;border-radius:5px;background:#e6e9ec;overflow:hidden}
    #${SUMMARY_ID} .akuts-cov-fill{height:100%;background:#2a9d8f;border-radius:5px;min-width:2px}
    #${SUMMARY_ID} .akuts-cov-lbl{font-size:12px;color:#778;margin-top:5px}
    #${SUMMARY_ID} .akuts-conf{display:inline-block;font-size:12px;font-weight:600;padding:4px 11px;border-radius:12px;margin:0 0 11px}
    #${SUMMARY_ID} .akuts-conf-high{background:#e3f4e8;color:#1f7a3d}
    #${SUMMARY_ID} .akuts-conf-medium{background:#e7f0fb;color:#1b5fae}
    #${SUMMARY_ID} .akuts-conf-low{background:#fdf0dd;color:#a86412}
    #${SUMMARY_ID} .akuts-conf-insufficient{background:#eceef0;color:#6a727c}
    #${SUMMARY_ID} .akuts-x{border:none;background:transparent;font-size:26px;line-height:1;cursor:pointer;color:#666;padding:0 4px}
    #${SUMMARY_ID} .akuts-x:hover{color:#000}
    #${SUMMARY_ID}.akuts-dark .akuts-sum-dialog{background:#1f2430;color:#d8dce4}
    #${SUMMARY_ID}.akuts-dark .akuts-sum-head{border-bottom-color:#3a4150}
    #${SUMMARY_ID}.akuts-dark .akuts-sum-head span{color:#e6ebf4}
    #${SUMMARY_ID}.akuts-dark .akuts-metric{background:#262c38}
    #${SUMMARY_ID}.akuts-dark .akuts-metric-v{color:#e6ebf4}
    #${SUMMARY_ID}.akuts-dark .akuts-metric-l{color:#9aa3b2}
    #${SUMMARY_ID}.akuts-dark .akuts-sum-note{color:#9aa3b2}
    #${SUMMARY_ID}.akuts-dark .akuts-sum-lbl{color:#e6ebf4}
    #${SUMMARY_ID}.akuts-dark .akuts-sum-item{border-top-color:#2c3340}
    #${SUMMARY_ID}.akuts-dark a{color:#5aa9f0}
    #${SUMMARY_ID}.akuts-dark .akuts-score-v{color:#e6ebf4}
    #${SUMMARY_ID}.akuts-dark .akuts-score-l{color:#9aa3b2}
    #${SUMMARY_ID}.akuts-dark .akuts-cov-bar{background:#2c3340}
    #${SUMMARY_ID}.akuts-dark .akuts-cov-lbl{color:#9aa3b2}
    #${SUMMARY_ID}.akuts-dark .akuts-conf-high{background:#1f2e25;color:#5fd17a}
    #${SUMMARY_ID}.akuts-dark .akuts-conf-medium{background:#1d2a3a;color:#6ab0f0}
    #${SUMMARY_ID}.akuts-dark .akuts-conf-low{background:#322a1c;color:#e0a94a}
    #${SUMMARY_ID}.akuts-dark .akuts-conf-insufficient{background:#262c38;color:#9aa3b2}
  `;
  document.documentElement.appendChild(style);

  // ---------- dark mode + expected score ----------
  let darkMode = false;
  let esOn = false;
  function applyTheme() {
    const p = document.getElementById(PANEL_ID); if (p) p.classList.toggle("akuts-dark", darkMode);
    const o = document.getElementById(OVERLAY_ID); if (o) o.classList.toggle("akuts-dark", darkMode);
  }
  chrome.storage.local.get({ dark: false, expectedScore: false }, c => { darkMode = !!c.dark; esOn = !!c.expectedScore; applyTheme(); });
  chrome.storage.onChanged.addListener((changes, area) => {
    if (area !== "local") return;
    if (changes.dark) { darkMode = !!changes.dark.newValue; applyTheme(); }
    if (changes.expectedScore) { esOn = !!changes.expectedScore.newValue; }
  });

  function toast(text) {
    const t = document.createElement("div");
    t.className = "akuts-toast";
    t.textContent = text;
    (document.body || document.documentElement).appendChild(t);
    setTimeout(() => t.remove(), 4500);
  }

  // ============================================================
  // FEATURE 1 - buttons on the test RESULTS page
  // ============================================================
  function qidFromCell(cell) { return cell ? cell.textContent.split("-").pop().trim() : ""; }
  function collectAll() {
    const cells = document.querySelectorAll(".mat-column-id");
    const out = [];
    for (let i = 1; i < cells.length; i++) { const q = qidFromCell(cells[i]); if (q) out.push(q); }
    return out;
  }
  function collectByIcon(sel) {
    const out = [];
    document.querySelectorAll(sel).forEach(ic => {
      const row = ic.closest('[role="row"], tr, mat-row');
      const q = qidFromCell(row && row.querySelector(".mat-column-id"));
      if (q) out.push(q);
    });
    return out;
  }
  function buildTagQuery(qids, sv) {
    return qids.map(q => "tag:#AK_Step" + sv + "_" + ANKING_VER + "::#UWorld::*::" + q).join(" OR ");
  }
  function runBrowse(qids) {
    if (!qids.length) { toast("No matching questions found on this page."); return; }
    getSv().then(sv => {
      const query = buildTagQuery(qids, sv);
      anki("guiBrowse", { query }).catch(e =>
        toast("Couldn't reach Anki. Make sure it's open and the Atlas add-on is installed. (" + e + ")"));
    });
  }
  function makeBtn(label, getQids) {
    const b = document.createElement("button");
    b.textContent = label;
    b.className = "review-button akuts-btn";
    b.addEventListener("click", () => runBrowse(getQids()));
    return b;
  }
  function addButtons(toolbar) {
    const host = document.createElement("span");
    host.id = BTN_HOST_ID;
    host.appendChild(makeBtn("Anki: Missed", () => collectByIcon(".mat-column-flag i.fa-times")));
    host.appendChild(makeBtn("Anki: All", () => collectAll()));
    host.appendChild(makeBtn("Anki: Marked", () => collectByIcon(".mat-column-flag i.fas.fa-bookmark")));
    toolbar.appendChild(host);
  }

  // ============================================================
  // FEATURE 2 - resource table + image overlay on the REVIEW page
  // ============================================================
  const RESOURCES = [
    { label: "Sketchy",         color: "#1aa7e0", fields: ["Sketchy", "Sketchy 2", "Sketchy Extra"], tag: "#Sketchy" },
    { label: "Bootcamp",        color: "#8e63d6", fields: ["Bootcamp"], tag: "#Bootcamp" },
    { label: "Boards & Beyond", color: "#2f9e44", fields: ["Boards & Beyond", "Boards and Beyond", "B&B"], tag: ["#B&B", "#BoardsandBeyond", "#Boards_and_Beyond"] },
    { label: "Physeo",          color: "#27a39a", fields: ["Physeo"], tag: "#Physeo" },
    { label: "Pixorize",        color: "#ec6aa0", fields: ["Pixorize"], tag: "#Pixorize" },
    { label: "First Aid",       color: "#f0a020", fields: ["First Aid"], tag: "#FirstAid" }
  ];
  const IMG_SOURCES = {
    F: { label: "First Aid", fields: ["First Aid"] },
    S: { label: "Sketchy",   fields: ["Sketchy", "Sketchy 2", "Sketchy Extra"] },
    P: { label: "Pixorize",  fields: ["Pixorize"] }
  };
  let lastQid = null;
  let currentFiles = { F: [], S: [], P: [] };
  let cachedUris = { F: null, S: null, P: null };
  const dedupe = a => Array.from(new Set(a));

  function findQid() {
    const scope = document.querySelector("nbmev2-header") || document.body;
    const m = (scope.textContent || "").match(/Question\s*Id:\s*(\d+)/i);
    return m ? m[1] : null;
  }
  // The explanation has no height until you submit, so this is effectively
  // "has this question been answered yet?"
  function isAnswered() {
    const ex = document.querySelector("#explanation");
    return !!(ex && ex.offsetHeight > 1);
  }
  function cleanSeg(s) {
    return s
      .replace(/^[!*\s]+/, "")        // leading ! or * markers
      .replace(/^\d+[_\-.]\s*/, "")   // leading number prefix: 03_  06-  1.
      .replace(/_/g, " ")
      .trim();
  }
  function isNoiseSeg(s) {
    return /^\^/.test(s)                  // tracking tags: ^physeo_image_update, ^Missing_image
        || /retired/i.test(s)             // ##_Retired_Lessons
        || /old[\s_]*version/i.test(s)    // [OLD VERSION]
        || /\[old/i.test(s)
        || /alt[_\s]*tagging/i.test(s)    // 03_Neoplasia_Alt_Tagging
        || /^pathoma\s*20\d{2}/i.test(s)  // Pathoma2018 (old edition)
        || /^20\d{2}$/.test(s);           // a bare old-edition year
  }
  function tagPaths(tags, needles) {
    const arr = (Array.isArray(needles) ? needles : [needles]).map(s => s.toLowerCase());
    const out = [];
    for (const t of (tags || [])) {
      const tl = t.toLowerCase();
      if (!arr.some(nd => tl.includes(nd))) continue;
      const seg = t.split("::");
      const rest = seg.slice(2);                  // chapters after #AK_Step1_v12::<resource>
      if (!rest.length || rest.some(isNoiseSeg)) continue;
      let cleaned = rest.map(cleanSeg).filter(Boolean);
      if (cleaned.length > 1 && /^extra$/i.test(cleaned[cleaned.length - 1])) cleaned.pop();
      if (!cleaned.length) continue;
      out.push(cleaned.slice(-3));               // keep the last 3 segments
    }
    return out;
  }
  function fieldAnchors(note, names) {
    const out = [];
    const parser = new DOMParser();
    names.forEach(n => {
      const f = note.fields && note.fields[n];
      if (!f || !f.value) return;
      const doc = parser.parseFromString(f.value, "text/html");
      doc.querySelectorAll("a[href]").forEach(a => {
        const href = a.getAttribute("href");
        if (href) out.push({ href, text: a.textContent.trim() || href });
      });
    });
    return out;
  }
  function fieldImages(note, names) {
    const out = [];
    const parser = new DOMParser();
    names.forEach(n => {
      const f = note.fields && note.fields[n];
      if (!f || !f.value) return;
      const doc = parser.parseFromString(f.value, "text/html");
      doc.querySelectorAll("img[src]").forEach(img => {
        const src = img.getAttribute("src");
        if (src) out.push(src);
      });
    });
    return out;
  }
  function mimeFor(fn) {
    const ext = (fn.split(".").pop() || "").toLowerCase();
    if (ext === "jpg" || ext === "jpeg") return "image/jpeg";
    if (ext === "gif") return "image/gif";
    if (ext === "webp") return "image/webp";
    if (ext === "svg") return "image/svg+xml";
    return "image/png";
  }
  async function fetchImages(files) {
    const uris = [];
    for (const fn of files) {
      try {
        const b64 = await anki("retrieveMediaFile", { filename: fn });
        if (b64) uris.push("data:" + mimeFor(fn) + ";base64," + b64);
      } catch (e) { /* skip a file we can't fetch */ }
    }
    return uris;
  }
  function ensurePanel() {
    let panel = document.getElementById(PANEL_ID);
    if (panel) { panel.classList.toggle("akuts-dark", darkMode); return panel; }
    panel = document.createElement("div");
    panel.id = PANEL_ID;
    if (darkMode) panel.classList.add("akuts-dark");
    const anchor = document.querySelector("#questionInformation");
    if (anchor) anchor.appendChild(panel);
    else { panel.classList.add("akuts-float"); document.body.appendChild(panel); }
    return panel;
  }
  // If UWorld squashes or hides the in-flow card, pop it out as a floating card.
  function ensureVisible() {
    const p = document.getElementById(PANEL_ID);
    if (!p || p.classList.contains("akuts-float")) return;
    const r = p.getBoundingClientRect();
    if (p.offsetParent === null || r.height < 2 || r.width < 2) {
      p.classList.add("akuts-float");
      document.body.appendChild(p);
    }
  }
  function akNorm(s) { return (s || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim(); }
  function akLinkTopic(text) {
    return akNorm(text)
      .replace(/^watch\s+/, "").replace(/^associated\s+/, "")
      .replace(/^(bootcamp|sketchy)\s+/, "").replace(/^video\s+/, "").trim();
  }
  function akTokens(s) { return akNorm(s).split(" ").filter(w => w.length > 2); }
  function akClose(a, b) {            // true if within ~1 character edit (typo tolerance)
    if (a === b) return true;
    if (Math.abs(a.length - b.length) > 1) return false;
    let i = 0, j = 0, edits = 0;
    while (i < a.length && j < b.length) {
      if (a[i] === b[j]) { i++; j++; continue; }
      if (++edits > 1) return false;
      if (a.length > b.length) i++;
      else if (b.length > a.length) j++;
      else { i++; j++; }
    }
    if (i < a.length || j < b.length) edits++;
    return edits <= 1;
  }
  function akTokenFound(w, arr) {
    for (const t of arr) { if (w === t) return true; if (w.length >= 4 && akClose(w, t)) return true; }
    return false;
  }
  function makeLink(href, text, cls) {
    const a = document.createElement("a");
    a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer";
    a.textContent = text; if (cls) a.className = cls;
    return a;
  }
  // grouped-by-chapter view; a leaf gets an inline "Watch" if a video link matches it
  function renderResource(td, paths, links) {
    links = links.slice();
    if (!paths.length) {
      links.forEach(l => td.appendChild(makeLink(l.href, l.text, "akuts-link")));
      return;
    }
    const leaves = paths.map(segs => ({ parent: segs.slice(0, -1).join(" \u203A "), leaf: segs[segs.length - 1] }));
    const linkTokens = links.map(l => akTokens(akLinkTopic(l.text)));
    const TH = 0.6;                 // a topic matches a video if >=60% of its words appear in it
    const pairs = [];
    leaves.forEach((lf, li) => {
      const L = akTokens(lf.leaf);
      if (!L.length) return;
      links.forEach((lk, ki) => {
        let hit = 0; for (const w of L) if (akTokenFound(w, linkTokens[ki])) hit++;
        const score = hit / L.length;
        if (score >= TH) pairs.push({ li, ki, score });
      });
    });
    pairs.sort((a, b) => b.score - a.score);   // assign strongest matches first
    const used = new Set(), usedLeaf = new Set();
    for (const p of pairs) {
      if (usedLeaf.has(p.li) || used.has(p.ki)) continue;
      leaves[p.li].watch = links[p.ki].href;
      usedLeaf.add(p.li); used.add(p.ki);
    }
    const order = []; const groups = new Map();
    for (const lf of leaves) {
      if (!groups.has(lf.parent)) { groups.set(lf.parent, []); order.push(lf.parent); }
      groups.get(lf.parent).push(lf);
    }
    for (const parent of order) {
      const g = document.createElement("div");
      g.className = "akuts-group";
      if (parent) {
        const ph = document.createElement("div");
        ph.className = "akuts-parent"; ph.textContent = parent;
        g.appendChild(ph);
      }
      for (const lf of groups.get(parent)) {
        const r = document.createElement("div");
        r.className = "akuts-leaf-row";
        const ls = document.createElement("span");
        ls.className = "akuts-leaf"; ls.textContent = lf.leaf;
        r.appendChild(ls);
        if (lf.watch) r.appendChild(makeLink(lf.watch, "Watch", "akuts-watch"));
        g.appendChild(r);
      }
      td.appendChild(g);
    }
    const leftover = links.filter((_, i) => !used.has(i));
    if (leftover.length) {
      const g = document.createElement("div");
      g.className = "akuts-group";
      leftover.forEach(l => g.appendChild(makeLink(l.href, l.text, "akuts-link")));
      td.appendChild(g);
    }
  }
  function renderRows(qid, rows, msg) {
    const panel = ensurePanel();
    panel.replaceChildren();
    if (msg) {
      const n = document.createElement("div"); n.className = "akuts-msg"; n.textContent = msg; panel.appendChild(n); ensureVisible(); return;
    }
    if (!rows || !rows.length) {
      const n = document.createElement("div"); n.className = "akuts-msg";
      n.textContent = "No AnKing resources found for this question."; panel.appendChild(n); ensureVisible(); return;
    }
    const table = document.createElement("table");
    const tb = document.createElement("tbody");
    for (const row of rows) {
      const tr = document.createElement("tr");
      const td1 = document.createElement("td");
      td1.className = "akuts-res";
      td1.textContent = row.R.label;
      td1.style.borderLeftColor = row.R.color;
      const td2 = document.createElement("td");
      renderResource(td2, row.paths, row.links);
      tr.appendChild(td1); tr.appendChild(td2);
      tb.appendChild(tr);
    }
    table.appendChild(tb);
    panel.appendChild(table);
    ensureVisible();
  }
  function addImageHint() {
    const panel = document.getElementById(PANEL_ID);
    if (!panel) return;
    const bits = [];
    if (currentFiles.F.length) bits.push("F = First Aid");
    if (currentFiles.S.length) bits.push("S = Sketchy");
    if (currentFiles.P.length) bits.push("P = Pixorize");
    if (!bits.length) return;
    const n = document.createElement("div");
    n.className = "akuts-note";
    n.textContent = "Images - press " + bits.join("  /  ") + "  (press again, Esc, or X to close)";
    panel.appendChild(n);
  }
  async function buildTable(qid) {
    currentFiles = { F: [], S: [], P: [] };
    cachedUris = { F: null, S: null, P: null };
    hideOverlay();

    let sv; try { sv = await getSv(); } catch (e) { sv = 1; }
    const query = "tag:#AK_Step" + sv + "_" + ANKING_VER + "::#UWorld::*::" + qid;
    let nids;
    try { nids = await anki("findNotes", { query }); }
    catch (e) { renderRows(qid, null, "Couldn't reach Anki. Make sure it's open and the Atlas add-on is installed. (" + e + ")"); return; }
    if (!nids.length) { renderRows(qid, []); return; }
    let notes;
    try { notes = await anki("notesInfo", { notes: nids }); }
    catch (e) { renderRows(qid, null, "Anki error: " + e); return; }

    const rows = [];
    for (const R of RESOURCES) {
      const links = []; const paths = []; const seenP = new Set();
      for (const note of notes) {
        fieldAnchors(note, R.fields).forEach(l => links.push(l));
        tagPaths(note.tags, R.tag).forEach(p => { const k = p.join(" \u203A "); if (!seenP.has(k)) { seenP.add(k); paths.push(p); } });
      }
      const seen = new Set();
      const ulinks = links.filter(l => !seen.has(l.href) && seen.add(l.href));
      if (ulinks.length || paths.length) rows.push({ R, links: ulinks, paths });
    }
    renderRows(qid, rows);

    for (const key of Object.keys(IMG_SOURCES)) {
      const fnames = [];
      for (const note of notes) fieldImages(note, IMG_SOURCES[key].fields).forEach(f => fnames.push(f));
      currentFiles[key] = dedupe(fnames);
    }
    addImageHint();
    ensureVisible();
    if (esOn) addExpectedLine(qid);
  }

  // ---------- image overlay (modal with X / backdrop / Esc) ----------
  function ensureOverlay() {
    let o = document.getElementById(OVERLAY_ID);
    if (o) { o.classList.toggle("akuts-dark", darkMode); return o; }
    o = document.createElement("div");
    o.id = OVERLAY_ID;
    if (darkMode) o.classList.add("akuts-dark");
    o.addEventListener("click", e => { if (e.target === o) hideOverlay(); }); // click backdrop closes
    document.body.appendChild(o);
    return o;
  }
  function hideOverlay() {
    const o = document.getElementById(OVERLAY_ID);
    if (o) { o.style.display = "none"; o.replaceChildren(); } // drop image data so Brave can free it
  }
  function buildHead(o, label, key) {
    const head = document.createElement("div");
    head.className = "akuts-ovl-head";
    const title = document.createElement("span");
    const b = document.createElement("b"); b.textContent = label;
    const hint = document.createElement("span"); hint.className = "akuts-ovl-hint";
    hint.textContent = "press " + key + " or Esc to close";
    title.appendChild(b); title.appendChild(hint);
    const x = document.createElement("button");
    x.className = "akuts-x"; x.textContent = "\u00d7"; x.title = "Close";
    x.addEventListener("click", () => hideOverlay());
    head.appendChild(title); head.appendChild(x);
    return head;
  }
  function renderOverlayMessage(o, label, key, msg) {
    o.dataset.key = key; o.style.display = "flex"; o.replaceChildren();
    const dlg = document.createElement("div"); dlg.className = "akuts-dialog";
    dlg.appendChild(buildHead(o, label, key));
    const n = document.createElement("div"); n.textContent = msg; dlg.appendChild(n);
    o.appendChild(dlg);
  }
  function renderOverlay(o, key, label) {
    o.dataset.key = key; o.style.display = "flex"; o.replaceChildren();
    const dlg = document.createElement("div"); dlg.className = "akuts-dialog";
    dlg.appendChild(buildHead(o, label, key));
    const uris = cachedUris[key] || [];
    if (!uris.length) {
      const n = document.createElement("div"); n.textContent = "(couldn't load images)"; dlg.appendChild(n);
    } else {
      uris.forEach(u => { const img = document.createElement("img"); img.src = u; img.className = "akuts-ovl-img"; dlg.appendChild(img); });
    }
    o.appendChild(dlg);
  }
  async function showImages(key) {
    const src = IMG_SOURCES[key];
    const existing = document.getElementById(OVERLAY_ID);
    if (existing && existing.style.display === "flex" && existing.dataset.key === key) {
      hideOverlay(); return; // same key hides it
    }
    if (!lastQid) return;
    const files = currentFiles[key] || [];
    if (!files.length) { toast("No " + src.label + " image for this question."); return; }
    const o = ensureOverlay();
    if (!cachedUris[key]) {
      renderOverlayMessage(o, src.label, key, "Loading...");
      cachedUris[key] = await fetchImages(files);
    }
    renderOverlay(o, key, src.label);
  }
  document.addEventListener("keydown", e => {
    const o = document.getElementById(OVERLAY_ID);
    const k = (e.key || "").toLowerCase();
    if (k === "escape") { const su = document.getElementById(SUMMARY_ID); if (su && su.style.display === "flex") closeSummary(); if (o && o.style.display === "flex") hideOverlay(); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const tgt = e.target;
    const tag = ((tgt && tgt.tagName) || "").toLowerCase();
    if (tag === "input" || tag === "textarea" || (tgt && tgt.isContentEditable)) return;
    if (k === "f") showImages("F");
    else if (k === "s") showImages("S");
    else if (k === "p") showImages("P");
  });

  // ---------- main loop ----------
  setInterval(() => {
    const toolbar = document.querySelector(".test-performance-top-div");
    if (toolbar && !document.getElementById(BTN_HOST_ID)) addButtons(toolbar);
    const host = document.getElementById(BTN_HOST_ID);
    if (host) syncExpectedButton(host);

    const qid = findQid();
    const ready = qid && isAnswered();
    if (ready) {
      if (qid !== lastQid) { lastQid = qid; buildTable(qid); }
    } else {
      lastQid = null;
      currentFiles = { F: [], S: [], P: [] };
      cachedUris = { F: null, S: null, P: null };
      const p = document.getElementById(PANEL_ID);
      if (p) p.remove();
      hideOverlay();
    }
  }, 1000);

  // ============================================================
  // Expected Score (Beta)
  // ============================================================
  const ES_GUESS = 0.2;   // 5-option MCQ guess floor
  const YIELD_W = { HighYield: 2.0, RelativelyHighYield: 1.6, "HighYield-temporary": 1.4, LowerYield: 0.8, LowYield: 0.5 };
  function qidQuery(qid, sv) { return "tag:#AK_Step" + sv + "_" + ANKING_VER + "::#UWorld::*::" + qid; }
  // probability you know one card's fact right now (0..1)
  function cardMaturity(c) {
    if (c.type === 2) {                                // review card
      const eff = Math.max((c.ivl || 0) * Math.pow(0.7, c.lapses || 0), (c.ivl || 0) * 0.4);
      return 1 / (1 + Math.exp(-0.1 * (eff - 21)));    // sigmoid: 21d -> 0.5
    }
    if (c.type === 1 || c.type === 3) return 0.15;     // learning / relearning
    return 0;                                          // new
  }
  function yieldWeight(y) { return (y && YIELD_W[y]) || 1.0; }
  // yield-weighted preparedness for one question's cards -> {prep,n,review} or null
  function prepFor(cards) {
    const usable = (cards || []).filter(c => !c.suspended);
    if (!usable.length) return null;                   // uncovered
    let sw = 0, swm = 0, review = 0;
    for (const c of usable) {
      const w = yieldWeight(c.yield);
      sw += w; swm += w * cardMaturity(c);
      if (c.type === 2) review++;
    }
    return { prep: sw > 0 ? swm / sw : 0, n: usable.length, review };
  }
  // mixture w/ guess floor: either you know it (~prep) or you guess (~20%)
  function predFrom(prep) { return ES_GUESS + (1 - ES_GUESS) * prep; }
  // reliability of the estimate (geometric mean of four factors)
  function confidence(details, nTotal) {
    const cov = details.filter(Boolean);
    const nCov = cov.length;
    if (!nCov) return { score: 0, label: "Insufficient" };
    const coverage = Math.min(1, nCov / (0.5 * nTotal));
    const sumInv = cov.reduce((s, q) => s + (q.n > 0 ? 1 / q.n : 0), 0);
    const H = sumInv > 0 ? nCov / sumInv : 0;
    const density = Math.min(1, H / 4);
    const sample = Math.min(1, nCov / 10);
    const totalCards = cov.reduce((s, q) => s + q.n, 0);
    const reviewCards = cov.reduce((s, q) => s + q.review, 0);
    const quality = totalCards > 0 ? reviewCards / totalCards : 0;
    const score = Math.pow(coverage * density * sample * quality, 0.25);
    const label = score >= 0.7 ? "High" : score >= 0.4 ? "Medium" : score >= 0.15 ? "Low" : "Insufficient";
    return { score, label };
  }
  const ES_MSG = {
    mature_wrong: ["Oof \u2014 your cards say you knew this one.", "Mature in Anki but missed \u2014 sneaky one, or a slip.", "Your reviews had this down. Go revisit it.", "This was in your wheelhouse \u2014 worth a careful look.", "You'd matured this. Don't let it slide."],
    mature_right: ["Nailed it \u2014 and your cards backed you up.", "Solid. Your reps clearly paid off.", "Matured and correct. Textbook.", "Clean hit \u2014 well-drilled.", "Your Anki grind showed here. Nice."],
    mature_unknown: ["Your cards on this are mature.", "Well-drilled in Anki.", "This one's locked in your reviews."],
    mid_wrong: ["Still bedding this one in \u2014 fair enough.", "Young card, missed it. It'll stick soon.", "Not matured yet \u2014 keep the reps up.", "This one's still settling in Anki."],
    mid_right: ["Got it while it's still young \u2014 nice.", "Correct, and it's still settling. Bonus.", "Ahead of your reviews on this one.", "Young card, right answer \u2014 good sign."],
    mid_unknown: ["Still young in your reviews.", "This one's settling in Anki.", "Halfway home on this card."],
    low_wrong: ["Barely started this in Anki \u2014 no shame.", "Fresh card, fair miss. It's coming.", "Hardly reviewed yet \u2014 expected.", "Early days for this one."],
    low_right: ["Correct on a card you've barely touched \u2014 clutch.", "Reasoned that one out before Anki caught up.", "Got it ahead of your reviews. Slick.", "Nice \u2014 that wasn't from the deck yet."],
    low_unknown: ["Barely reviewed in Anki yet.", "Fresh in your deck.", "Early days for this card."],
    none_wrong: ["Not in your deck yet \u2014 totally fair miss.", "No card for this one. Can't fault you.", "Off-deck question \u2014 not on you.", "Your deck doesn't cover this yet."],
    none_right: ["Not in your deck \u2014 pure reasoning. Respect.", "No card for this, and you still got it. Nice.", "Off-deck and correct \u2014 real understanding.", "Deck doesn't cover this \u2014 you earned that one."],
    none_unknown: ["Not in your deck yet.", "No matching card for this one.", "Your deck doesn't cover this question."]
  };
  function esPick(a) { return a[Math.floor(Math.random() * a.length)]; }
  function phraseFor(chance, correct) {
    const band = chance === null ? "none" : chance >= 0.8 ? "mature" : chance >= 0.45 ? "mid" : "low";
    const who = correct === true ? "right" : correct === false ? "wrong" : "unknown";
    return esPick(ES_MSG[band + "_" + who] || ES_MSG[band + "_unknown"]);
  }
  function expectedStatus(chance, correct) {
    if (chance !== null && chance >= 0.8 && correct === false) return "warn";
    if (correct === true) return "good";
    return "";
  }
  function answerResult() {
    const txt = ((document.querySelector("nbmev2-header") || document.body).textContent || "");
    if (/answered\s+incorrectly/i.test(txt)) return false;
    if (/answered\s+correctly/i.test(txt)) return true;
    return null;                                        // couldn't tell
  }
  async function addExpectedLine(qid) {
    let sv; try { sv = await getSv(); } catch (e) { sv = 1; }
    let cards;
    try { const r = await anki("cardsForQueries", { queries: [qidQuery(qid, sv)] }); cards = r && r[0]; }
    catch (e) { return; }
    if (lastQid !== qid) return;                        // moved on while waiting
    const panel = document.getElementById(PANEL_ID);
    if (!panel || document.getElementById("akuts-expected")) return;
    const d = prepFor(cards);
    const chance = d ? d.prep : null;
    const correct = answerResult();
    const line = document.createElement("div");
    line.id = "akuts-expected";
    line.className = "akuts-expected " + expectedStatus(chance, correct);
    line.textContent = phraseFor(chance, correct);
    panel.insertBefore(line, panel.firstChild);
  }
  function syncExpectedButton(host) {
    const ID = "akuts-es-btn";
    const existing = document.getElementById(ID);
    if (esOn && !existing) {
      const b = document.createElement("button");
      b.id = ID; b.textContent = "Expected Score"; b.className = "review-button akuts-btn akuts-es";
      b.addEventListener("click", () => computeSummary());
      host.appendChild(b);
    } else if (!esOn && existing) { existing.remove(); }
  }
  function openInAnki(qid) { getSv().then(sv => anki("guiBrowse", { query: qidQuery(qid, sv) }).catch(() => {})); }
  async function computeSummary() {
    const cells = document.querySelectorAll(".mat-column-id");
    const items = [];
    for (let i = 1; i < cells.length; i++) {
      const qid = qidFromCell(cells[i]);
      if (!qid) continue;
      const row = cells[i].closest('[role="row"], tr, mat-row');
      const wrong = !!(row && row.querySelector(".mat-column-flag i.fa-times"));
      items.push({ qid, correct: !wrong });
    }
    if (!items.length) { toast("No questions found on this page."); return; }
    let sv; try { sv = await getSv(); } catch (e) { sv = 1; }
    let byQ;
    try { byQ = await anki("cardsForQueries", { queries: items.map(it => qidQuery(it.qid, sv)) }); }
    catch (e) { toast("Couldn't reach Anki. Make sure it's open and the Atlas add-on is installed. (" + e + ")"); return; }
    items.forEach((it, i) => {
      const d = prepFor(byQ[i]);
      it.detail = d;
      it.prep = d ? d.prep : null;
      it.pred = d ? predFrom(d.prep) : null;
    });
    renderSummary(items);
  }
  function metric(label, value) {
    const d = document.createElement("div"); d.className = "akuts-metric";
    const v = document.createElement("div"); v.className = "akuts-metric-v"; v.textContent = value;
    const l = document.createElement("div"); l.className = "akuts-metric-l"; l.textContent = label;
    d.appendChild(v); d.appendChild(l); return d;
  }
  function closeSummary() { const o = document.getElementById(SUMMARY_ID); if (o) { o.style.display = "none"; o.replaceChildren(); } }
  function renderSummary(items) {
    const total = items.length;
    const overallCorrect = items.filter(it => it.correct).length;
    const overallPct = total ? Math.round(100 * overallCorrect / total) : 0;
    const covered = items.filter(it => it.pred !== null);
    const nCov = covered.length;
    const correctCov = covered.filter(it => it.correct).length;
    const expectedPct = nCov ? Math.round(100 * covered.reduce((s, it) => s + it.pred, 0) / nCov) : null;
    const actualPct = nCov ? Math.round(100 * correctCov / nCov) : null;
    const conf = confidence(covered.map(it => it.detail), total);
    const covPct = total ? Math.round(100 * nCov / total) : 0;
    const missed = covered.filter(it => !it.correct).sort((a, b) => b.prep - a.prep);

    let o = document.getElementById(SUMMARY_ID);
    if (!o) {
      o = document.createElement("div"); o.id = SUMMARY_ID;
      o.addEventListener("click", e => { if (e.target === o) closeSummary(); });
      document.body.appendChild(o);
    }
    o.classList.toggle("akuts-dark", darkMode);
    o.style.display = "flex"; o.replaceChildren();

    const dlg = document.createElement("div"); dlg.className = "akuts-sum-dialog";
    const head = document.createElement("div"); head.className = "akuts-sum-head";
    const h = document.createElement("span"); h.textContent = "Expected score (beta)";
    const x = document.createElement("button"); x.className = "akuts-x"; x.textContent = "\u00d7"; x.title = "Close";
    x.addEventListener("click", closeSummary);
    head.appendChild(h); head.appendChild(x); dlg.appendChild(head);

    // A — the score you already know from UWorld
    const score = document.createElement("div"); score.className = "akuts-sum-score";
    const sval = document.createElement("span"); sval.className = "akuts-score-v"; sval.textContent = overallPct + "%";
    const slbl = document.createElement("span"); slbl.className = "akuts-score-l"; slbl.textContent = "your block score \u00b7 " + overallCorrect + " of " + total;
    score.appendChild(sval); score.appendChild(slbl); dlg.appendChild(score);

    // B — how much of the block AnKing can even evaluate
    const cov = document.createElement("div"); cov.className = "akuts-cov";
    const bar = document.createElement("div"); bar.className = "akuts-cov-bar";
    const fill = document.createElement("div"); fill.className = "akuts-cov-fill"; fill.style.width = covPct + "%";
    bar.appendChild(fill);
    const covLbl = document.createElement("div"); covLbl.className = "akuts-cov-lbl";
    covLbl.textContent = nCov + " of " + total + " questions matched to AnKing (" + covPct + "%)";
    cov.appendChild(bar); cov.appendChild(covLbl); dlg.appendChild(cov);

    if (!nCov) {
      const p = document.createElement("div"); p.className = "akuts-sum-note";
      p.textContent = "Not enough data \u2014 none of these questions matched a card in your deck yet.";
      dlg.appendChild(p); o.appendChild(dlg); return;
    }

    // C — preparedness analysis, scoped to the covered questions only
    const sub = document.createElement("div"); sub.className = "akuts-sum-lbl";
    sub.textContent = "On the " + nCov + " covered question" + (nCov === 1 ? "" : "s") + ":";
    dlg.appendChild(sub);

    const row = document.createElement("div"); row.className = "akuts-sum-row";
    const gap = actualPct - expectedPct;
    row.appendChild(metric("Expected", expectedPct + "%"));
    row.appendChild(metric("You got", actualPct + "%"));
    row.appendChild(metric("Gap", (gap >= 0 ? "+" : "") + gap + " pts"));
    dlg.appendChild(row);

    const badge = document.createElement("div");
    badge.className = "akuts-conf akuts-conf-" + conf.label.toLowerCase();
    badge.textContent = "Confidence: " + conf.label;
    dlg.appendChild(badge);

    const note = document.createElement("div"); note.className = "akuts-sum-note";
    const interp = gap > 4 ? "you beat what your reviews predicted \u2014 reasoning, outside knowledge, or luck filled the gap."
      : gap < -4 ? "you came in under \u2014 these may have tested angles your cards don't cover."
      : "right about where your Anki history predicted.";
    const trust = conf.label === "High" ? "This estimate is well-supported."
      : conf.label === "Medium" ? "Reasonable, but limited data \u2014 use with some caution."
      : conf.label === "Low" ? "Rough estimate \u2014 directionally informative only."
      : "Very thin data \u2014 treat as a loose approximation.";
    note.textContent = "Your Anki prep predicted ~" + expectedPct + "% on these; you got " + actualPct + "% \u2014 " + interp + " " + trust + " \u201cExpected\u201d weighs card maturity by yield and floors at ~20% for guessing \u2014 it's a guide, not a grade.";
    dlg.appendChild(note);

    const lbl = document.createElement("div"); lbl.className = "akuts-sum-lbl";
    lbl.textContent = missed.length ? "Missed \u2014 best-prepared first (worth a look):" : "No covered questions missed \u2014 nice.";
    dlg.appendChild(lbl);
    missed.forEach(it => {
      const r = document.createElement("div"); r.className = "akuts-sum-item";
      const left = document.createElement("span");
      left.textContent = "QID " + it.qid + "  \u00b7  " + Math.round(it.prep * 100) + "% prepared";
      const a = document.createElement("a"); a.href = "#"; a.textContent = "open in Anki";
      a.addEventListener("click", e => { e.preventDefault(); openInAnki(it.qid); });
      r.appendChild(left); r.appendChild(a);
      dlg.appendChild(r);
    });
    o.appendChild(dlg);
  }
})();