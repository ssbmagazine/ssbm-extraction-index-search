"""Column-aware PDF extract with image export and per-page QA hooks."""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
from typing import Any

import fitz  # PyMuPDF

from anu_decoder import AnuToUnicodeDecoder
from qa_metrics import analyze_text_glyphs, merge_edition_qa, page_layout_coverage
from telugu_normalize import normalize_telugu_text

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


TELUGU_FONT_KEYWORDS = (
    "priyaanka",
    "ajantha",
    "brahma",
    "manupama",
    "royankee",
    "anu",
    "kranthi",
    "ramana",
    "ramanabrush",
)


def is_telugu_font(font_name: str | None) -> bool:
    if not font_name:
        return False
    lower = font_name.lower()
    return any(kw in lower for kw in TELUGU_FONT_KEYWORDS)


def _cluster_columns(blocks: list[dict], page_width: float) -> list[dict]:
    """Sort blocks in reading order: left column then right when clearly multi-column."""
    if len(blocks) < 4:
        return sorted(blocks, key=lambda b: (b["bbox"][1], b["bbox"][0]))

    centers = [((b["bbox"][0] + b["bbox"][2]) / 2.0) for b in blocks]
    mid = page_width / 2.0
    left = [b for b, c in zip(blocks, centers) if c < mid - 25]
    right = [b for b, c in zip(blocks, centers) if c >= mid - 25]

    # Only treat as two columns if both sides have meaningful content and little vertical overlap chaos
    if len(left) >= 2 and len(right) >= 2:
        left_sorted = sorted(left, key=lambda b: (b["bbox"][1], b["bbox"][0]))
        right_sorted = sorted(right, key=lambda b: (b["bbox"][1], b["bbox"][0]))
        return left_sorted + right_sorted

    return sorted(blocks, key=lambda b: (b["bbox"][1], b["bbox"][0]))


def _classify_block(
    bbox: list[float],
    text: str,
    page_width: float,
    line_count: int,
) -> str:
    x0, y0, x1, y1 = bbox
    center_x = page_width / 2.0
    block_center = (x0 + x1) / 2.0
    cleaned = text.strip()
    is_centered = abs(block_center - center_x) < 40.0
    is_right = x0 > page_width * 0.55 and (x1 > page_width * 0.75)
    is_short = line_count <= 2 and len(cleaned) < 80

    if is_centered and is_short and len(cleaned) < 60:
        return "heading"
    if is_right and is_short and len(cleaned) < 60:
        return "right_subheading"
    return "paragraph"


def extract_pdf_to_structured_text(
    pdf_path: str,
    header_ratio: float = 0.12,
    footer_ratio: float = 0.92,
    images_dir: str | None = None,
) -> dict[str, Any] | None:
    if not os.path.exists(pdf_path):
        print(f"Error: File not found at {pdf_path}")
        return None

    doc = fitz.open(pdf_path)
    decoder = AnuToUnicodeDecoder()
    abs_pdf = os.path.abspath(pdf_path)

    extracted: dict[str, Any] = {
        "metadata": dict(doc.metadata or {}),
        "pdf_path": abs_pdf,
        "total_pages": len(doc),
        "pages": [],
        "images": [],
        "page_qa": [],
    }
    extracted["metadata"]["path"] = abs_pdf

    unique_fonts: set[str] = set()
    image_counter = 0

    if images_dir:
        os.makedirs(images_dir, exist_ok=True)

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_width = page.rect.width
        page_height = page.rect.height
        header_y = page_height * header_ratio
        footer_y = page_height * footer_ratio

        for f in page.get_fonts():
            unique_fonts.add(f[3])

        page_dict = page.get_text("dict")
        raw_text_blocks = 0
        raw_spans = 0
        kept_spans = 0
        dropped_hf_spans = 0
        page_text_parts: list[str] = []
        provisional_blocks: list[dict] = []

        for block_no, b in enumerate(page_dict.get("blocks", [])):
            if b.get("type") != 0:
                continue

            raw_text_blocks += 1
            x0, y0, x1, y1 = b.get("bbox")
            lines = b.get("lines", [])
            block_span_count = sum(len(line.get("spans", [])) for line in lines)
            raw_spans += block_span_count

            # Soft header/footer: skip only if entire block is outside body band
            if y1 < header_y:
                dropped_hf_spans += block_span_count
                continue
            if y0 > footer_y:
                dropped_hf_spans += block_span_count
                continue

            block_text_parts: list[str] = []
            for line in lines:
                line_parts: list[str] = []
                for span in line.get("spans", []):
                    span_text = span.get("text", "")
                    font_name = span.get("font", "")
                    kept_spans += 1
                    if is_telugu_font(font_name):
                        decoded = decoder.decode(span_text, layout="anu6")
                    else:
                        decoded = span_text
                    line_parts.append(decoded)
                block_text_parts.append("".join(line_parts))

            decoded_text = "\n".join(block_text_parts)
            cleaned = normalize_telugu_text(decoded_text.strip())
            if not cleaned:
                continue

            bbox = [x0, y0, x1, y1]
            btype = _classify_block(bbox, cleaned, page_width, len(lines))
            provisional_blocks.append(
                {
                    "block_no": block_no,
                    "bbox": bbox,
                    "type": btype,
                    "text": cleaned,
                    "alignment": (
                        "right"
                        if btype == "right_subheading"
                        else ("center" if btype == "heading" else "left")
                    ),
                }
            )
            page_text_parts.append(cleaned)

        ordered = _cluster_columns(provisional_blocks, page_width)
        # Re-number after sort for stable reading order
        for i, blk in enumerate(ordered):
            blk["reading_order"] = i

        # Extract embedded images once per page (dedupe by xref within page)
        page_images: list[dict] = []
        if images_dir is not None:
            seen_xref: set[int] = set()
            for img_info in page.get_images(full=True):
                xref = img_info[0]
                if xref in seen_xref:
                    continue
                seen_xref.add(xref)
                try:
                    pix = fitz.Pixmap(doc, xref)
                    if pix.n > 4:
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    image_counter += 1
                    fname = f"p{page_idx + 1:03d}_img{image_counter:03d}.png"
                    fpath = os.path.join(images_dir, fname)
                    pix.save(fpath)
                    meta = {
                        "page_number": page_idx + 1,
                        "path": os.path.abspath(fpath),
                        "xref": xref,
                        "width": pix.width,
                        "height": pix.height,
                    }
                    page_images.append(meta)
                    extracted["images"].append(meta)
                except Exception:
                    continue

        page_body = "\n\n".join(page_text_parts)
        glyph_qa = analyze_text_glyphs(page_body)
        layout_qa = page_layout_coverage(
            raw_spans, kept_spans, raw_text_blocks, len(ordered), dropped_hf_spans
        )

        extracted["pages"].append(
            {
                "page_number": page_idx + 1,
                "width": page_width,
                "height": page_height,
                "blocks": ordered,
                "images": page_images,
            }
        )
        extracted["page_qa"].append(
            {
                "page_number": page_idx + 1,
                "glyphs": glyph_qa,
                "layout": layout_qa,
            }
        )

    extracted["detected_fonts"] = sorted(unique_fonts)
    extracted["qa_summary"] = merge_edition_qa(extracted["page_qa"])
    doc.close()
    return extracted


def save_to_text(data: dict, output_path: str) -> None:
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("SSBM Magazine Archival Export\n")
        f.write(f"Title: {data['metadata'].get('title', 'Unknown')}\n")
        f.write(f"PDF: {data.get('pdf_path', '')}\n")
        f.write(f"Total Pages: {data['total_pages']}\n")
        f.write(f"Detected Fonts: {', '.join(data.get('detected_fonts', []))}\n")
        f.write("=" * 60 + "\n\n")
        for page in data["pages"]:
            f.write(f"--- Page {page['page_number']} ---\n\n")
            for block in page["blocks"]:
                prefix = ""
                if block["type"] == "heading":
                    prefix = "[HEADING] "
                elif block["type"] == "right_subheading":
                    prefix = "[RIGHT] "
                f.write(f"{prefix}{block['text']}\n\n")
            f.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="SSBM Telugu PDF Text Extractor")
    parser.add_argument("pdf_path", help="Path to the Telugu PDF file")
    parser.add_argument("-o", "--output", help="Path to save the output file")
    parser.add_argument(
        "-f", "--format", choices=["json", "txt"], default="json", help="Output format"
    )
    parser.add_argument(
        "--images-dir", help="Directory to save extracted images (optional)"
    )
    args = parser.parse_args()

    output_path = args.output
    if not output_path:
        base_name, _ = os.path.splitext(args.pdf_path)
        output_path = f"{base_name}_extracted.{args.format}"

    print(f"Extracting {args.pdf_path}...")
    data = extract_pdf_to_structured_text(args.pdf_path, images_dir=args.images_dir)
    if not data:
        sys.exit(1)

    if args.format == "json":
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    else:
        save_to_text(data, output_path)
    print(f"Successfully extracted and saved to: {output_path}")
    qa = data.get("qa_summary", {})
    print(
        f"QA: latin={qa.get('latin_leftover_count')} "
        f"split_matra={qa.get('split_matra_count')} flags={qa.get('flags')}"
    )


if __name__ == "__main__":
    main()
