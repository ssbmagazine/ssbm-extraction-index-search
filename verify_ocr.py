"""Tesseract-based verification of decoded extract vs page OCR."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from collections import Counter
from typing import Any

import fitz

from telugu_normalize import has_split_virama

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

_TELUGU = re.compile(r"[\u0C00-\u0C7F]+")
_WORD = re.compile(r"[A-Za-z\u0C00-\u0C7F]{2,}")


def _collapse(text: str) -> str:
    text = unicodedata.normalize("NFC", text or "")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _telugu_mass(text: str) -> int:
    return sum(len(m.group(0)) for m in _TELUGU.finditer(text or ""))


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text or ""))


def _configure_tesseract() -> None:
    """Point pytesseract at installed binary and local/project tessdata if present."""
    import os
    import shutil

    import pytesseract

    exe = shutil.which("tesseract")
    if not exe:
        for candidate in (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ):
            if os.path.exists(candidate):
                exe = candidate
                break
    if exe:
        pytesseract.pytesseract.tesseract_cmd = exe

    local_tess = os.path.join(os.path.dirname(__file__), "tessdata")
    if os.path.isdir(local_tess) and os.path.exists(os.path.join(local_tess, "eng.traineddata")):
        # Mannheim Windows builds treat TESSDATA_PREFIX as the folder with *.traineddata
        os.environ["TESSDATA_PREFIX"] = local_tess


def ocr_page_pixmap(pix) -> str:
    try:
        import pytesseract
        from PIL import Image
        import io

        _configure_tesseract()
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        # Prefer tel+eng when tel is available; fall back to eng
        try:
            return pytesseract.image_to_string(img, lang="tel+eng", config="--oem 1")
        except pytesseract.TesseractError:
            return pytesseract.image_to_string(img, lang="eng", config="--oem 1")
    except Exception as exc:
        return f"__OCR_ERROR__:{exc}"


def verify_edition(
    pdf_path: str,
    extracted: dict[str, Any],
    max_pages: int | None = None,
    zoom: float = 2.0,
) -> dict[str, Any]:
    """Compare OCR vs decode for each page; return report."""
    doc = fitz.open(pdf_path)
    page_reports = []
    split_pages = []
    coverage_flags = []
    disagreement: Counter = Counter()

    n = len(doc)
    if max_pages is not None:
        n = min(n, max_pages)

    decode_by_page = {
        p["page_number"]: "\n".join(
            b.get("text", "") for b in p.get("blocks") or []
        )
        for p in extracted.get("pages") or []
    }

    ocr_available = True
    for i in range(n):
        page = doc[i]
        pn = i + 1
        decode_text = decode_by_page.get(pn, "")
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        ocr_raw = ocr_page_pixmap(pix)
        if ocr_raw.startswith("__OCR_ERROR__"):
            ocr_available = False
            page_reports.append(
                {
                    "page_number": pn,
                    "ocr_error": ocr_raw,
                    "flags": ["ocr_unavailable"],
                }
            )
            continue

        ocr_n = _collapse(ocr_raw)
        dec_n = _collapse(decode_text)
        ocr_mass = _telugu_mass(ocr_n)
        dec_mass = _telugu_mass(dec_n)
        ratio = (dec_mass / ocr_mass) if ocr_mass else 1.0

        flags = []
        if has_split_virama(decode_text):
            flags.append("split_virama")
            split_pages.append(pn)
        if ocr_mass > 40 and ratio < 0.55:
            flags.append("coverage_low")
            coverage_flags.append(pn)

        ocr_toks = _tokens(ocr_n)
        dec_toks = _tokens(dec_n)
        missing_in_decode = sorted(ocr_toks - dec_toks, key=len, reverse=True)[:8]
        extra_in_decode = sorted(dec_toks - ocr_toks, key=len, reverse=True)[:8]
        for t in missing_in_decode[:5]:
            if _TELUGU.search(t) or t.isalpha():
                disagreement[t] += 1

        page_reports.append(
            {
                "page_number": pn,
                "ocr_telugu_mass": ocr_mass,
                "decode_telugu_mass": dec_mass,
                "decode_ocr_ratio": round(ratio, 3),
                "flags": flags,
                "missing_in_decode_sample": missing_in_decode,
                "extra_in_decode_sample": extra_in_decode,
            }
        )

    doc.close()
    edition_flags = []
    if split_pages:
        edition_flags.append("split_virama")
    if coverage_flags:
        edition_flags.append("coverage_low")
    if not ocr_available:
        edition_flags.append("ocr_unavailable")
    if edition_flags:
        edition_flags.append("needs_review")

    return {
        "pdf_path": os.path.abspath(pdf_path),
        "ocr_available": ocr_available,
        "pages": page_reports,
        "split_virama_pages": split_pages,
        "coverage_low_pages": coverage_flags,
        "top_ocr_not_in_decode": [t for t, _ in disagreement.most_common(30)],
        "flags": edition_flags,
    }


def verify_and_write(
    pdf_path: str,
    extracted: dict[str, Any],
    edition_dir: str,
    max_pages: int | None = None,
) -> dict[str, Any]:
    report = verify_edition(pdf_path, extracted, max_pages=max_pages)
    # Merge into qa_report.json if present
    qa_path = os.path.join(edition_dir, "qa_report.json")
    existing = {}
    if os.path.exists(qa_path):
        with open(qa_path, encoding="utf-8") as f:
            existing = json.load(f)
    existing["ocr_verify"] = report
    flags = list(dict.fromkeys((existing.get("flags") or []) + report.get("flags", [])))
    # edition.json may hold flags separately
    existing["flags"] = flags
    with open(qa_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    ocr_path = os.path.join(edition_dir, "ocr_verify.json")
    with open(ocr_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return report


def main():
    parser = argparse.ArgumentParser(description="OCR verify an archive edition")
    parser.add_argument("edition_dir", help="archive/<id> directory")
    parser.add_argument("--max-pages", type=int, default=None)
    args = parser.parse_args()

    raw = os.path.join(args.edition_dir, "raw_extract.json")
    edition = os.path.join(args.edition_dir, "edition.json")
    with open(raw, encoding="utf-8") as f:
        extracted = json.load(f)
    with open(edition, encoding="utf-8") as f:
        ed = json.load(f)
    pdf = ed.get("pdf_path") or extracted.get("pdf_path")
    if not pdf or not os.path.exists(pdf):
        print("PDF not found")
        sys.exit(1)
    report = verify_and_write(pdf, extracted, args.edition_dir, max_pages=args.max_pages)
    print(json.dumps({"flags": report["flags"], "pages": len(report["pages"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
