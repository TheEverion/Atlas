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
ADDON_VERSION = "2.9"
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


def _set_cfg(key, value):
    try:
        cfg = mw.addonManager.getConfig(__name__) or {}
        cfg[key] = value
        mw.addonManager.writeConfig(__name__, cfg)
        return True
    except Exception:
        return False


def _port():
    try:
        return int(_cfg().get("port", DEFAULT_PORT))
    except Exception:
        return DEFAULT_PORT


# Whether block sessions count as real reviews. This lives on the Anki side, not in
# the browser popup: it decides what happens to the user's scheduling, so it belongs
# next to the collection it affects (and the popup was getting crowded).
def _block_reschedule():
    return _cfg().get("blockReschedule", True) is not False


def _set_block_reschedule(on):
    _set_cfg("blockReschedule", bool(on))
    tooltip("Atlas: block reps %s." % (
        "count as real reviews" if on else "are preview only - no scheduling change"),
        period=3500)


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


# --------------------------- block sessions ---------------------------
# A "block session" is: unsuspend what a UWorld block matched, gather it into a
# filtered deck, study just that, then put everything back.
#
# Filtered decks cannot gather suspended, buried, or already-filtered cards - see
# the hint button in aqt/filtered_deck.py, whose whole job is listing cards excluded
# for those reasons. So unsuspending FIRST is mandatory, and that is exactly why the
# rollback has to exist: we record the cards we unlocked so finishing can re-lock
# those and nothing else.

def _sessions_path():
    # user_files survives add-on updates; the rest of the add-on folder does not.
    d = os.path.join(os.path.dirname(__file__), "user_files")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return os.path.join(d, "sessions.json")


def _load_sessions():
    try:
        with open(_sessions_path(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_sessions(sessions):
    try:
        with open(_sessions_path(), "w", encoding="utf-8") as fh:
            json.dump(sessions, fh)
    except Exception:
        pass


def _ids2str(ids):
    return "(" + ",".join(str(int(i)) for i in ids) + ")"


def _matching_cards(col, query, want):
    """Card ids for a search, optionally narrowed to a set of yield levels."""
    try:
        cids = list(col.find_cards(query))
    except Exception:
        return []
    if want is None:
        return cids
    out = []
    for cid in cids:
        try:
            if _yield_of(col.get_card(cid).note().tags) in want:
                out.append(cid)
        except Exception:
            continue
    return out


def _next_block_no(sessions):
    """Blocks are numbered, not named after their contents - "Atlas - Block 7" is an
    identity, whereas "Atlas - 15 questions" reads like a card count sitting right next
    to Anki's actual card columns, which is exactly the confusion to avoid.

    Numbered among the sessions still OPEN, so once you've finished everything the next
    block starts back at 1 rather than climbing forever. All the number has to guarantee
    is that two decks on screen at once can't share it, and finishing a session deletes
    its deck - so counting finished ones bought nothing and just looked odd on a
    freshly cleaned-up collection."""
    n = 0
    for s in sessions:
        if s.get("finished"):
            continue
        try:
            n = max(n, int(s.get("block") or 0))
        except Exception:
            continue
    return n + 1


def _unique_deck_name(col, base):
    base = base.replace("::", " ").strip() or "block"     # "::" would make a subdeck
    name, n = base, 2
    while True:
        try:
            if not col.decks.id_for_name(name):
                return name
        except Exception:
            return name
        name = "%s (%d)" % (base, n)
        n += 1


def _build_filtered_deck(col, name, query, limit, reschedule):
    from anki.decks import DeckId, FilteredDeckConfig
    deck = col.sched.get_or_create_filtered_deck(deck_id=DeckId(0))
    deck.name = name
    cfg = deck.config
    cfg.reschedule = reschedule
    del cfg.search_terms[:]
    cfg.search_terms.extend([
        FilteredDeckConfig.SearchTerm(
            search=query + " -is:suspended",
            limit=max(int(limit), 1),          # the stock limit is far too low for a block
            order=FilteredDeckConfig.SearchTerm.ADDED,
        )
    ])
    return col.sched.add_or_update_filtered_deck(deck).id


def _answered_since(col, cids, since_ms):
    """Cards with a real answer logged after the session started. revlog.id is an
    epoch-ms timestamp; button_chosen == 0 marks manual/rescheduled entries rather
    than answers. Preview reviews are logged too, so this works in both modes."""
    if not cids or not since_ms:
        return set()
    try:
        rows = col.db.list(
            "select distinct cid from revlog where id > ? and button_chosen > 0 "
            "and cid in %s" % _ids2str(cids), since_ms)
        return set(int(r) for r in rows)
    except Exception:
        return set()


def start_block(queries=None, yields=None, label=None, reschedule=None, questions=None):
    """Unsuspend a block's cards, gather them into their own filtered deck, and
    drop the user straight into reviewing it.

    `reschedule` is normally None: the setting lives in Anki (Atlas menu). An
    explicit value still wins, so an older extension that sends its own toggle
    keeps working."""
    col = _collection()
    query = (queries or [None])[0]
    if not query:
        raise Exception("no query given")
    if reschedule is None:
        reschedule = _block_reschedule()
    started_ms = int(time.time() * 1000)

    want = set(yields) if yields else None
    matched = _matching_cards(col, query, want)
    if not matched:
        return {"sessionId": None, "matched": 0, "unsuspended": 0, "gathered": 0}

    locked = []
    for cid in matched:
        try:
            if col.get_card(cid).queue == -1:          # -1 == suspended
                locked.append(cid)
        except Exception:
            continue
    if locked:
        try:
            col.sched.unsuspend_cards(locked)
        except AttributeError:
            col.sched.unsuspendCards(locked)          # older Anki

    sessions = _load_sessions()
    block_no = _next_block_no(sessions)
    name = _unique_deck_name(col, "Atlas - Block %d" % block_no)
    try:
        did = _build_filtered_deck(col, name, query, len(matched), bool(reschedule))
    except Exception:
        # Anki refuses to build a filtered deck that would gather nothing, and raises
        # rather than returning an empty one. That means every matched card is held by
        # ANOTHER filtered deck (Anki Maxer and friends) or is buried. We have already
        # unsuspended by this point, so undo it - otherwise the collection is left
        # changed with no session recorded to undo it with.
        if locked:
            try:
                col.sched.suspend_cards(locked)
            except AttributeError:
                col.sched.suspendCards(locked)
        return {"sessionId": None, "matched": len(matched), "unsuspended": 0,
                "gathered": 0, "blocked": True, "reschedule": bool(reschedule)}

    # Anything short of `matched` is held by another filtered deck (or is buried);
    # the caller reports the gap rather than quietly under-delivering.
    try:
        gathered = len(col.decks.cids(did))
    except Exception:
        gathered = 0

    # Older extensions send a text label ("15 questions") instead of a count.
    if questions is None:
        m = re.match(r"\s*(\d+)", str(label or ""))
        questions = int(m.group(1)) if m else 0

    sess = {
        "id": str(started_ms),
        "block": block_no,
        "created": int(time.time()),
        "startedMs": started_ms,
        "questions": int(questions or 0),   # UWorld questions picked
        "gathered": int(gathered),          # cards that made it into the deck
        "deckId": int(did),
        "deckName": name,
        "reschedule": bool(reschedule),
        "unsuspended": [int(c) for c in locked],   # the undo scope
        "finished": False,
    }
    sessions.append(sess)
    _save_sessions(sessions)

    try:
        col.decks.select(did)
        mw.moveToState("review")
    except Exception:
        pass

    return {"sessionId": sess["id"], "matched": len(matched),
            "unsuspended": len(locked), "gathered": gathered,
            "reschedule": bool(reschedule)}   # so the page can report the mode used


def _reap_deleted_decks():
    """If the user deleted a session's deck by hand, the session is over - that IS the
    signal that they're done with it. So put it away properly rather than leaving a row
    they can't get rid of: re-lock whatever it unlocked (minus anything they answered)
    and retire the entry. Announced with a tooltip, so it is never silent."""
    try:
        col = _collection()
        from anki.decks import DeckId
    except Exception:
        return 0
    reaped = 0
    for s in list(_load_sessions()):
        if s.get("finished") or not s.get("deckId"):
            continue
        try:
            if col.decks.name_if_exists(DeckId(int(s["deckId"]))) is not None:
                continue                       # deck still there - leave it alone
        except Exception:
            continue
        try:
            res = finish_block(s.get("id"))    # re-loads the ledger itself, so this is safe
            reaped += 1
            n = res.get("resuspended", 0)
            tooltip("Atlas: %s was deleted, so the session was closed%s."
                    % (s.get("deckName") or "that deck",
                       (" - %d card(s) put back" % n) if n else ""),
                    period=4000)
        except Exception:
            pass
    return reaped


def list_blocks():
    """Every count is named, because three different ones are in play: questions
    picked, cards gathered into the deck, and cards to re-lock on finish."""
    _reap_deleted_decks()
    out = []
    try:
        col = _collection()
    except Exception:
        col = None
    sessions = _load_sessions()
    retired = False
    for s in sessions:
        if s.get("finished"):
            continue
        # Deleting the deck by hand does NOT finish the session - the cards stay
        # unlocked and the entry lingers. Flag it so the UI can say so, because the
        # Finish button is still the only thing that will re-lock them.
        deck_gone = False
        if col is not None and s.get("deckId"):
            try:
                from anki.decks import DeckId
                deck_gone = col.decks.name_if_exists(DeckId(int(s["deckId"]))) is None
            except Exception:
                deck_gone = False
        # Deck deleted by hand AND nothing left to put back: this session can never do
        # anything again, so retire it rather than leave a dead row cluttering the list.
        # One WITH cards to re-lock is kept - those cards are still unlocked in the
        # collection and Finish is the only thing that will suspend them again.
        if deck_gone and not (s.get("unsuspended") or []):
            s["finished"] = True
            s["finishedAt"] = int(time.time())
            retired = True
            continue
        block = s.get("block")
        out.append({
            "id": s.get("id"),
            "block": block,
            # sessions created before numbering fall back to their old label
            "title": ("Block %d" % block) if block else (s.get("label") or s.get("deckName") or "Block"),
            "questions": int(s.get("questions") or 0),
            "gathered": int(s.get("gathered") or 0),
            "cards": len(s.get("unsuspended") or []),   # will be re-locked on finish
            "created": s.get("created"),
            "deckName": s.get("deckName"),
            "deckGone": deck_gone,
            "reschedule": bool(s.get("reschedule", True)),
        })
    if retired:
        _save_sessions(sessions)
    return out


def finish_block(sessionId=None):
    """Put a session away: return its cards home, delete the temp deck, and re-lock
    the cards it unlocked - except the ones actually answered, which have earned
    their place. In preview mode nothing was earned, so everything goes back."""
    col = _collection()
    sessions = _load_sessions()
    sess = None
    for s in sessions:
        if s.get("id") == sessionId:
            sess = s
            break
    if sess is None:
        raise Exception("no such Atlas session")

    did = sess.get("deckId")
    returned = 0
    if did:
        try:
            returned = len(col.decks.cids(int(did)))
        except Exception:
            returned = 0
        try:
            col.sched.empty_filtered_deck(int(did))    # cards go back to their home decks
        except Exception:
            pass
        try:
            col.decks.remove([int(did)])
        except Exception:
            pass

    recorded = [int(c) for c in (sess.get("unsuspended") or [])]
    keep = set()
    if sess.get("reschedule", True):
        keep = _answered_since(col, recorded, int(sess.get("startedMs") or 0))

    # Never re-lock a card some other open session is still holding.
    held = set()
    for s in sessions:
        if s is sess or s.get("finished"):
            continue
        held.update(int(c) for c in (s.get("unsuspended") or []))

    to_lock = [c for c in recorded if c not in keep and c not in held]
    if to_lock:
        try:
            col.sched.suspend_cards(to_lock)           # unknown ids are ignored
        except AttributeError:
            col.sched.suspendCards(to_lock)            # older Anki

    sess["finished"] = True
    sess["finishedAt"] = int(time.time())
    sess["resuspended"] = len(to_lock)
    sess["unsuspended"] = []      # done with the undo scope; a big block stored hundreds of ids
    _save_sessions(sessions)
    return {"returned": returned, "resuspended": len(to_lock), "kept": len(keep)}


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


def _anki_version():
    try:
        from anki.buildinfo import version
        return str(version)
    except Exception:
        pass
    try:
        return str(aqt.appVersion)
    except Exception:
        return "?"


# Census of the UWorld tag layouts actually present. This is the one thing that
# explains almost every "it finds no cards" report: either the exam picked in the
# popup doesn't match any step here, or the deck's tags are a layout Atlas isn't
# matching, or the deck has no #UWorld tags at all. Counts only - no tag text, no
# card content, nothing personal, so it is safe to paste into a DM.
_UW_RE = re.compile(r"^#AK_Step(\d)_v(\d+)::#UWorld::(.+)$")
_FLAT_RE = re.compile(r"^\d+$")
_NESTED_RE = re.compile(r"^[^:]+(?:::[^:]+)*::\d+$")
_YIELD_RE = re.compile(r"^#AK_Step(\d)_v(\d+)::(?:#Low/HighYield|\^Other::\^HighYield)::")


def diagnostics():
    out = {"addon": ADDON_VERSION, "anki": _anki_version()}
    try:
        tags = list(_collection().tags.all())
    except Exception:
        tags = []
    out["tagsTotal"] = len(tags)

    uworld, yields = {}, set()
    for t in tags:
        m = _UW_RE.match(t)
        if m:
            key = "Step%s_v%s" % (m.group(1), m.group(2))
            d = uworld.setdefault(key, {"nested": 0, "flat": 0, "other": 0})
            rest = m.group(3)
            if _FLAT_RE.match(rest):
                d["flat"] += 1
            elif _NESTED_RE.match(rest):
                d["nested"] += 1
            else:
                d["other"] += 1
            continue
        y = _YIELD_RE.match(t)
        if y:
            yields.add("Step%s_v%s" % (y.group(1), y.group(2)))
    out["uworld"] = uworld
    out["yield"] = sorted(yields)

    try:
        out["notes"] = _collection().note_count()
    except Exception:
        pass
    try:
        out["openSessions"] = len(list_blocks())
    except Exception:
        pass
    return out


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
    if action == "startBlock":
        return start_block(params.get("queries"), params.get("yields"),
                           params.get("label"), params.get("reschedule"),
                           params.get("questions"))
    if action == "listBlocks":
        return list_blocks()
    if action == "diagnostics":
        return diagnostics()
    if action == "finishBlock":
        return finish_block(params.get("sessionId"))
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


# --------------------------- shared UI bits ---------------------------
def _openlink(url):
    try:
        from aqt.utils import openLink
        openLink(url)
    except Exception:
        try:
            from aqt.qt import QDesktopServices, QUrl
            QDesktopServices.openUrl(QUrl(url))
        except Exception:
            pass


def _finish_message(info):
    n = info["cards"] if info else 0
    if info is not None and not info["reschedule"]:
        return ("Put this session away?\n\nThe temporary deck is removed and all %d "
                "card(s) Atlas unlocked go back to suspended. This was a preview "
                "session, so no scheduling was changed." % n)
    return ("Put this session away?\n\nThe temporary deck is removed. Cards you "
            "answered stay in your reviews; the rest of the %d card(s) Atlas "
            "unlocked are suspended again." % n)


def _confirm_and_finish(sid, parent=None):
    """Ask, then put a session away. Shared by the menu and the status window so the
    wording and the confirmation can't drift apart."""
    info = None
    try:
        for x in list_blocks():
            if x["id"] == sid:
                info = x
                break
    except Exception:
        pass
    try:
        from aqt.utils import askUser
        if not askUser(_finish_message(info), parent=parent or mw):
            return False
    except Exception:
        pass
    try:
        res = finish_block(sid)
        tooltip("Atlas: %d card(s) suspended again, %d kept in your reviews."
                % (res.get("resuspended", 0), res.get("kept", 0)), period=4000)
        return True
    except Exception as exc:
        tooltip("Atlas: couldn't finish that session (%s)" % exc, period=5000)
        return False


# --------------------------- menu bar entry ---------------------------
_menu = {"obj": None}


def install_menu():
    """A top-level 'Atlas' menu next to AnKing/AnkiHub, so the status window and any
    open sessions are one click away instead of buried in Tools > Add-ons > Config.
    Rebuilt on aboutToShow, so the session list is always current without polling."""
    from aqt.qt import QMenu, QAction

    if _menu["obj"] is not None:
        return
    menu = QMenu("Atlas", mw)
    try:
        mw.form.menubar.addMenu(menu)
    except Exception:
        return
    _menu["obj"] = menu

    def rebuild():
        menu.clear()
        status = QAction("Atlas status…", menu)
        status.triggered.connect(open_status_dialog)
        menu.addAction(status)

        resched = QAction("Block reps count as real reviews", menu)
        resched.setCheckable(True)
        resched.setChecked(_block_reschedule())
        resched.setToolTip("Off = preview only: you see the block's cards but nothing "
                           "in your scheduling changes.")
        resched.triggered.connect(lambda checked: _set_block_reschedule(checked))
        menu.addAction(resched)

        try:
            sessions = list_blocks()
        except Exception:
            sessions = []
        if sessions:
            menu.addSeparator()
            head = QAction("Open study sessions", menu)
            head.setEnabled(False)          # a label, not a command
            menu.addAction(head)
            for s in sessions:
                bits = []
                if s["questions"]:
                    bits.append("%d question%s" % (s["questions"], "" if s["questions"] == 1 else "s"))
                bits.append("%d to re-lock" % s["cards"])
                if s.get("deckGone"):
                    bits.append("deck already deleted")
                label = "Finish %s — %s" % (s["title"], ", ".join(bits))
                act = QAction(label, menu)
                act.triggered.connect(
                    lambda _checked=False, sid=s["id"]: _confirm_and_finish(sid, mw))
                menu.addAction(act)

        menu.addSeparator()
        guide = QAction("Setup guide", menu)
        guide.triggered.connect(lambda: _openlink(GUIDE_URL))
        menu.addAction(guide)
        kofi = QAction("Support Atlas on Ko-fi", menu)
        kofi.triggered.connect(lambda: _openlink(KOFI_URL))
        menu.addAction(kofi)

    menu.aboutToShow.connect(rebuild)
    rebuild()


# --------------------------- status window ---------------------------
def _connected():
    return (time.time() - _last_seen["t"]) < SEEN_WINDOW


def open_status_dialog():
    """Shown when the user clicks 'Config' on the add-on. No JSON, no port -
    just whether Anki and the browser extension are talking to each other."""
    from aqt.qt import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
                        QTimer, QScrollArea, QWidget, Qt)
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
    dlg.setMinimumWidth(560)   # wide enough for a session to fit on one line
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

    # ---- open block sessions, each with a way to put it back ----
    sessions_box = QVBoxLayout()
    sessions_box.setSpacing(6)
    root.addLayout(sessions_box)

    def _clear(lay):
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
            else:
                child = item.layout()
                if child is not None:
                    _clear(child)

    def on_finish(sid):
        _confirm_and_finish(sid, dlg)
        render_sessions()

    def on_finish_all():
        try:
            items = list_blocks()
        except Exception:
            items = []
        if not items:
            return
        total = sum(x["cards"] for x in items)
        try:
            from aqt.utils import askUser
            if not askUser(
                "Put all %d session(s) away?\n\nTheir temporary decks are removed and %d "
                "card(s) go back to suspended - except any you actually answered, which "
                "stay in your reviews." % (len(items), total), parent=dlg):
                return
        except Exception:
            pass
        done = locked = 0
        for x in items:
            try:
                res = finish_block(x["id"])
                done += 1
                locked += res.get("resuspended", 0)
            except Exception:
                pass
        tooltip("Atlas: %d session(s) put away, %d card(s) suspended again."
                % (done, locked), period=4000)
        render_sessions()

    def render_sessions():
        _clear(sessions_box)
        try:
            items = list_blocks()
        except Exception:
            items = []
        if not items:
            return

        # Header: count on the left, bulk action on the right.
        head_row = QHBoxLayout()
        head = QLabel("Open study sessions (%d)" % len(items))
        head.setStyleSheet("font-size:12px;font-weight:700;color:%s;" % text)
        head_row.addWidget(head)
        head_row.addStretch(1)
        if len(items) > 1:
            all_btn = QPushButton("Finish all")
            all_btn.setObjectName("ghost")
            all_btn.setStyleSheet("padding:3px 10px;font-size:11px;")
            all_btn.clicked.connect(on_finish_all)
            head_row.addWidget(all_btn)
        sessions_box.addLayout(head_row)

        # One compact line per session, in a scroll area so twenty sessions can't grow
        # the dialog past the screen - it used to be a tall card each, with a full-width
        # button, and six of them ran off the bottom.
        holder = QWidget()
        hl = QVBoxLayout(holder)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(4)
        for s in items:
            row = QFrame()
            row.setObjectName("card")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(10, 6, 8, 6)
            rl.setSpacing(8)

            title = QLabel(s["title"])
            title.setStyleSheet("font-size:12px;font-weight:600;color:%s;" % text)
            rl.addWidget(title)

            bits = []
            if s["questions"]:
                bits.append("%d q" % s["questions"])
            if s["gathered"]:
                bits.append("%d cards" % s["gathered"])
            bits.append("%d to re-lock" % s["cards"])
            if not s["reschedule"]:
                bits.append("preview")
            if s.get("deckGone"):
                bits.append("deck deleted")
            if s["created"]:
                try:
                    bits.append(time.strftime("%b %d %H:%M", time.localtime(int(s["created"]))))
                except Exception:
                    pass
            meta = QLabel(" · ".join(bits))
            meta.setStyleSheet("font-size:11px;color:%s;" % muted)
            rl.addWidget(meta)
            rl.addStretch(1)

            btn = QPushButton("Finish")
            btn.setObjectName("ghost")
            btn.setStyleSheet("padding:3px 12px;font-size:11px;")
            btn.clicked.connect(lambda _checked=False, sid=s["id"]: on_finish(sid))
            rl.addWidget(btn)
            hl.addWidget(row)
        hl.addStretch(1)

        area = QScrollArea()
        area.setWidget(holder)
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # ~4 rows before it starts scrolling instead of growing
        area.setMaximumHeight(min(4, len(items)) * 40 + 8)
        sessions_box.addWidget(area)
        try:
            dlg.adjustSize()
        except Exception:
            pass

    # Only rebuild when the set of sessions actually changes - re-creating the rows
    # every tick would steal clicks from the Finish buttons.
    seen = {"sig": None}

    def sync_sessions():
        try:
            sig = tuple(sorted(x["id"] or "" for x in list_blocks()))
        except Exception:
            sig = ()
        if sig != seen["sig"]:
            seen["sig"] = sig
            render_sessions()

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
    sync_sessions()

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
    timer.timeout.connect(sync_sessions)
    timer.start(2000)

    dlg.exec()


try:
    mw.addonManager.setConfigAction(__name__, open_status_dialog)
except Exception:
    pass


# Bind once the main window exists (fires on the main thread).
gui_hooks.main_window_did_init.append(start_server)
gui_hooks.main_window_did_init.append(install_menu)
