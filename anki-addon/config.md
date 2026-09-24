# Atlas Bridge

You don't need to configure anything here. Use the **Atlas** menu in Anki's menu
bar — it has the status window and any open block sessions.

- `blockReschedule` — whether an Atlas block session counts as real reviews
  (`true`) or is preview only, changing no scheduling (`false`). Toggle it from
  the **Atlas** menu rather than editing this.
- `port` — this add-on listens on local port **8766** (deliberately not
  AnkiConnect's 8765, so both can run at once). Only change it if 8766 is already
  taken on your machine — and then point the Atlas extension at the same port.

Restart Anki after any change here.
