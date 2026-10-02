"""Telugu post-decode normalization and known mapping repairs."""
from __future__ import annotations

import re
import unicodedata

# Space (or ZWSP) between consonant and following virama —e.g. లక్ష ్మమ్మ
_SPLIT_VIRAMA = re.compile(
    r"([క-హౘ-ౚ])[ \u00a0\u200b\u200c\u200d]+(్[క-హౘ-ౚ])"
)
# Orphan space before combining matra
_SPLIT_MATRA = re.compile(
    r"([క-హౘ-ౚ](?:్[క-హౘ-ౚ])*)[ \u00a0\u200b]+([ా-ౄె-ౌౕౖఁ-ః])"
)

# Recurring decode misses → corrected forms (extend from OCR verify queue)
_WORD_FIXES = [
    (re.compile(r"సంరాతం"), "సంగీతం"),
    (re.compile(r"సంరాతాన్ని"), "సంగీతాన్ని"),
    (re.compile(r"సంరాతాన్ని"), "సంగీతాన్ని"),
    (re.compile(r"సంరాత"), "సంగీత"),
    (re.compile(r"మీ పేి"), "మీ పేరు"),
    (re.compile(r"పేి"), "పేరు"),
]


def normalize_telugu_text(text: str) -> str:
    if not text:
        return text
    out = unicodedata.normalize("NFC", text)
    # Iterate until stable — conjuncts can chain
    for _ in range(5):
        nxt = _SPLIT_VIRAMA.sub(r"\1\2", out)
        nxt = _SPLIT_MATRA.sub(r"\1\2", nxt)
        if nxt == out:
            break
        out = nxt
    for pat, repl in _WORD_FIXES:
        out = pat.sub(repl, out)
    return out


def has_split_virama(text: str) -> bool:
    return bool(_SPLIT_VIRAMA.search(text or ""))
