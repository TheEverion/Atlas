<p align="center">
  <img src="assets/buttons.png" alt="Atlas buttons on UWorld results page" width="900">
</p>

<div align="center">

# Atlas

### Stop digging through AnKing tags like a raccoon in a dumpster.

**Atlas connects your UWorld results to AnKing cards, resource tags, videos, and images — directly from your browser.**

<a href="https://ko-fi.com/atlasanki">
  <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Support Atlas on Ko-fi">
</a>

<br><br>

<img alt="Version" src="https://img.shields.io/badge/version-1.7-blue?style=for-the-badge">
<img alt="Anki" src="https://img.shields.io/badge/Anki-Bridge-2b90d9?style=for-the-badge">
<img alt="Chrome Extension" src="https://img.shields.io/badge/Chrome_Extension-Atlas-34a853?style=for-the-badge&logo=googlechrome&logoColor=white">
<img alt="JavaScript" src="https://img.shields.io/badge/JavaScript-76%25-f7df1e?style=for-the-badge&logo=javascript&logoColor=black">
<img alt="Python" src="https://img.shields.io/badge/Python-19%25-3776ab?style=for-the-badge&logo=python&logoColor=white">

<br>

**For students who live inside UWorld, Anki, and 47 browser tabs.**

</div>

---

## Why Atlas exists

UWorld tells you what you missed.

AnKing probably has the cards you need.

But finding those cards, checking resource tags, opening videos, and deciding what to unsuspend can turn into a tiny side quest.

**Atlas removes the side quest.**

It adds buttons to the UWorld results page so you can instantly open matching AnKing cards, review related resources, view images, and optionally unsuspend cards with one click.

---

## What Atlas does

| Button / Feature | What it helps you do |
|---|---|
| **Missed** | Open AnKing cards linked to the questions you got wrong. |
| **All** | Open matching cards for the whole block. |
| **Marked** | Focus only on questions you flagged. |
| **Resources Panel** | See related tags from B&B, Pathoma, Sketchy, Bootcamp, Physeo, First Aid, and more. |
| **Image Overlay** | Open First Aid / Sketchy images without leaving the question page. |
| **Watch Links** | Jump to matching resource videos when available. |
| **Easy Mode** | Auto-unsuspend matched cards after confirmation. |
| **Expected Score Beta** | Estimate performance from card maturity. |
| **Dark Mode** | Save your eyes during the 1 a.m. “just one more block” lie. |

---

## Preview

### UWorld buttons

<p align="center">
  <img src="assets/buttons.png" alt="Atlas buttons on UWorld results page" width="900">
</p>

---

### Resource panel

See which resources cover the topic, grouped by source.

<p align="center">
  <img src="assets/resources-panel.png" alt="Atlas resources panel" width="900">
</p>

---

### Image overlay

Press **F** for First Aid or **S** for Sketchy.

<p align="center">
  <img src="assets/image-demo.gif" alt="Atlas image overlay demo" width="900">
</p>

---

### Watch links

Open the matching resource video for the subtopic.

<p align="center">
  <img src="assets/watch-demo.gif" alt="Atlas watch links demo" width="900">
</p>

---

### Dark mode

Because your retina deserves mercy.

<p align="center">
  <img src="assets/dark-mode.gif" alt="Atlas dark mode demo" width="900">
</p>

---

## Easy Mode

Easy Mode is for when you do **not** want to manually open Anki Browser, select cards, right-click, and unsuspend.

When Easy Mode is on, Atlas checks the matched cards and asks before unlocking them into your review queue.

<p align="center">
  <img src="assets/easy-mode-toggle.png" alt="Atlas Easy Mode toggle" width="420">
</p>

<p align="center">
  <img src="assets/easy-mode-confirm.png" alt="Atlas Easy Mode confirmation dialog" width="520">
</p>

Easy Mode is **off by default**.

With Easy Mode off, Atlas keeps the normal behavior and opens matching cards in Anki.

---

## How it works

Atlas has two parts:

| Part | Folder | What it does |
|---|---|---|
| **Atlas Bridge** | `anki-addon/` | Local Anki add-on that lets the browser extension talk to Anki. |
| **Atlas Extension** | `chrome-extension/` | Browser extension that adds Atlas buttons and panels to UWorld. |

Both are required.

The extension is the interface.  
The Anki add-on is the bridge.

Atlas talks to Anki locally through:

```txt
127.0.0.1:8765
```

---

## Installation

You need to install both pieces.

### 1. Install Atlas Bridge in Anki

1. Open Anki.
2. Go to:

```txt
Tools → Add-ons → View Files
```

3. Create a new folder named:

```txt
atlas_bridge
```

4. Copy everything from:

```txt
anki-addon/
```

into that folder.

You should copy files like:

```txt
__init__.py
config.json
config.md
manifest.json
```

5. Restart Anki.

Atlas Bridge should start automatically.

---

### 2. Install the browser extension

1. Open your browser extension page:

```txt
chrome://extensions
```

or, if you use Brave:

```txt
brave://extensions
```

2. Turn on **Developer mode**.
3. Click **Load unpacked**.
4. Select the repo folder:

```txt
chrome-extension/
```

5. Pin Atlas to your toolbar.

---

## Usage

1. Open Anki.
2. Open UWorld.
3. Review a block.
4. Use the Atlas buttons on the UWorld results page.
5. Choose what you want to do:
   - open missed cards,
   - open all related cards,
   - open marked cards,
   - view resources,
   - view images,
   - or use Easy Mode.

<p align="center">
  <img src="assets/popup.png" alt="Atlas popup" width="420">
</p>

<p align="center">
  <img src="assets/exam-dropdown.png" alt="Atlas exam dropdown" width="420">
</p>

---

## Supported exam modes

Atlas can switch between:

| Exam mode | Use case |
|---|---|
| **Step 1 / COMLEX 1** | Preclinical cards and resources. |
| **Step 2 / COMLEX 2** | Clinical shelf / Step 2 style studying. |
| **Step 3** | Step 3 mode. |

Change the exam from the popup.

No page refresh needed.

---

## Configuration

Atlas Bridge settings live in:

```txt
config.json
```

You can edit them from Anki:

```txt
Tools → Add-ons → Atlas Bridge → Config
```

Main settings:

| Setting | Default | What it does |
|---|---:|---|
| `port` | `8765` | Local port used by Atlas Bridge. |
| `extraOrigins` | `[]` | Extra allowed extension or website origins. Usually leave empty. |

Restart Anki after changing settings.

---

## Important note about AnkiConnect

Atlas Bridge uses the same default port as AnkiConnect:

```txt
8765
```

Only one app can use that port at a time.

If you already use AnkiConnect, you can either:

- disable AnkiConnect while using Atlas, or
- change Atlas Bridge to another port and update the extension to match.

Atlas Bridge only exposes the actions Atlas needs.

---

## Project structure

```txt
Atlas/
├── anki-addon/          # Atlas Bridge for Anki
├── chrome-extension/    # Browser extension
├── assets/              # README screenshots and GIFs
├── PRIVACY.md           # Privacy policy
└── README.md
```

---

## Privacy

Atlas is designed to run locally between your browser and Anki.

It communicates through:

```txt
127.0.0.1:8765
```

Read the full privacy policy here:

[PRIVACY.md](PRIVACY.md)

---

## Support Atlas

Atlas is made for students trying to survive UWorld, Anki, and the eternal battle against suspended cards.

If Atlas saves you clicks, confusion, or one tiny academic breakdown, you can support it here:

<p align="center">
  <a href="https://ko-fi.com/atlasanki">
    <img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Support Atlas on Ko-fi">
  </a>
</p>

---

## Changelog

### v1.7

- Added **Easy Mode**.
- Added one-click auto-unsuspend after confirmation.
- Shows card count before unlocking cards.
- Keeps normal open-in-Anki behavior when Easy Mode is off.

### v1.6

- Added grouped resource panel.
- Added First Aid and Sketchy image overlays.
- Added video watch links.
- Added dark mode.
- Added Expected Score Beta.

---

## Disclaimer

Atlas is an independent study tool.

It is not affiliated with UWorld, AnKing, Anki, Sketchy, Boards & Beyond, Bootcamp, Pathoma, Physeo, First Aid, or any other third-party resource.

Use it as a study helper, not as an excuse to do 900 cards at 2 a.m.
