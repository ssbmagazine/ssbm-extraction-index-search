"""Straight-through batch: PDF → extract → articles → catalog → verify → index."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

from article_builder import export_edition_archive
from extract_ssbm import extract_pdf_to_structured_text
from index_ssbm import index_archive_edition, parse_edition_info

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

MONTH_NAMES = {
    1: "jan",
    2: "feb",
    3: "mar",
    4: "apr",
    5: "may",
    6: "jun",
    7: "jul",
    8: "aug",
    9: "sep",
    10: "oct",
    11: "nov",
    12: "dec",
}


def edition_id_from_pdf(pdf_path: str) -> str:
    """Support jan2002.pdf and issues/YYYY/MM.pdf → YYYY-MM."""
    path = Path(pdf_path)
    parent = path.parent.name
    stem = path.stem
    if parent.isdigit() and len(parent) == 4 and re.fullmatch(r"\d{2}", stem):
        return f"{parent}-{stem}"
    if re.fullmatch(r"\d{4}-\d{2}", stem):
        return stem
    # legacy jan2002
    base = re.sub(r"_extracted$", "", stem, flags=re.I).lower()
    return base


def parse_year_month_from_path(pdf_path: str):
    eid = edition_id_from_pdf(pdf_path)
    m = re.fullmatch(r"(\d{4})-(\d{2})", eid)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        title = f"SSBM {MONTH_NAMES.get(month, str(month)).capitalize()} {year}"
        return title, year, month
    return parse_edition_info(pdf_path)


def discover_pdfs(pdf_dir: str) -> list[str]:
    """Flat *.pdf or YYYY/MM.pdf tree under issues/."""
    pdfs: list[str] = []
    root = Path(pdf_dir)
    if not root.exists():
        return pdfs
    # Prefer year/month layout
    year_dirs = [p for p in root.iterdir() if p.is_dir() and p.name.isdigit()]
    if year_dirs:
        for ydir in sorted(year_dirs):
            for pdf in sorted(ydir.glob("*.pdf")):
                pdfs.append(str(pdf))
        return pdfs
    for pdf in sorted(root.glob("*.pdf")):
        pdfs.append(str(pdf))
    return pdfs


def process_one(
    pdf_path: str,
    out_root: str,
    db_path: str,
    force: bool = False,
    verify: bool = True,
    verify_max_pages: int | None = None,
) -> dict:
    eid = edition_id_from_pdf(pdf_path)
    edition_dir = os.path.join(out_root, eid)
    edition_json = os.path.join(edition_dir, "edition.json")

    if os.path.exists(edition_json) and not force:
        print(f"[skip] {eid} already processed (use --force to redo)")
        index_archive_edition(edition_dir, db_path)
        return {"edition_id": eid, "status": "skipped"}

    images_dir = os.path.join(edition_dir, "images")
    os.makedirs(edition_dir, exist_ok=True)

    print(f"[extract] {pdf_path}")
    data = extract_pdf_to_structured_text(pdf_path, images_dir=images_dir)
    if not data:
        return {"edition_id": eid, "status": "extract_failed"}

    raw_path = os.path.join(edition_dir, "raw_extract.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    title, year, month = parse_year_month_from_path(pdf_path)
    print(f"[segment+catalog] {eid}")
    result = export_edition_archive(
        data,
        edition_id=eid,
        out_dir=edition_dir,
        year=year,
        month=month,
        title=title,
    )

    verify_flags = []
    if verify:
        print(f"[verify-ocr] {eid}")
        try:
            from verify_ocr import verify_and_write

            report = verify_and_write(
                pdf_path,
                data,
                edition_dir,
                max_pages=verify_max_pages,
            )
            verify_flags = report.get("flags") or []
        except Exception as exc:
            verify_flags = ["ocr_verify_error"]
            print(f"  OCR verify failed: {exc}")

    print(f"[index] {eid}")
    index_archive_edition(edition_dir, db_path)

    n_review = sum(1 for a in result["articles"] if a.get("review_flags"))
    return {
        "edition_id": eid,
        "status": "ok",
        "articles": len(result["articles"]),
        "catalog": len(result.get("catalog") or []),
        "needs_review_articles": n_review,
        "qa_flags": (data.get("qa_summary") or {}).get("flags"),
        "verify_flags": verify_flags,
    }


def verify_only(edition_dir: str, max_pages: int | None = None) -> dict:
    from verify_ocr import verify_and_write

    with open(os.path.join(edition_dir, "raw_extract.json"), encoding="utf-8") as f:
        extracted = json.load(f)
    with open(os.path.join(edition_dir, "edition.json"), encoding="utf-8") as f:
        ed = json.load(f)
    pdf = ed.get("pdf_path") or extracted.get("pdf_path")
    report = verify_and_write(pdf, extracted, edition_dir, max_pages=max_pages)
    return {"edition_id": ed.get("id"), "flags": report.get("flags"), "status": "verified"}


def main():
    default_issues = os.path.normpath(
        os.path.join(
            os.path.dirname(__file__),
            "..",
            "ssbmagazine",
            "public",
            "issues",
        )
    )
    parser = argparse.ArgumentParser(description="SSBM archive straight-through processor")
    parser.add_argument(
        "--pdf-dir",
        default=default_issues if os.path.isdir(default_issues) else ".",
        help="Directory of PDFs or issues/YYYY/MM.pdf tree",
    )
    parser.add_argument("--pdf", action="append", help="Specific PDF (repeatable)")
    parser.add_argument("--out", default="archive", help="Output archive root")
    parser.add_argument("-d", "--database", default="ssbm_archive.db")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--no-verify", action="store_true", help="Skip Tesseract OCR verify")
    parser.add_argument("--verify-only", metavar="EDITION_DIR", help="Re-run OCR verify only")
    parser.add_argument("--verify-max-pages", type=int, default=None)
    parser.add_argument(
        "--year",
        type=int,
        help="Only process this year when scanning issues tree",
    )
    args = parser.parse_args()

    if args.verify_only:
        print(verify_only(args.verify_only, max_pages=args.verify_max_pages))
        return

    pdfs: list[str] = []
    if args.pdf:
        pdfs = args.pdf
    else:
        pdfs = discover_pdfs(args.pdf_dir)
        if args.year:
            y = str(args.year)
            pdfs = [p for p in pdfs if f"{os.sep}{y}{os.sep}" in p or f"/{y}/" in p]

    if not pdfs:
        print("No PDFs found.")
        sys.exit(1)

    os.makedirs(args.out, exist_ok=True)
    summary = []
    for pdf in pdfs:
        summary.append(
            process_one(
                pdf,
                args.out,
                args.database,
                force=args.force,
                verify=not args.no_verify,
                verify_max_pages=args.verify_max_pages,
            )
        )

    report_path = os.path.join(args.out, "batch_summary.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # Aggregate verify flags
    verify_summary = {
        "editions": len(summary),
        "with_needs_review": sum(
            1 for s in summary if "needs_review" in (s.get("verify_flags") or [])
        ),
        "items": summary,
    }
    with open(os.path.join(args.out, "verify_summary.json"), "w", encoding="utf-8") as f:
        json.dump(verify_summary, f, ensure_ascii=False, indent=2)

    print("\nBatch complete:")
    for s in summary:
        print(f"  {s}")
    print(f"Wrote {report_path}")


if __name__ == "__main__":
    main()
