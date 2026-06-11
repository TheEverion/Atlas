# Atlas Bridge - a tiny local helper for the Atlas UWorld extension.
#
# It exposes ONLY the handful of read-only actions Atlas needs (version,
# findNotes, notesInfo, retrieveMediaFile, guiBrowse) over the same
# 127.0.0.1:8765 endpoint AnkiConnect uses, so Atlas works as a drop-in.
#
# Design notes:
#  - The HTTP server runs in a background (daemon) thread, but EVERY call that
#    touches the Anki collection is marshalled onto Anki's main thread via
#    mw.taskman.run_on_main(). Anki's collection is not thread-safe, so this is
#    the part that matters - never read mw.col from the worker thread directly.
#  - CORS: the request comes from a chrome-extension:// origin. We allow Atlas's
#    fixed extension id (baked in below), plus localhost, plus no-origin. Any
#    other website is refused with 403, same protection AnkiConnect gives you.
#  - It binds 8765, so if AnkiConnect is also installed only one can run. Use one
#    or the other (see the README that came with this).

import base64
import json
import os
import re
import threading
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import aqt
from aqt import mw, gui_hooks
from aqt.utils import tooltip

API_VERSION = 6
HOST = "127.0.0.1"
DEFAULT_PORT = 8765
# Atlas's fixed extension id (from its manifest "key"). Requests from this
# origin are always allowed, so users never have to edit a CORS list.
ATLAS_ORIGIN = "chrome-extension://mpfeanjlkepajolaifdhpafhhofcoble"

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
    origins = {ATLAS_ORIGIN, "http://localhost", "http://127.0.0.1"}
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


def _yield_of(tags):
    """Pull the AnKing yield level from a note's tags, e.g.
    #AK_Step1_v12::#Low/HighYield::1-HighYield -> 'HighYield'."""
    for t in (tags or []):
        if "low/highyield" in t.lower():
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
                "type": c.type,
                "ivl": c.ivl,
                "lapses": c.lapses,
                "suspended": (c.queue == -1),
                "yield": ytag,
            })
        out.append(cards)
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
        try:
            req = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as exc:
            body = json.dumps({"result": None, "error": "bad JSON: %s" % exc}).encode("utf-8")
            self._reply(200, body, echo)
            return
        action = req.get("action", "")
        params = req.get("params", {}) or {}
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


# Bind once the main window exists (fires on the main thread).
gui_hooks.main_window_did_init.append(start_server)
