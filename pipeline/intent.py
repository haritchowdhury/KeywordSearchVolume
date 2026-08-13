"""Commercial-intent scoring and informational filtering."""
from __future__ import annotations

import re
from typing import List

from .config import Config

# Base intent strength by DataForSEO main_intent label.
INTENT_BASE = {
    "transactional": 1.0,
    "commercial": 0.85,
    "navigational": 0.30,
    "informational": 0.05,
}


def _contains_any(text: str, terms: List[str]) -> bool:
    low = text.lower()
    return any(re.search(rf"\b{re.escape(t)}\b", low) for t in terms)


def commercial_intent_score(keyword: str, main_intent: str | None,
                            config: Config) -> float:
    """Return a 0..1 commercial-intent score blending API intent with
    configurable text modifiers."""
    base = INTENT_BASE.get((main_intent or "").lower(), 0.2)
    score = base
    mods = list(config.intent.commercial_modifiers or [])
    if mods and _contains_any(keyword, mods):
        score = min(1.0, score + 0.10)
    info = list(config.intent.informational_modifiers or [])
    if info and _contains_any(keyword, info):
        score = max(0.0, score - 0.40)
    return max(0.0, min(1.0, score))


def is_informational(keyword: str, main_intent: str | None,
                     config: Config) -> bool:
    """A keyword is considered irrelevant/informational if its main_intent is
    informational, or it strongly matches an informational modifier."""
    info_labels = set(config.intent.informational_labels or [])
    if (main_intent or "").lower() in info_labels:
        return True
    info_mods = list(config.intent.informational_modifiers or [])
    return bool(info_mods) and _contains_any(keyword, info_mods)
