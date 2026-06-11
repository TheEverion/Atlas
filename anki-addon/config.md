# Atlas Bridge config

**port** — the local port the bridge listens on. Default `8765` (the same port
AnkiConnect uses), so the Atlas browser extension works with no changes. Only
change this if you also run AnkiConnect and want them on different ports (you'd
then point Atlas at the new port too).

**extraOrigins** — extra browser-extension/website origins allowed to talk to
the bridge. Atlas's own origin is already allowed, so you normally leave this
empty. Example: `["chrome-extension://abcdetc"]`.

Restart Anki after changing these.
