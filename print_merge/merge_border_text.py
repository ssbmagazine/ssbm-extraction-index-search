#!/usr/bin/env python3
"""
Merge Canva border/master PDFs with Word/Google-Docs Letter text PDFs for SSBM print.

Default mode: design BEHIND, cleaned text (page numbers, body) ON TOP.

Design PDF layouts supported:
  2 pages: [right, left]   — odd text pages use right, even use left
  3 pages: [contents, right, left] — with --contents, text page 1 uses contents,
            then left, right, left, right... for subsequent pages

See README.md in this folder for full agent-oriented docs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import fitz
import numpy as np

# Letter output
PAGE_W, PAGE_H = 612.0, 792.0

# Facing-page outer pads from June 2026 proof (optional via --facing-pads).
ODD_PAD = (40.68, 55.44)  # left, top
EVEN_PAD = (46.08, 55.08)


def is_near_white_fill(fill, tol: float = 0.02) -> bool:
    if not fill or len(fill) < 3:
        return False
    return all(abs(float(c) - 1.0) <= tol for c in fill[:3])


def knock_out_background(page: fitz.Page, dpi: float, white_thresh: int) -> fitz.Pixmap:
    """Rasterize a page; keep existing transparency; knock out near-white."""
    mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    pix = page.get_pixmap(matrix=mat, alpha=True)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n).copy()
    rgb = arr[:, :, :3]
    orig_a = arr[:, :, 3]
    near_white = (
        (rgb[:, :, 0] >= white_thresh)
        & (rgb[:, :, 1] >= white_thresh)
        & (rgb[:, :, 2] >= white_thresh)
    )
    arr[:, :, 3] = np.where((orig_a == 0) | near_white, 0, np.maximum(orig_a, 255)).astype(
        np.uint8
    )
    return fitz.Pixmap(fitz.csRGB, pix.w, pix.h, arr.tobytes(), True)


def soft_knockout_alpha(
    rgb: np.ndarray,
    *,
    mode: str,
    white_clear: int = 252,
    white_opaque: int = 200,
    black_clear: int = 12,
    black_opaque: int = 55,
) -> np.ndarray:
    """
    Build a soft (graduated) alpha mask so JPEG drop-shadows stay smooth.

    Binary 0/255 knockout turns soft gray shadow fringes into stippled halos that
    look fine in MuPDF/Cursor but weird in Adobe/Chrome/Edge/etc.
    """
    if mode == "black-bg":
        level = rgb.max(axis=2).astype(np.float32)
        clear, opaque = float(black_clear), float(black_opaque)
        alpha = np.clip((level - clear) / max(opaque - clear, 1.0) * 255.0, 0, 255)
    else:
        level = rgb.min(axis=2).astype(np.float32)
        clear, opaque = float(white_clear), float(white_opaque)
        alpha = np.clip((clear - level) / max(clear - opaque, 1.0) * 255.0, 0, 255)
    return alpha.astype(np.uint8)


def pixmap_knockout_background(
    doc: fitz.Document,
    xref: int,
    white_thresh: int = 248,
    black_thresh: int = 40,
) -> fitz.Pixmap | None:
    """
    Rebuild an image as RGB+alpha for plate removal.

    Returns None (keep original) when the image already has a soft-mask
    (circular photos) — black-bg heuristics wrongly punch out dark hair/robes.

    Uses graduated alpha (not binary) so Word drop shadows stay smooth across
    PDF viewers.
    """
    try:
        info = doc.extract_image(xref)
    except Exception:
        return None
    if info.get("smask"):
        return None

    try:
        base = fitz.Pixmap(doc, xref)
    except Exception:
        return None
    if base.colorspace is None:
        return None

    if base.n - base.alpha != 3:
        try:
            base = fitz.Pixmap(fitz.csRGB, base)
        except Exception:
            return None
    if base.alpha:
        base = fitz.Pixmap(base, 0)

    rgb = np.frombuffer(base.samples, dtype=np.uint8).reshape(base.h, base.w, 3).copy()
    edge = np.concatenate([rgb[0, :, :], rgb[-1, :, :], rgb[:, 0, :], rgb[:, -1, :]], axis=0)
    edge_mean = float(edge.mean())

    if edge_mean < 80:
        alpha = soft_knockout_alpha(rgb, mode="black-bg")
    else:
        # Word title banners often bake a soft drop-shadow into a JPEG on white.
        # Converting that fringe to alpha (even soft) composites badly in Adobe/
        # Chrome/Edge while MuPDF/Cursor still looks OK. Leave those JPEGs alone.
        soft_fringe = float(((rgb >= 200) & (rgb < max(white_thresh, 248))).all(axis=2).mean())
        near_white = float((rgb >= max(white_thresh, 248)).all(axis=2).mean())
        if soft_fringe > 0.04 and near_white < 0.55:
            return None

        clear = max(int(white_thresh), 250)
        opaque = min(int(white_thresh) - 48, 210)
        alpha = soft_knockout_alpha(
            rgb, mode="white-bg", white_clear=clear, white_opaque=opaque
        )

    if float((alpha < 8).mean()) < 0.01:
        return None

    rgba = np.dstack([rgb, alpha])
    return fitz.Pixmap(fitz.csRGB, base.w, base.h, rgba.tobytes(), True)


def prepare_text_pdf(text_pdf: Path, white_thresh: int) -> fitz.Document:
    """Copy text PDF; remove white fill rects; rebuild plate images as transparent."""
    src = fitz.open(text_pdf)
    doc = fitz.open()
    doc.insert_pdf(src)
    src.close()

    removed_fills = 0
    for page in doc:
        for d in page.get_drawings():
            r = d.get("rect")
            fill = d.get("fill")
            if r is None or not is_near_white_fill(fill):
                continue
            if r.width >= 15 and r.height >= 8:
                page.add_redact_annot(r)
                removed_fills += 1
        page.apply_redactions(images=0, graphics=2, text=1)
    print(f"  Cleaned text PDF: removed {removed_fills} white fill rects")

    seen: set[int] = set()
    replaced = 0
    skipped_masked = 0
    for page in doc:
        for im in page.get_image_info(xrefs=True):
            xref = im.get("xref")
            if not xref or xref in seen:
                continue
            seen.add(xref)
            try:
                info = doc.extract_image(xref)
                if info.get("smask"):
                    skipped_masked += 1
                    continue
            except Exception:
                pass
            new_pix = pixmap_knockout_background(doc, xref, white_thresh=white_thresh)
            if new_pix is None:
                continue
            try:
                page.replace_image(xref, pixmap=new_pix)
                replaced += 1
            except Exception as e:
                print(f"  WARNING: could not replace image xref={xref}: {e}")
    print(
        f"  Cleaned text PDF: rebuilt {replaced} images with bg->transparent "
        f"(left {skipped_masked} soft-masked photos untouched)"
    )
    return doc


def resolve_design_indices(n_pages: int, use_contents: bool) -> dict[str, int | None]:
    """
    Map logical roles to 0-based design page indices.

    Expected 3-page order (filename convention): [contents, right, left]
    Expected 2-page order: [right, left]
    """
    if use_contents:
        if n_pages < 3:
            raise SystemExit(
                f"--contents requires a 3-page design PDF [contents, right, left]; got {n_pages}"
            )
        return {"contents": 0, "right": 1, "left": 2}

    if n_pages >= 3:
        # Skip the contents master; use right/left only.
        return {"contents": None, "right": 1, "left": 2}
    if n_pages == 2:
        return {"contents": None, "right": 0, "left": 1}
    if n_pages == 1:
        return {"contents": None, "right": 0, "left": 0}
    raise SystemExit("Design PDF has no pages.")


def design_page_index(
    page_1based: int,
    indices: dict[str, int | None],
    use_contents: bool,
) -> int:
    """
    Choose which design page stamps behind this text page.

    With --contents:
      text p1 -> contents
      then left, right, left, right...  (p2 left, p3 right, ...)
    Without:
      odd -> right, even -> left  (classic facing pages)
    """
    if use_contents and page_1based == 1:
        assert indices["contents"] is not None
        return indices["contents"]

    # Magazine body: odd pages are right-hand, even are left-hand.
    # With contents as p1, body starts at p2 (even) => left first — matches request.
    if page_1based % 2 == 1:
        return int(indices["right"])
    return int(indices["left"])


def design_label(bi: int, indices: dict[str, int | None]) -> str:
    if indices.get("contents") is not None and bi == indices["contents"]:
        return "contents"
    if bi == indices["right"]:
        return "right-border"
    if bi == indices["left"]:
        return "left-border"
    return f"design-p{bi + 1}"


def placement_for_page(
    page_1based: int,
    border_w: float,
    border_h: float,
    facing_pads: bool,
) -> fitz.Rect:
    """Place framed Canva art on Letter (default: center-X, measured top)."""
    if facing_pads:
        left, top = ODD_PAD if page_1based % 2 == 1 else EVEN_PAD
    else:
        left = (PAGE_W - border_w) / 2.0
        top = ODD_PAD[1]
    left = min(max(0.0, left), max(0.0, PAGE_W - border_w))
    top = min(max(0.0, top), max(0.0, PAGE_H - border_h))
    return fitz.Rect(left, top, left + border_w, top + border_h)


def merge(
    border_pdf: Path,
    text_pdf: Path,
    out_pdf: Path,
    dpi: float = 200.0,
    white_thresh: int = 248,
    page_indices: list[int] | None = None,
    design_behind: bool = True,
    facing_pads: bool = False,
    use_contents: bool = False,
) -> dict[str, Any]:
    borders = fitz.open(border_pdf)
    out = fitz.open()

    indices = resolve_design_indices(borders.page_count, use_contents=use_contents)
    bw = borders[0].rect.width
    bh = borders[0].rect.height

    print(
        f"  Canva frame: {bw:.2f}x{bh:.2f} pt "
        f"({bw / 72:.4f}x{bh / 72:.4f} in)  |  "
        f"mode: {'design behind, text on top' if design_behind else 'text behind, borders on top'}"
    )
    print(
        f"  Design pages: {borders.page_count}  |  "
        f"contents={'ON (p1)' if use_contents else 'OFF'}  |  "
        f"indices contents={indices['contents']} right={indices['right']} left={indices['left']}"
    )
    if facing_pads:
        print(f"  Placement: facing pads odd={ODD_PAD} even={EVEN_PAD}")
    else:
        print(
            f"  Placement: center-X L={(PAGE_W - bw) / 2:.2f}, "
            f"measured top T={ODD_PAD[1]:.2f}"
        )

    if design_behind:
        text = prepare_text_pdf(text_pdf, white_thresh=white_thresh)
        print("  Text overlay: cleaned vector PDF on top of design")
    else:
        text = fitz.open(text_pdf)

    border_stamps: dict[int, fitz.Pixmap] | None = None
    if not design_behind:
        border_stamps = {}
        needed = {indices["right"], indices["left"]}
        if indices["contents"] is not None:
            needed.add(indices["contents"])
        for bi in sorted(x for x in needed if x is not None):
            border_stamps[int(bi)] = knock_out_background(
                borders[int(bi)], dpi=dpi, white_thresh=white_thresh
            )

    sel = page_indices if page_indices is not None else list(range(text.page_count))
    for ti in sel:
        if ti < 0 or ti >= text.page_count:
            continue
        page_no = ti + 1
        bi = design_page_index(page_no, indices, use_contents=use_contents)
        dest = placement_for_page(page_no, bw, bh, facing_pads=facing_pads)
        page = out.new_page(width=PAGE_W, height=PAGE_H)

        if design_behind:
            page.show_pdf_page(dest, borders, bi, keep_proportion=False)
            page.show_pdf_page(page.rect, text, ti, keep_proportion=False, overlay=True)
        else:
            assert border_stamps is not None
            page.show_pdf_page(page.rect, text, ti, keep_proportion=False)
            page.insert_image(
                dest, pixmap=border_stamps[bi], keep_proportion=False, overlay=True
            )

        print(
            f"  page {page_no}: {design_label(bi, indices)} "
            f"(Canva p{bi + 1}) at ({dest.x0:.1f},{dest.y0:.1f})"
        )

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    out.save(out_pdf, deflate=True, garbage=4)
    info = {
        "pages": len(sel),
        "output": str(out_pdf.resolve()),
        "border_size_pt": (bw, bh),
        "output_size_pt": (PAGE_W, PAGE_H),
        "design_behind": design_behind,
        "use_contents": use_contents,
    }
    out.close()
    text.close()
    borders.close()
    return info


def parse_pages(spec: str | None, n: int) -> list[int] | None:
    if not spec:
        return None
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            for p in range(int(a), int(b) + 1):
                if 1 <= p <= n:
                    pages.add(p - 1)
        else:
            p = int(part)
            if 1 <= p <= n:
                pages.add(p - 1)
    return sorted(pages)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Merge Canva SSBM border masters with Letter text PDFs. "
            "Design behind text by default. Use --contents for a 3-page master "
            "[contents, right, left]."
        )
    )
    ap.add_argument(
        "border_pdf",
        type=Path,
        help="Canva master: 2pg [right,left] or 3pg [contents,right,left]",
    )
    ap.add_argument("text_pdf", type=Path, help="Letter text PDF (Word/Docs)")
    ap.add_argument("-o", "--output", type=Path, required=True, help="Merged output PDF")
    ap.add_argument(
        "--contents",
        action="store_true",
        help=(
            "Use design page 1 as contents master for text page 1; "
            "then left, right, left, right... Requires 3-page design PDF."
        ),
    )
    ap.add_argument("--dpi", type=float, default=200.0, help="Legacy raster DPI")
    ap.add_argument(
        "--white-thresh",
        type=int,
        default=248,
        help="RGB >= this treated as transparent in plate images (default 248)",
    )
    ap.add_argument("--pages", type=str, default=None, help="Subset e.g. 1-4 (1-based)")
    ap.add_argument(
        "--borders-on-top",
        action="store_true",
        help="Legacy: text under, border decorations stamped on top",
    )
    ap.add_argument(
        "--facing-pads",
        action="store_true",
        help="Use odd/even outer pads from print proof",
    )
    args = ap.parse_args(argv)

    if not args.border_pdf.is_file():
        print(f"Not found: {args.border_pdf}", file=sys.stderr)
        return 1
    if not args.text_pdf.is_file():
        print(f"Not found: {args.text_pdf}", file=sys.stderr)
        return 1

    text_count = fitz.open(args.text_pdf).page_count
    page_sel = parse_pages(args.pages, text_count)

    print(f"Border: {args.border_pdf}")
    print(f"Text:   {args.text_pdf}")
    print(f"Output: {args.output}")
    info = merge(
        args.border_pdf,
        args.text_pdf,
        args.output,
        dpi=args.dpi,
        white_thresh=args.white_thresh,
        page_indices=page_sel,
        design_behind=not args.borders_on_top,
        facing_pads=args.facing_pads,
        use_contents=args.contents,
    )
    bw, bh = info["border_size_pt"]
    print(
        f"Done: {info['pages']} pages -> {info['output']}\n"
        f"  Canva frame: {bw:.2f}x{bh:.2f} pt ({bw / 72:.4f}x{bh / 72:.4f} in)\n"
        f"  Output page: {PAGE_W:.0f}x{PAGE_H:.0f} pt (Letter 8.5x11 in)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
