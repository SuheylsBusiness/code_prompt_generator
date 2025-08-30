# Code Prompt Generator

<p align="center">
  <!-- Replace the path below with the real screenshot once available -->
  <img src="https://backend.suheylsbusiness.com/files/view/681b65fcecafa1d39737fc2d" alt="Code Prompt Generator GUI" width="800"/>
</p>

> **Turn your codebase into a concise, share‑ready prompt in seconds.**
> Code Prompt Generator lets you visually pick project files and instantly produce a structured markdown prompt for ChatGPT / LLMs, code reviews, or documentation.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE) 
[![Python >= 3.9](https://img.shields.io/badge/python-%3E%3D3.9-blue)](https://www.python.org/)

---

## 🚀 Quick Tour (Loom Video)

> A 2‑minute Loom walkthrough that covers the main workflow will appear here.

<div>
    <a href="https://www.loom.com/share/3a175e57b4004c96aed2e33817e39adb">
      <p>Git Repository Usage Guide - Watch Video</p>
    </a>
    <a href="https://www.loom.com/share/3a175e57b4004c96aed2e33817e39adb">
      <img style="max-width:300px;" src="https://cdn.loom.com/sessions/thumbnails/3a175e57b4004c96aed2e33817e39adb-a51514ad303f5246-full-play.gif">
    </a>
  </div>

---

## Table of Contents

1. [Features](#features)
2. [Why Use It ? (Benefits)](#why-use-it--benefits)
3. [Getting Started](#getting-started)
4. [Configuration](#configuration)
5. [Usage Guide](#usage-guide)
6. [Project Structure](#project-structure)
7. [Contributing](#contributing)
8. [Roadmap](#roadmap)
9. [License](#license)
10. [Author & Contact](#author--contact)

---

## Features

* **Modern Tkinter GUI** – intuitive project/file selector with live search, coloured heat‑map highlighting and keyboard shortcuts.
* **Smart Limits** – honours `.gitignore`, auto‑blacklists huge directories, skips oversized files, and enforces project limits from `config.ini`.
* **One‑Click Prompt Generation** – outputs ready‑to‑paste markdown containing directory tree, selected file list and content blocks.
* **Caching** – hashes files and skips re‑processing unchanged selections for instant regeneration.
* **Cross‑Platform** – Windows, macOS, Linux (Python ≥ 3.9).

## Why Use It ? (Benefits)

* **Save time:** avoid manual copy‑paste of dozens of source files.
* **Stay within LLM context limits:** configurable caps prevent oversize prompts.
* **Reproducible outputs:** deterministic cache keys guarantee identical prompts for identical inputs.
* **Team‑friendly:** share prompts, selection histories and outputs via Git or chat.
* **Extensible:** tweak the default markdown template or add your own in‑app.

---

## Getting Started

### Prerequisites

```bash
python --version   # >= 3.9 recommended
```

### Installation

```bash
# 1 — Clone the repository
 git clone https://github.com/SuheylsBusiness/code_prompt_generator
 cd code_prompt_generator

# 2 — Create & activate a virtual environment (optional but recommended)
 python -m venv .venv
 source .venv/bin/activate            # On Windows: .venv\Scripts\activate

# 3 — Install Python dependencies
 pip install -r requirements.txt

# 4 — Run the application
 python main.pyw
```

The GUI should open within a few seconds. 🎉

---

## Configuration

All runtime limits live in **`config.ini`** and are loaded on start‑up.
Default values are suitable for most projects, so you *don’t need to touch anything* at first.

```ini
[Limits]
CACHE_EXPIRY_SECONDS = 3600   ; 1 hour
MAX_FILES            = 500    ; max files per project
MAX_CONTENT_SIZE     = 2000000; max total characters in prompt
MAX_FILE_SIZE        = 500000 ; max characters per single file
```

If your workflow demands different thresholds, edit `config.ini` and restart the app.

---

## Usage Guide

1. **Add a project** – Click **Add Project**, pick your repository root.
2. **Select files** – Use the check boxes (or search & *Select All*) to pick source files you want in the prompt.
3. **Choose a template** – Built‑in default or create your own in **Manage Templates**.
4. **Generate** – Press **Generate**. Your prompt is saved to `data/outputs/<project>_<timestamp>.md` and opened in your default editor.
5. *(Optional)* revisit history, view past outputs or tweak settings (.gitignore respect, blacklist, keep‑rules, prefix, etc.).

> **Tip:** double‑click any output in **View Outputs** to inspect it inside the built‑in text editor.

---

## Project Structure

```
code_prompt_generator/
├── config.ini           # Runtime limits (defaults above)
├── main.pyw             # Tkinter application entry‑point
├── requirements.txt     # Python dependencies
└── data/                # Generated at runtime (cache, outputs, logs)
```

---

## Roadmap

* [ ] 🌐 Publish PyPI package (`pip install code‑prompt‑generator`).
* [ ] 🎥 Embed interactive Loom video.
* [ ] 🔌 Plugin system for custom exporters (JSON, HTML, SVG).
* [ ] 📝 In‑app markdown preview.

Feel free to open an issue to suggest a feature or vote for an item above.

---

## License

Distributed under the **MIT License**. See [`LICENSE`](LICENSE) for more information.

---

## Author & Contact

**Suheyl Ünüvar**
[suheyl@suheylsbusiness.com](mailto:suheyl@suheylsbusiness.com)

---

<p align="center"><i>Made with ❤️  using Python & Tkinter</i></p>
