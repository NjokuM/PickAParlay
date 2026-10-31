"""
Player-name matching across sources (odds feed, NBA stats, ESPN injuries).

They disagree on accents (Jokić/Jokic), punctuation (C.J./CJ), suffixes
(Derrick Jones/Derrick Jones Jr.) and short forms (Herb/Herbert Jones).
Loose fuzzy matching is not safe here: it matched "Shai Gilgeous-Alexander"
to an injured "Trey Alexander" and rookie "Cameron Boozer" to retired
Carlos Boozer.
"""
from __future__ import annotations

import re
import unicodedata

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def norm_name(name: str) -> str:
    """Lowercase, no accents/punctuation/generational suffix: "Derrick Jones Jr." → "derrick jones"."""
    name = unicodedata.normalize("NFKD", name or "")
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = re.sub(r"[.'’]", "", name.lower())
    parts = name.replace("-", " ").split()
    while len(parts) > 2 and parts[-1] in _SUFFIXES:
        parts.pop()
    return " ".join(parts)


def same_player(a: str, b: str) -> bool:
    """Exact after normalising, or a short first name ("herb jones" ~ "herbert jones")."""
    a, b = norm_name(a), norm_name(b)
    if a == b:
        return True
    ta, tb = a.split(), b.split()
    if len(ta) != len(tb) or len(ta) < 2 or ta[1:] != tb[1:]:
        return False
    fa, fb = ta[0], tb[0]
    return min(len(fa), len(fb)) >= 3 and (fa.startswith(fb) or fb.startswith(fa))
