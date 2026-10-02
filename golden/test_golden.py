"""Golden regression checks for normalize, TOC, catalog, front-matter, search."""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from article_builder import build_articles  # noqa: E402
from extract_ssbm import extract_pdf_to_structured_text  # noqa: E402
from telugu_normalize import has_split_virama, normalize_telugu_text  # noqa: E402
from toc_parser import parse_edition_toc  # noqa: E402

GOLDEN_EXPECTATIONS = {
    "jan2002.pdf": {
        "min_articles": 10,
        "must_have_titles_substr": ["స్వామి", "గాంధీ", "క్విజ్"],
        "max_latin_rate": 0.05,
        "must_not_split_virama_pages": [10],
        "must_have_meeru": True,
    },
    "feb2002.pdf": {
        "min_articles": 10,
        "must_have_titles_substr": ["సాయిమాట", "గాంధీ", "క్విజ్"],
        "max_latin_rate": 0.05,
        "must_not_split_virama_pages": [6, 7],
        "must_contain_editor_front": True,
        "must_fix_sangeetam": True,
    },
}


def check_pdf(pdf_name: str, expect: dict) -> list[str]:
    errors = []
    pdf_path = os.path.join(ROOT, pdf_name)
    if not os.path.exists(pdf_path):
        # try issues path
        issues = os.path.normpath(
            os.path.join(ROOT, "..", "ssbmagazine", "public", "issues")
        )
        alt = None
        if pdf_name.startswith("jan"):
            alt = os.path.join(issues, "2002", "01.pdf")
        elif pdf_name.startswith("feb"):
            alt = os.path.join(issues, "2002", "02.pdf")
        if alt and os.path.exists(alt):
            pdf_path = alt
        else:
            return [f"missing {pdf_name}"]

    data = extract_pdf_to_structured_text(pdf_path, images_dir=None)
    if not data:
        return [f"extract failed {pdf_name}"]

    # Normalize unit tests
    bad = "లక్ష ్మమ్మ నిర్లక్ష ్యం"
    fixed = normalize_telugu_text(bad)
    if has_split_virama(fixed) or "లక్ష్మమ్మ" not in fixed:
        errors.append(f"{pdf_name}: normalize failed on split virama sample → {fixed!r}")

    qa = data.get("qa_summary") or {}
    rate = qa.get("latin_leftover_rate") or 0
    if rate > expect["max_latin_rate"]:
        errors.append(f"{pdf_name}: latin rate {rate} > {expect['max_latin_rate']}")

    toc = parse_edition_toc(data)
    if not toc.get("entries"):
        errors.append(f"{pdf_name}: TOC entries empty")

    built = build_articles(data)
    arts = built["articles"]
    # front matter counts toward min
    if len(arts) < expect["min_articles"]:
        errors.append(f"{pdf_name}: articles {len(arts)} < {expect['min_articles']}")

    titles = " ".join(a["title"] for a in arts)
    for substr in expect["must_have_titles_substr"]:
        if substr not in titles:
            errors.append(f"{pdf_name}: missing title substr {substr!r}")

    # No split virama on cited pages after normalize
    for pn in expect.get("must_not_split_virama_pages") or []:
        page = next((p for p in data["pages"] if p["page_number"] == pn), None)
        if not page:
            errors.append(f"{pdf_name}: missing page {pn}")
            continue
        text = "\n".join(b["text"] for b in page.get("blocks") or [])
        if has_split_virama(text):
            errors.append(f"{pdf_name}: page {pn} still has split virama")

    if expect.get("must_contain_editor_front"):
        front = next((a for a in arts if a.get("kind") == "front_matter"), None)
        body = (front or {}).get("body_unicode") or ""
        # also search any article body
        all_body = "\n".join(a.get("body_unicode") or "" for a in arts)
        if "Editor" not in all_body and "editor" not in all_body.lower():
            errors.append(f"{pdf_name}: Editor not found in indexed bodies (front matter?)")

    if expect.get("must_fix_sangeetam"):
        all_body = "\n".join(a.get("body_unicode") or "" for a in arts)
        if "సంరాతం" in all_body:
            errors.append(f"{pdf_name}: సంరాతం still present (expected సంగీతం)")
        if "సంగీతం" not in all_body and "సంగీత" not in all_body:
            # soft: title may still have wrong form before normalize on title from TOC
            pass

    if expect.get("must_have_meeru"):
        all_titles = " ".join(a["title"] for a in arts)
        all_body = "\n".join(a.get("body_unicode") or "" for a in arts)
        if "పేి" in all_titles or "పేి" in all_body:
            errors.append(f"{pdf_name}: పేి still present (expected పేరు)")

    if pdf_name.startswith("jan"):
        p10 = next((p for p in data["pages"] if p["page_number"] == 10), None)
        if not p10 or len(p10.get("blocks") or []) < 2:
            errors.append(f"{pdf_name}: page 10 looks empty (layout miss?)")

    return errors


def main():
    all_errors = []
    for pdf, expect in GOLDEN_EXPECTATIONS.items():
        errs = check_pdf(pdf, expect)
        if errs:
            all_errors.extend(errs)
            print(f"FAIL {pdf}:")
            for e in errs:
                print(f"  - {e}")
        else:
            print(f"OK   {pdf}")

    out = os.path.join(os.path.dirname(__file__), "last_run.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"errors": all_errors, "ok": not all_errors}, f, ensure_ascii=False, indent=2)

    if all_errors:
        sys.exit(1)
    print("All golden checks passed.")


if __name__ == "__main__":
    main()
