#!/usr/bin/env python3
"""
Measure PDF page geometry for print consistency checks.

Focuses on three sizes the layout team usually needs:
  1. Outer padding  – white margin from page edge to the outer border/frame
  2. Framed page    – page size without that outer padding (live/framed area)
  3. Inner content  – area inside the decorative border (no border, no outer pad)

Also reports formal Media/Crop/Bleed/Trim/Art boxes when present.

Units everywhere: points (1 pt = 1/72 in), inches, and mm.

Usage:
  python tools/measure_pdf_pages.py "path/to/file.pdf"
  python tools/measure_pdf_pages.py "path/to/file.pdf" --json out.json
  python tools/measure_pdf_pages.py "path/to/file.pdf" --dpi 200 --pages 1-5,10
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import fitz
import numpy as np

PT_PER_IN = 72.0
MM_PER_IN = 25.4


def pt_to_in(v: float) -> float:
    return v / PT_PER_IN


def pt_to_mm(v: float) -> float:
    return v / PT_PER_IN * MM_PER_IN


def size_triplet(w_pt: float, h_pt: float) -> dict[str, float]:
    return {
        "width_pt": round(w_pt, 3),
        "height_pt": round(h_pt, 3),
        "width_in": round(pt_to_in(w_pt), 4),
        "height_in": round(pt_to_in(h_pt), 4),
        "width_mm": round(pt_to_mm(w_pt), 3),
        "height_mm": round(pt_to_mm(h_pt), 3),
    }


def pad_triplet(left: float, top: float, right: float, bottom: float) -> dict[str, float]:
    out: dict[str, float] = {
        "left_pt": round(left, 3),
        "top_pt": round(top, 3),
        "right_pt": round(right, 3),
        "bottom_pt": round(bottom, 3),
    }
    for side in ("left", "top", "right", "bottom"):
        out[f"{side}_in"] = round(pt_to_in(out[f"{side}_pt"]), 4)
        out[f"{side}_mm"] = round(pt_to_mm(out[f"{side}_pt"]), 3)
    return out


def fmt_size(w_pt: float, h_pt: float) -> str:
    return (
        f"{w_pt:.2f} x {h_pt:.2f} pt  |  "
        f"{pt_to_in(w_pt):.4f} x {pt_to_in(h_pt):.4f} in  |  "
        f"{pt_to_mm(w_pt):.2f} x {pt_to_mm(h_pt):.2f} mm"
    )


def fmt_len(v_pt: float) -> str:
    return f"{v_pt:.2f} pt  |  {pt_to_in(v_pt):.4f} in  |  {pt_to_mm(v_pt):.2f} mm"


def fmt_pads(p: dict[str, float]) -> str:
    return (
        f"L {fmt_len(p['left_pt'])}\n"
        f"      T {fmt_len(p['top_pt'])}\n"
        f"      R {fmt_len(p['right_pt'])}\n"
        f"      B {fmt_len(p['bottom_pt'])}"
    )


def rect_dict(r: fitz.Rect) -> dict[str, float]:
    d = {
        "x0": round(r.x0, 3),
        "y0": round(r.y0, 3),
        "x1": round(r.x1, 3),
        "y1": round(r.y1, 3),
    }
    d.update(size_triplet(r.width, r.height))
    return d


def boxes_differ(a: fitz.Rect, b: fitz.Rect, tol: float = 0.5) -> bool:
    return (
        abs(a.x0 - b.x0) > tol
        or abs(a.y0 - b.y0) > tol
        or abs(a.x1 - b.x1) > tol
        or abs(a.y1 - b.y1) > tol
    )


def _first_drop(dens: np.ndarray, start: int, end: int, step: int, high: float, low: float) -> int | None:
    """Walk from outer edge inward; return index of last high-density sample before drop."""
    in_high = False
    last_high = None
    for i in range(start, end, step):
        d = float(dens[i])
        if d >= high:
            in_high = True
            last_high = i
        elif in_high and d < low:
            return last_high
    return last_high


def detect_geometry(
    page: fitz.Page,
    dpi: float = 200.0,
    white_thresh: int = 248,
    border_high: float = 0.55,
    border_low: float = 0.35,
) -> dict[str, Any] | None:
    """
    Detect:
      - outer_pad: page edge -> outer frame
      - framed: outer ink bbox (page without outer padding)
      - inner: area after decorative border density drops
      - border_thickness: framed edge -> inner edge
    """
    mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    pix = page.get_pixmap(matrix=mat, colorspace=fitz.csGRAY, alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w)
    ink = arr < white_thresh
    rows = np.any(ink, axis=1)
    cols = np.any(ink, axis=0)
    if not rows.any() or not cols.any():
        return None

    scale = 72.0 / dpi
    page_w, page_h = page.rect.width, page.rect.height

    y0p, y1p = [int(v) for v in np.where(rows)[0][[0, -1]]]
    x0p, x1p = [int(v) for v in np.where(cols)[0][[0, -1]]]

    # Prefer dense frame start when sparse ink sticks outside (e.g. page 11).
    col_dens = ink.mean(axis=0)
    row_dens = ink.mean(axis=1)
    dense_cols = np.where(col_dens >= border_high)[0]
    dense_rows = np.where(row_dens >= border_high)[0]
    if len(dense_cols) >= 2:
        # Outer frame = first/last dense column near the ink extremes
        near_left = dense_cols[dense_cols <= x0p + int(0.15 * (x1p - x0p))]
        near_right = dense_cols[dense_cols >= x1p - int(0.15 * (x1p - x0p))]
        if len(near_left) and len(near_right):
            x0p = int(near_left[0])
            x1p = int(near_right[-1])
    if len(dense_rows) >= 2:
        near_top = dense_rows[dense_rows <= y0p + int(0.15 * (y1p - y0p))]
        near_bot = dense_rows[dense_rows >= y1p - int(0.15 * (y1p - y0p))]
        if len(near_top) and len(near_bot):
            y0p = int(near_top[0])
            y1p = int(near_bot[-1])

    # Inner edges: walk inward from framed outer edge through high-density border.
    left_high = _first_drop(col_dens, x0p, x1p, 1, border_high, border_low)
    right_high = _first_drop(col_dens, x1p, x0p, -1, border_high, border_low)
    top_high = _first_drop(row_dens, y0p, y1p, 1, border_high, border_low)
    bot_high = _first_drop(row_dens, y1p, y0p, -1, border_high, border_low)

    border_detected = (
        left_high is not None
        and right_high is not None
        and top_high is not None
        and bot_high is not None
        and left_high < right_high
        and top_high < bot_high
    )

    if border_detected:
        # Content starts just inside the high-density border band.
        ix0p = left_high + 1
        ix1p = right_high  # exclusive end at first pixel of right border
        iy0p = top_high + 1
        iy1p = bot_high
        if ix1p <= ix0p or iy1p <= iy0p:
            ix0p, iy0p, ix1p, iy1p = x0p, y0p, x1p + 1, y1p + 1
            border_detected = False
    else:
        ix0p, iy0p, ix1p, iy1p = x0p, y0p, x1p + 1, y1p + 1

    # Point coords (outer framed uses inclusive pixel ends -> +1)
    fx0, fy0 = x0p * scale, y0p * scale
    fx1, fy1 = (x1p + 1) * scale, (y1p + 1) * scale
    ix0, iy0 = ix0p * scale, iy0p * scale
    ix1, iy1 = ix1p * scale, iy1p * scale

    outer_pad = pad_triplet(fx0, fy0, page_w - fx1, page_h - fy1)
    framed = size_triplet(fx1 - fx0, fy1 - fy0)
    framed["bbox_pt"] = [round(fx0, 3), round(fy0, 3), round(fx1, 3), round(fy1, 3)]

    inner = size_triplet(ix1 - ix0, iy1 - iy0)
    inner["bbox_pt"] = [round(ix0, 3), round(iy0, 3), round(ix1, 3), round(iy1, 3)]

    border = pad_triplet(ix0 - fx0, iy0 - fy0, fx1 - ix1, fy1 - iy1)

    return {
        "outer_padding": outer_pad,
        "framed_page": framed,  # page without outer padding
        "inner_content": inner,  # without borders / outer padding
        "border_thickness": border,
        "border_detected": border_detected,
        "dpi": dpi,
    }


def content_bbox_from_objects(page: fitz.Page) -> tuple[float, float, float, float] | None:
    xs0: list[float] = []
    ys0: list[float] = []
    xs1: list[float] = []
    ys1: list[float] = []

    for b in page.get_text("blocks"):
        xs0.append(b[0]); ys0.append(b[1]); xs1.append(b[2]); ys1.append(b[3])
    for d in page.get_drawings():
        r = d.get("rect")
        if r is None or r.width < 0.5 or r.height < 0.5:
            continue
        xs0.append(r.x0); ys0.append(r.y0); xs1.append(r.x1); ys1.append(r.y1)
    for img in page.get_image_info():
        bb = img.get("bbox")
        if not bb:
            continue
        xs0.append(bb[0]); ys0.append(bb[1]); xs1.append(bb[2]); ys1.append(bb[3])
    if not xs0:
        return None
    return (min(xs0), min(ys0), max(xs1), max(ys1))


def _paper_name(w: float, h: float, tol: float = 2.0) -> str:
    candidates = {
        "Letter": (612, 792),
        "Legal": (612, 1008),
        "Tabloid": (792, 1224),
        "A4": (595.28, 841.89),
        "A3": (841.89, 1190.55),
        "A5": (419.53, 595.28),
    }
    for name, (cw, ch) in candidates.items():
        if (abs(w - cw) <= tol and abs(h - ch) <= tol) or (
            abs(w - ch) <= tol and abs(h - cw) <= tol
        ):
            return name
    return "Custom"


def measure_page(page: fitz.Page, page_index: int, dpi: float) -> dict[str, Any]:
    media = page.mediabox
    crop = page.cropbox
    bleed = page.bleedbox
    trim = page.trimbox
    art = page.artbox
    page_w, page_h = page.rect.width, page.rect.height

    formal_bleed = boxes_differ(bleed, media) or boxes_differ(bleed, trim)
    formal_trim = boxes_differ(trim, media)

    out: dict[str, Any] = {
        "page": page_index + 1,
        "rotation": page.rotation,
        "page_size": {
            **size_triplet(page_w, page_h),
            "common_name": _paper_name(page_w, page_h),
        },
        "pdf_boxes": {
            "MediaBox": rect_dict(media),
            "CropBox": rect_dict(crop),
            "BleedBox": rect_dict(bleed),
            "TrimBox": rect_dict(trim),
            "ArtBox": rect_dict(art),
        },
        "formal_trim_defined": formal_trim,
        "formal_bleed_defined": formal_bleed,
    }

    if formal_trim or formal_bleed:
        out["trim_size"] = size_triplet(trim.width, trim.height)
        out["bleed_padding_outside_trim"] = pad_triplet(
            trim.x0 - media.x0,
            trim.y0 - media.y0,
            media.x1 - trim.x1,
            media.y1 - trim.y1,
        )

    geom = detect_geometry(page, dpi=dpi)
    if geom is None:
        out["empty_or_blank"] = True
    else:
        out["empty_or_blank"] = False
        out.update(geom)

    return out


def parse_pages_spec(spec: str | None, n_pages: int) -> list[int]:
    if not spec:
        return list(range(n_pages))
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            for p in range(int(a), int(b) + 1):
                if 1 <= p <= n_pages:
                    pages.add(p - 1)
        else:
            p = int(part)
            if 1 <= p <= n_pages:
                pages.add(p - 1)
    return sorted(pages)


def _median_pad(group: list[dict], key: str = "outer_padding") -> dict[str, float]:
    sides = {}
    for side in ("left", "top", "right", "bottom"):
        vals = [p[key][f"{side}_pt"] for p in group]
        med = statistics.median(vals)
        sides[f"{side}_pt"] = round(med, 3)
        sides[f"{side}_in"] = round(pt_to_in(med), 4)
        sides[f"{side}_mm"] = round(pt_to_mm(med), 3)
    return sides


def _median_size(group: list[dict], key: str) -> dict[str, float]:
    ws = [p[key]["width_pt"] for p in group]
    hs = [p[key]["height_pt"] for p in group]
    return size_triplet(statistics.median(ws), statistics.median(hs))


def summarize(pages: list[dict[str, Any]]) -> dict[str, Any]:
    non_empty = [p for p in pages if not p.get("empty_or_blank")]
    size_counts = Counter(
        (round(p["page_size"]["width_pt"], 2), round(p["page_size"]["height_pt"], 2))
        for p in pages
    )
    summary: dict[str, Any] = {
        "page_count": len(pages),
        "non_empty_pages": len(non_empty),
        "blank_pages": [p["page"] for p in pages if p.get("empty_or_blank")],
        "page_size_variants": [
            {**size_triplet(w, h), "count": c, "name": _paper_name(w, h)}
            for (w, h), c in size_counts.most_common()
        ],
        "any_formal_trim_box": any(p.get("formal_trim_defined") for p in pages),
        "any_formal_bleed_box": any(p.get("formal_bleed_defined") for p in pages),
    }
    if not non_empty:
        return summary

    summary["outer_padding_median"] = _median_pad(non_empty, "outer_padding")
    summary["framed_page_median"] = _median_size(non_empty, "framed_page")
    summary["inner_content_median"] = _median_size(non_empty, "inner_content")
    summary["border_thickness_median"] = _median_pad(non_empty, "border_thickness")

    for label, group in (
        ("odd_pages", [p for p in non_empty if p["page"] % 2 == 1]),
        ("even_pages", [p for p in non_empty if p["page"] % 2 == 0]),
    ):
        if not group:
            continue
        summary[label] = {
            "outer_padding": _median_pad(group, "outer_padding"),
            "framed_page": _median_size(group, "framed_page"),
            "inner_content": _median_size(group, "inner_content"),
            "border_thickness": _median_pad(group, "border_thickness"),
        }
    return summary


def format_report(path: Path, meta: dict, summary: dict, pages: list[dict]) -> str:
    lines: list[str] = []
    lines.append(f"PDF: {path}")
    lines.append(f"Producer: {meta.get('producer') or '(none)'}")
    lines.append(
        f"Pages measured: {summary['page_count']} "
        f"(non-empty: {summary['non_empty_pages']})"
    )
    if summary["blank_pages"]:
        lines.append(f"Blank pages: {summary['blank_pages']}")

    lines.append("")
    lines.append("=" * 72)
    lines.append("1) FULL PAGE SIZE (MediaBox)")
    lines.append("=" * 72)
    for v in summary["page_size_variants"]:
        lines.append(
            f"  {v['name']}: {fmt_size(v['width_pt'], v['height_pt'])}  ({v['count']} pages)"
        )

    lines.append("")
    lines.append("=" * 72)
    lines.append("2) OUTER PADDING  (page edge -> outer border/frame)")
    lines.append("=" * 72)
    if "outer_padding_median" in summary:
        lines.append(f"  Overall median:\n      {fmt_pads(summary['outer_padding_median'])}")
    for label, title in (("odd_pages", "Odd pages"), ("even_pages", "Even pages")):
        g = summary.get(label)
        if not g:
            continue
        lines.append(f"  {title}:\n      {fmt_pads(g['outer_padding'])}")

    lines.append("")
    lines.append("=" * 72)
    lines.append("3) PAGE WITHOUT OUTER PADDING  (framed / live area)")
    lines.append("=" * 72)
    if "framed_page_median" in summary:
        f = summary["framed_page_median"]
        lines.append(f"  Overall median: {fmt_size(f['width_pt'], f['height_pt'])}")
    for label, title in (("odd_pages", "Odd pages"), ("even_pages", "Even pages")):
        g = summary.get(label)
        if not g:
            continue
        f = g["framed_page"]
        lines.append(f"  {title}: {fmt_size(f['width_pt'], f['height_pt'])}")

    lines.append("")
    lines.append("=" * 72)
    lines.append("4) INNER CONTENT  (inside borders; no border, no outer pad)")
    lines.append("=" * 72)
    if "inner_content_median" in summary:
        f = summary["inner_content_median"]
        lines.append(f"  Overall median: {fmt_size(f['width_pt'], f['height_pt'])}")
    if "border_thickness_median" in summary:
        lines.append(f"  Border thickness (median):\n      {fmt_pads(summary['border_thickness_median'])}")
    for label, title in (("odd_pages", "Odd pages"), ("even_pages", "Even pages")):
        g = summary.get(label)
        if not g:
            continue
        f = g["inner_content"]
        lines.append(f"  {title}: {fmt_size(f['width_pt'], f['height_pt'])}")

    lines.append("")
    lines.append("=" * 72)
    lines.append("Formal Trim/Bleed metadata")
    lines.append("=" * 72)
    lines.append(f"  TrimBox distinct: {summary['any_formal_trim_box']}")
    lines.append(f"  BleedBox distinct: {summary['any_formal_bleed_box']}")
    if not summary["any_formal_trim_box"]:
        lines.append(
            "  NOTE: No Trim/Bleed boxes (typical of Microsoft Print-to-PDF). "
            "Sizes above are inferred from visible ink/borders."
        )

    lines.append("")
    lines.append("=" * 72)
    lines.append("Per-page detail (all units: pt | in | mm)")
    lines.append("=" * 72)
    for p in pages:
        if p.get("empty_or_blank"):
            lines.append(f"\nPage {p['page']}: BLANK")
            continue
        ps = p["page_size"]
        op = p["outer_padding"]
        fr = p["framed_page"]
        inn = p["inner_content"]
        bt = p["border_thickness"]
        lines.append(f"\nPage {p['page']}:")
        lines.append(f"  Full page:     {fmt_size(ps['width_pt'], ps['height_pt'])}")
        lines.append(f"  Outer pad:     L={fmt_len(op['left_pt'])}")
        lines.append(f"                 T={fmt_len(op['top_pt'])}")
        lines.append(f"                 R={fmt_len(op['right_pt'])}")
        lines.append(f"                 B={fmt_len(op['bottom_pt'])}")
        lines.append(f"  Framed page:   {fmt_size(fr['width_pt'], fr['height_pt'])}")
        lines.append(f"  Border thick:  L={fmt_len(bt['left_pt'])}  R={fmt_len(bt['right_pt'])}")
        lines.append(f"                 T={fmt_len(bt['top_pt'])}  B={fmt_len(bt['bottom_pt'])}")
        lines.append(f"  Inner content: {fmt_size(inn['width_pt'], inn['height_pt'])}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Measure PDF page sizes, outer padding, framed area, and inner content."
    )
    ap.add_argument("pdf", type=Path, help="Path to PDF")
    ap.add_argument("--dpi", type=float, default=200.0, help="Raster DPI (default 200)")
    ap.add_argument("--pages", type=str, default=None, help="Pages e.g. 1-5,10 (1-based)")
    ap.add_argument("--json", type=Path, default=None, help="Write full JSON report")
    args = ap.parse_args(argv)

    pdf_path = args.pdf
    if not pdf_path.is_file():
        print(f"File not found: {pdf_path}", file=sys.stderr)
        return 1

    doc = fitz.open(pdf_path)
    try:
        indices = parse_pages_spec(args.pages, doc.page_count)
        pages = [measure_page(doc[i], i, dpi=args.dpi) for i in indices]
        summary = summarize(pages)
        report = {
            "file": str(pdf_path.resolve()),
            "metadata": dict(doc.metadata or {}),
            "summary": summary,
            "pages": pages,
        }
        text = format_report(pdf_path, report["metadata"], summary, pages)
        try:
            print(text)
        except UnicodeEncodeError:
            print(text.encode("ascii", "replace").decode("ascii"))
        if args.json:
            args.json.parent.mkdir(parents=True, exist_ok=True)
            args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(f"\nJSON written: {args.json}")
    finally:
        doc.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
