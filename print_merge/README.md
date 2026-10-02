# SSBM print merge (Canva + Word/Docs)

Standalone tooling for merging **Canva border/master PDFs** with **Letter text PDFs**
(Word / Google Docs) into printer-ready Letter PDFs. This folder is intentionally
separate from the archive search/extraction code in the repo root.

Agents: read this file before changing merge behaviour. Do not invent bleed/trim
boxes for Microsoft Print-to-PDF / Word exports — those files usually lack them.

## Layout

```
print_merge/
  merge_border_text.py     # main CLI
  measure_pdf_pages.py     # optional: measure page boxes / outer pads
  README.md                # this file
  templates/               # Canva masters (framed live area, typically 525×689.25 pt)
  content/                 # Letter text PDFs from Word/Docs
  output/                  # merged results (+ archive_measurements/)
```

## Dependencies

- Python 3.10+
- `pymupdf` (fitz)
- `numpy`

From repo root (or any venv that already has project deps):

```bash
pip install pymupdf numpy
```

## Design PDF conventions

| Pages | Order (0-based) | When to use |
|------:|-----------------|-------------|
| 2 | `[right, left]` | Body-only issues (no TOC design) |
| 3 | `[contents, right, left]` | First text page is a contents/TOC page |

- Masters are usually **framed live area** (~7.29×9.57 in), **not** full Letter.
- The script places the frame on Letter (default: horizontally centered, measured top pad).
- Odd magazine pages are **right-hand**; even are **left-hand**.

### `--contents` mapping

With `--contents` (requires 3-page design):

| Text page | Design |
|----------:|--------|
| 1 | contents (design p1) |
| 2 | left (design p3) |
| 3 | right (design p2) |
| 4 | left |
| 5 | right |
| … | left, right, … |

Without `--contents`:

| Text page | Design |
|----------:|--------|
| odd | right |
| even | left |

If the design PDF has 3 pages and `--contents` is **omitted**, page 1 (contents master) is skipped and only right/left are used.

## Text PDF expectations

- Letter **612×792 pt** (8.5×11 in).
- Wide margins so body text stays inside the Canva safe zone.
- Page numbers may sit in the footer (over the lotus); they must end up **on top** of the design.
- Word often adds opaque white rectangles under page numbers / headings — the script removes those.
- Soft-masked photos (circular portraits) are **left untouched** (knocking out “black backgrounds” was wrongly inverting dark hair).

## Merge behaviour (default)

1. Optional text cleanup (white fills removed; plate images → transparent).
2. Draw Canva design into the framed rect on a blank Letter page.
3. Overlay cleaned text PDF (`show_pdf_page`, preserves Word transparency).

Legacy `--borders-on-top` stamps decorations over text instead (usually wrong when footers must show).

## CLI

```bash
# From repo root — with contents page
python print_merge/merge_border_text.py \
  "print_merge/templates/sample template canva contents, right and left 6.pdf" \
  "print_merge/content/SSBM Printer Sample text 7.pdf" \
  -o "print_merge/output/SSBM_merged_sample_text7.pdf" \
  --contents

# Body only (skip contents master even if present in a 3-page design)
python print_merge/merge_border_text.py \
  "print_merge/templates/sample template canva contents, right and left 6.pdf" \
  "print_merge/content/SSBM Printer Sample text 7.pdf" \
  -o "print_merge/output/SSBM_merged_no_contents.pdf"

# Classic 2-page design [right, left]
python print_merge/merge_border_text.py \
  "print_merge/templates/sample template canva right and left 5.pdf" \
  "print_merge/content/SSBM Printer Sample text 6.pdf" \
  -o "print_merge/output/SSBM_merged_sample_text6.pdf"
```

### Useful flags

| Flag | Meaning |
|------|---------|
| `--contents` | Text p1 → contents design; then left, right, left… |
| `-o PATH` | Output PDF (required) |
| `--pages 1-4` | Only merge a subset (1-based) |
| `--white-thresh 248` | Plate knockout threshold for non-masked images |
| `--facing-pads` | Odd/even X pads from print proof (can misalign centered page numbers) |
| `--borders-on-top` | Legacy stamp mode |

## Placement constants

Defined in `merge_border_text.py`:

- Output: Letter `612×792`
- Default top pad: `55.44` pt (from June 2026 proof)
- Default X: `(612 - frame_width) / 2` so footer art aligns with centered page numbers

If a new Canva export changes frame size, re-check placement (or run `measure_pdf_pages.py` on a printed proof).

## Measuring proofs

```bash
python print_merge/measure_pdf_pages.py "path/to/proof.pdf" --json print_merge/output/proof.json
```

Reports Media/Trim/Bleed boxes when present; otherwise infers outer pad / live area from ink.

## Common failure modes (for agents)

1. **Inverted / white hair on circular photos** — do not apply black-bg knockout to soft-masked images.
2. **Stippled / weird halo around Word banners with drop shadows** — Word bakes soft shadows into JPEGs on white. Do **not** force those through white→alpha knockout (binary or soft); leave the JPEG intact. Knockout of that fringe looks OK in MuPDF/Cursor but speckled/blocked in Adobe/Chrome/Edge.
3. **Lotus covered by page numbers** — ensure design-behind mode; remove Word white fill under page numbers.
4. **Alternating page-number vs lotus offset** — avoid `--facing-pads` unless intentionally matching bindery pads; prefer center-X.
5. **Wrong left/right** — confirm design PDF page order is `[contents?, right, left]` as documented; do not assume filename alone if the artist reorders pages.
6. **Canva center is opaque white** — stacking design *on top* of text hides body copy; default order is design then text.

## Related NGO workflow notes

- Grayscale / B&W flexible printer; formal PDF/X and commercial bleed are not required for this pipeline.
- Editorial text lives in Word/Docs; static borders live in Canva; Python only merges.
