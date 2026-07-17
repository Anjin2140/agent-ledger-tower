#!/usr/bin/env python3
"""Deterministic structural audit for read-only model responses.

This module does not decide whether prose is factually true. It checks whether
a response obeys the evidence contract that makes human review possible:

* clearly separate Evidence, Inference, and Unknown;
* cite at least one supplied source when sources were supplied; and
* never claim that this read-only chat executed an action.

The caller records the verdict with the response hash. A flagged response is
shown to the operator; it is not silently upgraded into trusted evidence.
"""
from __future__ import annotations

import re
from typing import Any, Sequence


CONTRACT_VERSION = "response-quality-v1"
_SECTION_RE = re.compile(r"(?im)^\s*(evidence|inference|unknown)\s*:\s*")
_ACTION_CLAIM_RE = re.compile(
    r"\b(?:i|we)\s+(?:have\s+)?(?:wrote|created|saved|sent|executed|deleted|ran|changed|called|accessed)\b",
    re.IGNORECASE,
)
_UNKNOWN_RE = re.compile(r"\b(?:unknown|insufficient|not\s+enough\s+(?:evidence|information)|cannot\s+determine)\b", re.IGNORECASE)


def audit_response(text: str, supplied_citations: Sequence[str]) -> dict[str, Any]:
    """Return a deterministic review verdict for a model response.

    A passing verdict means the response is *reviewable*, not correct. The
    supplied citations are exact identifiers created by the local memory index.
    """
    text = text if isinstance(text, str) else ""
    citations = [item for item in supplied_citations if isinstance(item, str) and item]
    headings = {match.group(1).lower() for match in _SECTION_RE.finditer(text)}
    flags: list[str] = []

    missing_sections = [name for name in ("evidence", "inference", "unknown") if name not in headings]
    if missing_sections:
        flags.append("missing_sections:" + ",".join(missing_sections))

    cited = [citation for citation in citations if citation in text]
    if citations and not cited:
        flags.append("no_supplied_citation_used")
    if not citations and not _UNKNOWN_RE.search(text):
        flags.append("no_sources_without_explicit_unknown")
    if _ACTION_CLAIM_RE.search(text):
        flags.append("action_claim_in_read_only_chat")

    return {
        "contract": CONTRACT_VERSION,
        "verdict": "pass" if not flags else "flagged",
        "flags": flags,
        "supplied_citation_count": len(citations),
        "used_citation_count": len(cited),
        "sections": {name: name in headings for name in ("evidence", "inference", "unknown")},
    }
