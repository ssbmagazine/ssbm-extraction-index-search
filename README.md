# SSBM extraction, index & search

Digitize *Sri Sathya Sai Balavikas* (SSBM) Telugu magazine PDFs into **article-level** archives, index them in SQLite, and search by **catalog** (titles / authors / series) or **full text**.

Many scripts live in the repo root today (layout cleanup can come later). This document is the map: what each piece does, how to set up, how to process issues, and how the UIs fit in.

> **`print_merge/` is unrelated to archive search.** It merges a Canva design/border PDF with a Letter text PDF for print publication. See [print_merge/README.md](print_merge/README.md). Skip that folder unless you are doing print production.

---

## Mental model

```
PDF (PageMaker / Priyaanka–Anu glyph fonts)
        │
        ▼
  extract_ssbm  ──►  decoded page blocks + images
        │                 (anu_decoder + telugu_normalize)
        ▼
  article_builder ──►  archive/<edition_id>/
        │                 edition.json, articles/*.json|md,
        │                 catalog.json, raw_extract.json, images/
        │            (+ catalog_builder, toc_parser, author_tagger)
        ▼
  verify_ocr (optional) ──► qa / verify diffs vs Tesseract
        │
        ▼
  index_ssbm ──►  ssbm_archive.db
        │            editions, articles, catalog_entries
        │            FTS: catalog (P1) + body trigram (P2)
        ▼
  search_ssbm (CLI)  or  search_ui (browser)
  review_ui (fix doubtful extracts)
```

**One-shot path:** `process_archive.py` runs extract → segment/catalog → optional OCR verify → index for every PDF you point it at.

**Edition IDs**

| PDF layout | Example | `edition_id` |
|------------|---------|--------------|
| Legacy flat name | `jan2002.pdf` | `jan2002` |
| Corpus tree | `issues/2026/01.pdf` | `2026-01` |

Outputs land under `archive/<edition_id>/` (gitignored). The SQLite DB defaults to `ssbm_archive.db` in the repo root (also gitignored).

---

## Dual search (why two modes)

| Mode | What it searches | Engine | Good for |
|------|------------------|--------|----------|
| **P1 Catalog** (default) | Headings, authors, series labels | FTS5 `unicode61` on `catalog_entries` | “Find the article titled …” / series / byline |
| **P2 Full text** | Article body | FTS5 **trigram** on body | Words inside the story; better when spaces are missing |

**Scope** (year / decade) filters on `editions.publish_year` — no extra schema. UI values like `2000s` → 2000–2009, `2026` → that year only.

**Known quality caveat:** early-2000s Priyaanka/Anu PDFs decode reasonably. Many **2026** issues use extra fonts (`Kranthi`, `Deepika`, `Jyothi`, …) with high unmapped-glyph rates, so catalog/body text can be garbled and **normal Telugu queries will not hit that content** until decoder coverage improves (or OCR is used as primary text for that era).

---

## Setup

### Requirements

- Python **3.10+** (3.11 used in development)
- [Tesseract](https://github.com/tesseract-ocr/tesseract) with **Telugu + English** data — only needed if you run OCR verify (not required for extract/index/search alone)

### Install

```bash
cd ssbm-extraction-index-search
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
```

`requirements.txt` currently lists: `pymupdf`, `flask`, `pytesseract`, `Pillow`.

For OCR verify on Windows, install Tesseract and either put `tel.traineddata` / `eng.traineddata` where Tesseract expects them, or use a local `tessdata/` directory (the verify path can honor `TESSDATA_PREFIX`).

### Optional sibling corpus

`process_archive.py` defaults `--pdf-dir` to:

`../ssbmagazine/public/issues`

if that folder exists (year folders with `MM.pdf`). Otherwise pass `--pdf-dir` explicitly.

---

## How to process magazines

### Recommended: batch via `process_archive.py`

```bash
# All PDFs under a directory (flat *.pdf or YYYY/MM.pdf)
python process_archive.py --pdf-dir "C:\path\to\issues" --out archive -d ssbm_archive.db

# Only one year
python process_archive.py --pdf-dir "C:\path\to\issues" --year 2002 --out archive -d ssbm_archive.db

# Specific files
python process_archive.py --pdf jan2002.pdf --pdf feb2002.pdf --out archive -d ssbm_archive.db

# Faster ingest (skip Tesseract)
python process_archive.py --pdf-dir "...\issues" --year 2026 --no-verify --force -d ssbm_archive.db

# Re-run OCR verify only on an existing archive folder
python process_archive.py --verify-only archive/2026-01
```

Useful flags:

| Flag | Meaning |
|------|---------|
| `--force` | Re-extract even if `edition.json` already exists |
| `--no-verify` | Skip OCR QA pass |
| `--year YYYY` | Filter discovered PDFs to that calendar year |
| `-d` / `--database` | SQLite path |
| `--out` | Archive root (default `archive`) |

After a batch, check `archive/batch_summary.json` and each edition’s `qa_report.json`.

### Step-by-step (same pipeline, manual)

Use this when debugging one stage:

```bash
# 1) Glyph decode + page structure
python extract_ssbm.py path\to\issue.pdf -o raw.json

# 2) TOC → articles + catalog (normally done inside process_archive
#    via article_builder.export_edition_archive — no separate CLI)

# 3) Index an archive edition folder into SQLite
python index_ssbm.py archive/jan2002 -d ssbm_archive.db

# 4) Optional OCR verify
python verify_ocr.py archive/jan2002
```

---

## Search

### CLI — `search_ssbm.py`

```bash
# Catalog (P1) — default
python search_ssbm.py "స్వామి" -d ssbm_archive.db

# Full text (P2)
python search_ssbm.py "స్వామి" --mode fulltext -d ssbm_archive.db

# Exact word (stricter)
python search_ssbm.py "ప్రేమ" --exact

# Catalog kind filter
python search_ssbm.py "గురు" --kind heading
```

Year scope exists on the DB API / HTML UI; the CLI focuses on mode, kind, and exact match (extend later if needed).

### Browser UI — `search_ui.py`

Dev Flask app over the same DB:

```bash
python search_ui.py -d ssbm_archive.db --port 5056
```

Open **http://127.0.0.1:5056/**

- Tabs: **Catalog (P1)** vs **Full text (P2)**
- **Scope:** all years, decades (`2000s`, `2020s`), or a single year
- **Catalog kind:** heading / author / series
- **Exact word** checkbox

This is a **local research UI**, not a production website.

### Review UI — `review_ui.py`

Separate Flask app for articles flagged for review (side-by-side page image vs extract):

```bash
python review_ui.py -d ssbm_archive.db --archive archive --port 5055
```

Open **http://127.0.0.1:5055/** — use when QA flags / review queues need human correction. Independent of `search_ui.py`.

---

## Root scripts (who does what)

| File | Role |
|------|------|
| **`process_archive.py`** | **Main entry** — batch PDF → archive → DB |
| **`extract_ssbm.py`** | PDF text/layout extract; calls decoder |
| **`anu_decoder.py`** | Anu/Priyaanka-style glyph → Unicode Telugu |
| **`priyaanka_decoder.py`** | Older/alternate Priyaanka mapping (legacy; extract path centers on Anu) |
| **`telugu_normalize.py`** | Post-decode cleanup (matras, spaces, composition) |
| **`toc_parser.py`** | Table-of-contents → article spine |
| **`article_builder.py`** | Build articles + front matter; write `archive/<id>/` |
| **`catalog_builder.py`** | P1 catalog rows (heading / author / series) |
| **`author_tagger.py`** | Heuristic author detection on layout |
| **`series_catalog.json`** / **`series_aliases.json`** | Extensible series name lists |
| **`qa_metrics.py`** | Latin-leftover / split-matra style QA signals |
| **`verify_ocr.py`** | Tesseract tel+eng verify against extract (QA only) |
| **`index_ssbm.py`** | Load archive edition into SQLite + FTS |
| **`db_manager.py`** | Schema, FTS, search helpers (`SSBMDatabase`) |
| **`search_ssbm.py`** | CLI search |
| **`search_ui.py`** | Browser search (P1/P2 + scope) |
| **`review_ui.py`** | Browser review queue |
| **`golden/test_golden.py`** | Regression checks for known decode/search bugs |

Supporting / generated (usually **not** in git):

| Path | Role |
|------|------|
| `archive/` | Per-edition JSON/MD/images/QA |
| `ssbm_archive.db` | Search index |
| `extracted_jsons/`, `extracted_txts/` | Older ad-hoc extract dumps |
| `tessdata/` | Local OCR language data |
| `*.pdf` | Source issues (keep outside git) |

---

## Archive folder shape

After a successful process:

```
archive/2026-01/
  edition.json          # id, title, year/month, pdf_path, flags
  raw_extract.json      # full page/block extract + detected fonts
  catalog.json          # P1 entries
  qa_report.json        # extract QA (+ verify if run)
  articles/
    00_front_matter.json|.md
    01_<title>.json|.md
    ...
  images/
    p001_img002.png
    ...
```

---

## Typical workflows

**A. Ingest a few known-good early issues, then search**

```bash
pip install -r requirements.txt
python process_archive.py --pdf-dir ".\issues_sample" --year 2002 --no-verify -d ssbm_archive.db
python search_ui.py -d ssbm_archive.db --port 5056
```

**B. Re-index after fixing decoder (no need to keep old DB)**

```bash
# delete or rename ssbm_archive.db if you want a clean index
python process_archive.py --pdf-dir "...\issues" --year 2002 --force --no-verify -d ssbm_archive.db
```

**C. Print production (separate)**

```bash
pip install pymupdf numpy
python print_merge/merge_border_text.py design.pdf text.pdf -o out.pdf
```

Details, facing pads, and contents-page layouts: [print_merge/README.md](print_merge/README.md).

---

## Tests

```bash
python golden/test_golden.py
```

Expects fixtures / behavior documented in that file; some checks assume prior extracts or decoder behavior.

---

## What we are not doing yet

- Rewiring root scripts into `src/` packages (planned later)
- Production deployment of the Flask UIs
- Full font coverage for all modern SSBM PDF fonts (2026 decode gaps)

When in doubt: start from **`process_archive.py`** for ingest and **`search_ui.py`** for exploration; treat everything else as a stage you only call when debugging that stage.
