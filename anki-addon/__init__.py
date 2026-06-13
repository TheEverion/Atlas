# Atlas Bridge - a tiny local helper for the Atlas UWorld extension.
#
# It exposes ONLY the handful of read-only actions Atlas needs (plus an
# atlasHealth ping) over 127.0.0.1:8766. That port is deliberately NOT
# AnkiConnect's 8765, so the two never collide - you can run both.
#
# Users never see a port or a JSON config: clicking "Config" on the add-on
# opens a small status window (see open_status_dialog) that just tells them
# whether Anki and the browser extension are talking.
#
# Design notes:
#  - The HTTP server runs in a background (daemon) thread, but EVERY call that
#    touches the Anki collection is marshalled onto Anki's main thread via
#    mw.taskman.run_on_main(). Anki's collection is not thread-safe, so this is
#    the part that matters - never read mw.col from the worker thread directly.
#  - CORS: the request comes from a chrome-extension:// origin. We allow Atlas's
#    fixed extension id (baked in below), plus localhost, plus no-origin. Any
#    other website is refused with 403.

import base64
import json
import os
import re
import threading
import time
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import aqt
from aqt import mw, gui_hooks
from aqt.utils import tooltip

API_VERSION = 6
ADDON_VERSION = "2.0"
HOST = "127.0.0.1"
DEFAULT_PORT = 8766
# Atlas's extension ids (derived from the manifest "key"). Requests from these
# origins are always allowed, so users never have to edit a CORS list.
# Chrome Web Store build (the published extension):
ATLAS_ORIGIN = "chrome-extension://nldpifnmnejhebgajmkfdijgianbahkj"
# Unpacked / source build (the key checked into the GitHub repo):
ATLAS_ORIGIN_UNPACKED = "chrome-extension://mpfeanjlkepajolaifdhpafhhofcoble"

# Links shown in the status window.
GUIDE_URL = "https://github.com/TheEverion/Atlas"
KOFI_URL = "https://ko-fi.com/atlasanki"

# The bridge remembers when the extension last called in, so the status window
# can say "connected recently" without the user having to do anything.
SEEN_WINDOW = 120  # seconds
_last_seen = {"t": 0.0}

_server = None


# ----------------------------- config -----------------------------
def _cfg():
    try:
        return mw.addonManager.getConfig(__name__) or {}
    except Exception:
        return {}


def _port():
    try:
        return int(_cfg().get("port", DEFAULT_PORT))
    except Exception:
        return DEFAULT_PORT


def _allowed_origins():
    origins = {ATLAS_ORIGIN, ATLAS_ORIGIN_UNPACKED,
               "http://localhost", "http://127.0.0.1"}
    for o in (_cfg().get("extraOrigins") or []):
        if isinstance(o, str):
            origins.add(o)
    return origins


# ---------------------- run work on the main thread ----------------------
def _on_main(func):
    box = {}
    done = threading.Event()

    def run():
        try:
            box["value"] = func()
        except Exception as exc:  # capture to re-raise on the worker thread
            box["error"] = exc
        finally:
            done.set()

    mw.taskman.run_on_main(run)
    if not done.wait(timeout=20):
        raise Exception("timed out waiting for Anki's main thread")
    if "error" in box:
        raise box["error"]
    return box.get("value")


# ----------------------------- the actions -----------------------------
def _collection():
    col = mw.col
    if col is None:
        raise Exception("no Anki collection is open")
    return col


def find_notes(query=None):
    if not query:
        return []
    return [int(nid) for nid in _collection().find_notes(query)]


def notes_info(notes=None, query=None):
    if query:
        notes = find_notes(query)
    notes = notes or []
    col = _collection()
    out = []
    for nid in notes:
        try:
            note = col.get_note(int(nid))
        except Exception:
            continue
        model = note.note_type()
        fields = {}
        for fld in model["flds"]:
            order = fld["ord"]
            fields[fld["name"]] = {"value": note.fields[order], "order": order}
        out.append({
            "noteId": note.id,
            "tags": note.tags,
            "fields": fields,
            "modelName": model["name"],
            "mod": note.mod,
        })
    return out


def retrieve_media_file(filename=None):
    if not filename:
        return False
    filename = unicodedata.normalize("NFC", os.path.basename(filename))
    path = os.path.join(_collection().media.dir(), filename)
    if os.path.exists(path):
        with open(path, "rb") as fh:
            return base64.b64encode(fh.read()).decode("ascii")
    return False


def gui_browse(query=None):
    browser = aqt.dialogs.open("Browser", mw)
    browser.activateWindow()
    if query:
        try:
            browser.form.searchEdit.lineEdit().setText(query)
            if hasattr(browser, "onSearch"):
                browser.onSearch()
            else:
                browser.onSearchActivated()
        except Exception:
            # fall back for other Anki versions
            if hasattr(browser, "search_for"):
                try:
                    browser.search_for(query)
                except Exception:
                    pass
            elif hasattr(browser, "search"):
                try:
                    browser.search()
                except Exception:
                    pass
    return []


# Parent-path markers for the AnKing yield project. v12 files it under
# "#Low/HighYield::"; older v11 decks use "^Other::^HighYield::". Both share the
# same leaf format (e.g. "1-HighYield"), so we accept either parent.
_YIELD_MARKERS = ("low/highyield", "^highyield")


def _yield_of(tags):
    """Pull the AnKing yield level from a note's tags, e.g.
    #AK_Step1_v12::#Low/HighYield::1-HighYield -> 'HighYield'
    (also handles v11: #AK_Step1_v11::^Other::^HighYield::1-HighYield)."""
    for t in (tags or []):
        tl = t.lower()
        if not any(m in tl for m in _YIELD_MARKERS):
            continue
        seg = re.sub(r"^\d+-", "", t.split("::")[-1]).strip().lower()
        if seg == "highyield":
            return "HighYield"
        if seg == "relativelyhighyield":
            return "RelativelyHighYield"
        if seg == "highyield-temporary":
            return "HighYield-temporary"
        if seg == "loweryield":
            return "LowerYield"
        if seg == "lowyield":
            return "LowYield"
    return None


def cards_for_queries(queries):
    """For each search, return one entry per linked card with the fields the
    preparedness model needs: type, interval, lapses, suspended, yield."""
    col = _collection()
    out = []
    for q in (queries or []):
        cards = []
        try:
            cids = col.find_cards(q)
        except Exception:
            cids = []
        for cid in cids:
            try:
                c = col.get_card(cid)
            except Exception:
                continue
            try:
                ytag = _yield_of(c.note().tags)
            except Exception:
                ytag = None
            cards.append({
                "cid": cid,
                "type": c.type,
                "ivl": c.ivl,
                "lapses": c.lapses,
                "suspended": (c.queue == -1),
                "yield": ytag,
            })
        out.append(cards)
    return out


def unsuspend_for_queries(queries, yields=None):
    """For each search, unsuspend any matching cards that are currently
    suspended. If `yields` is a non-empty list of yield levels (e.g.
    ["HighYield","RelativelyHighYield"]), only cards at those levels are
    touched. Returns per-query {matched, unlocked} counts."""
    col = _collection()
    want = set(yields) if yields else None
    out = []
    for q in (queries or []):
        try:
            cids = list(col.find_cards(q))
        except Exception:
            cids = []
        matched = 0
        locked = []
        for cid in cids:
            try:
                c = col.get_card(cid)
            except Exception:
                continue
            if want is not None:
                try:
                    if _yield_of(c.note().tags) not in want:
                        continue
                except Exception:
                    continue
            matched += 1
            if c.queue == -1:                       # -1 == suspended
                locked.append(cid)
        if locked:
            try:
                col.sched.unsuspend_cards(locked)
            except AttributeError:
                col.sched.unsuspendCards(locked)    # older Anki
        out.append({"matched": matched, "unlocked": len(locked)})
    return out


def maturity_for_queries(queries):
    """For each Anki search, classify its cards into maturity buckets.
    new / learning / young (<21d) / mature (>=21d) / suspended."""
    col = _collection()
    out = []
    for q in (queries or []):
        counts = {"new": 0, "learning": 0, "young": 0, "mature": 0, "suspended": 0, "total": 0}
        try:
            cids = col.find_cards(q)
        except Exception:
            cids = []
        for cid in cids:
            try:
                c = col.get_card(cid)
            except Exception:
                continue
            counts["total"] += 1
            if c.queue == -1:                      # suspended
                counts["suspended"] += 1
            elif c.type == 0:                      # new
                counts["new"] += 1
            elif c.type in (1, 3):                 # learning / relearning
                counts["learning"] += 1
            elif c.type == 2:                      # review
                if c.ivl >= 21:
                    counts["mature"] += 1
                else:
                    counts["young"] += 1
            else:
                counts["new"] += 1
        out.append(counts)
    return out


def get_tags():
    return list(_collection().tags.all())


def dispatch(action, params):
    if action == "version":
        return API_VERSION
    if action == "findNotes":
        return find_notes(params.get("query"))
    if action == "notesInfo":
        return notes_info(params.get("notes"), params.get("query"))
    if action == "retrieveMediaFile":
        return retrieve_media_file(params.get("filename"))
    if action == "guiBrowse":
        return gui_browse(params.get("query"))
    if action == "getTags":
        return get_tags()
    if action == "maturityForQueries":
        return maturity_for_queries(params.get("queries"))
    if action == "cardsForQueries":
        return cards_for_queries(params.get("queries"))
    if action == "unsuspendForQueries":
        return unsuspend_for_queries(params.get("queries"), params.get("yields"))
    raise Exception("Atlas Bridge does not support action: %s" % action)


# ------------------------------ HTTP layer ------------------------------
class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass  # stay quiet in Anki's console

    def _cors(self):
        origin = self.headers.get("Origin")
        if not origin:
            return True, "*"
        if origin in _allowed_origins():
            return True, origin
        return False, origin

    def _reply(self, code, body=b"", origin_echo="*"):
        self.send_response(code)
        self.send_header("Access-Control-Allow-Origin", origin_echo)
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_OPTIONS(self):
        _, echo = self._cors()
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", echo)
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        # Chrome's Private Network Access preflight for local addresses
        if (self.headers.get("Access-Control-Request-Private-Network", "").lower()
                == "true"):
            self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        allowed, echo = self._cors()
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        if not allowed:
            self._reply(403, b"", echo)
            return
        # Any allowed call means the extension is alive right now.
        _last_seen["t"] = time.time()
        try:
            req = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as exc:
            body = json.dumps({"result": None, "error": "bad JSON: %s" % exc}).encode("utf-8")
            self._reply(200, body, echo)
            return
        action = req.get("action", "")
        params = req.get("params", {}) or {}
        # Health check answers immediately, without marshalling to the main
        # thread, so the popup gets a fast "ready" even while Anki is busy.
        if action == "atlasHealth":
            body = json.dumps({
                "result": {"ok": True, "name": "Atlas Bridge", "version": ADDON_VERSION},
                "error": None,
            }).encode("utf-8")
            self._reply(200, body, echo)
            return
        try:
            result = _on_main(lambda: dispatch(action, params))
            body = json.dumps({"result": result, "error": None}).encode("utf-8")
        except Exception as exc:
            body = json.dumps({"result": None, "error": str(exc)}).encode("utf-8")
        self._reply(200, body, echo)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def start_server():
    global _server
    if _server is not None:
        return
    port = _port()
    try:
        _server = _Server((HOST, port), _Handler)
    except OSError:
        _server = None
        tooltip(
            "Atlas Bridge: port %d is already in use. If AnkiConnect is "
            "installed, disable it (they share this port)." % port,
            period=6000,
        )
        return
    threading.Thread(target=_server.serve_forever, daemon=True).start()


# --------------------------- status window ---------------------------
def _connected():
    return (time.time() - _last_seen["t"]) < SEEN_WINDOW


def open_status_dialog():
    """Shown when the user clicks 'Config' on the add-on. No JSON, no port -
    just whether Anki and the browser extension are talking to each other."""
    from aqt.qt import QDialog, QVBoxLayout, QLabel, QPushButton, QFrame, QTimer
    try:
        from aqt.utils import openLink as _open
    except Exception:
        from aqt.qt import QDesktopServices, QUrl
        _open = lambda u: QDesktopServices.openUrl(QUrl(u))
    try:
        from aqt.theme import theme_manager
        night = bool(theme_manager.night_mode)
    except Exception:
        night = False

    if night:
        text, muted = "#e3e7ee", "#9aa3b2"
        card_bg, card_bd = "#2a313e", "#3a4150"
        ok, warn = "#5fd17a", "#e6b450"
        ghost_bd, ghost_hover = "#3a4150", "#2a313e"
    else:
        text, muted = "#1b1b1b", "#5b6470"
        card_bg, card_bd = "#f2f6fc", "#dde6f2"
        ok, warn = "#0a8a0a", "#b8772a"
        ghost_bd, ghost_hover = "#cccccc", "#eef2f8"

    dlg = QDialog(mw)
    dlg.setWindowTitle("Atlas Bridge")
    dlg.setMinimumWidth(380)
    dlg.setStyleSheet(
        "QLabel{color:%s;}"
        "QPushButton{border-radius:8px;padding:9px 12px;font-size:13px;}"
        "QPushButton#kofi{background:#3b9ae1;color:#ffffff;border:none;font-weight:600;}"
        "QPushButton#kofi:hover{background:#2f86c9;}"
        "QPushButton#ghost{background:transparent;color:%s;border:1px solid %s;}"
        "QPushButton#ghost:hover{background:%s;}"
        "QFrame#card{background:%s;border:1px solid %s;border-radius:10px;}"
        % (text, text, ghost_bd, ghost_hover, card_bg, card_bd)
    )

    root = QVBoxLayout(dlg)
    root.setContentsMargins(18, 16, 18, 16)
    root.setSpacing(12)

    title = QLabel("\U0001F6E1\uFE0F  Atlas Bridge")
    title.setStyleSheet("font-size:17px;font-weight:700;color:%s;" % text)
    root.addWidget(title)

    card = QFrame()
    card.setObjectName("card")
    card_l = QVBoxLayout(card)
    card_l.setContentsMargins(14, 12, 14, 12)
    card_l.setSpacing(4)
    status = QLabel()
    sub = QLabel()
    sub.setWordWrap(True)
    sub.setStyleSheet("font-size:12px;color:%s;" % muted)
    card_l.addWidget(status)
    card_l.addWidget(sub)
    root.addWidget(card)

    hint = QLabel("Keep Anki open while reviewing UWorld.")
    hint.setWordWrap(True)
    hint.setStyleSheet("font-size:12px;color:%s;" % muted)
    root.addWidget(hint)

    def refresh():
        if _connected():
            status.setText("\u2705  Atlas is ready")
            status.setStyleSheet("font-size:14px;font-weight:600;color:%s;" % ok)
            sub.setText("Your browser extension connected recently.")
        else:
            status.setText("\u23F3  Waiting for the Atlas extension")
            status.setStyleSheet("font-size:14px;font-weight:600;color:%s;" % warn)
            sub.setText("Open UWorld and click the Atlas extension. "
                        "Atlas Bridge itself is installed correctly here.")

    refresh()

    refresh_btn = QPushButton("Refresh status")
    refresh_btn.setObjectName("ghost")
    refresh_btn.clicked.connect(refresh)
    root.addWidget(refresh_btn)

    guide_btn = QPushButton("\U0001F4D8  Setup guide")
    guide_btn.setObjectName("ghost")
    guide_btn.clicked.connect(lambda: _open(GUIDE_URL))
    root.addWidget(guide_btn)

    kofi_btn = QPushButton("\U0001F499  Support Atlas on Ko-fi")
    kofi_btn.setObjectName("kofi")
    kofi_btn.clicked.connect(lambda: _open(KOFI_URL))
    root.addWidget(kofi_btn)

    # Live-refresh so that simply opening the extension flips this to "ready".
    timer = QTimer(dlg)
    timer.timeout.connect(refresh)
    timer.start(2000)

    dlg.exec()


try:
    mw.addonManager.setConfigAction(__name__, open_status_dialog)
except Exception:
    pass


# Bind once the main window exists (fires on the main thread).
gui_hooks.main_window_did_init.append(start_server)
