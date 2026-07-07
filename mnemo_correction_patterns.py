#!/usr/bin/env python3
"""
Shared correction-detection patterns — single source of truth for both the live
UserPromptSubmit hook (track-correction.py) and the client sweep
(mnemo-correction-sweep.py). Keeping them in one module prevents the two
detectors from drifting apart.

Bilingual by design: the XO fleet corrects Claude in Greek at least as often as
in English (measured: ~52 Greek vs ~42 English correction turns for the busiest
user). An English-only detector structurally cannot see ~half their corrections,
so Greek + Greeklish markers are first-class here.

Detection is deterministic and cheap. It is the reliable floor; server-side LLM
extraction is the language-agnostic complement for nuance the regex misses.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# False positives — phrases that look corrective but are approvals / filler.
# Checked FIRST; a match here vetoes a correction match.
# ---------------------------------------------------------------------------
_FP_PATTERNS = [
    # English
    r"\bno\s+(problem|worries|issue|big deal|way)\b",
    r"\bno\s+need\b",
    r"that'?s\s+(fine|great|good|perfect|ok|okay|correct|right|exactly)\b",
    r"\bdon'?t\s+(worry|bother|hesitate|mind|sweat)\b",
    r"\b(never ?mind|no need to)\b",
    # Greek approvals / filler
    r"\bδεν\s+πειράζει\b",          # "no worries"
    r"\bμια\s+χαρά\b",              # "just fine"
    r"\b(εντάξει|οκ|οκέι)\b",       # "ok"
    r"\b(σωστά|τέλεια|ωραία|μπράβο)\b",  # "correct / perfect / nice / well done"
    r"\bόχι\s+(πρόβλημα|θέμα)\b",   # "no problem"
    r"\bκαμία\s+ανάγκη\b",          # "no need"
]

# ---------------------------------------------------------------------------
# Correction markers — English + Greek + Greeklish.
# ---------------------------------------------------------------------------
_CORRECTION_PATTERNS = [
    # --- English ---
    r"^\s*no[.!,]?\s*$",
    r"\b(no|nope)[,.!]?\s+(that|this|you|don'?t|please|stop|more|again)\b",
    r"\bdon'?t\s+(do|say|use|write|add|include|create|make|change|remove|delete|run|call|edit|touch|commit|push)\b",
    r"\bstop\s+(doing|using|adding|writing|saying|that|it|this)\b",
    r"\b(wrong|incorrect|that'?s not right|not correct)\b",
    r"\b(undo|revert|rollback|roll back)\b",
    r"\bthat'?s\s+(not|wrong)\b",
    r"\bactually[,\s]+(no|don'?t|use|do|instead)\b",
    r"\bi\s+(said|meant|asked for|told you|wanted)\b",
    r"\bplease\s+(stop|don'?t)\b",
    r"\bwait[,.]?\s*(no|actually|that|hold on)\b",
    r"\bno[,.]?\s+actually\b",
    r"\bnot\s+quite\b",
    r"\b(you\s+)?(missed|forgot|skipped)\s+(the|that|this|a|to)\b",
    r"\bthat\s+(doesn'?t|didn'?t|won'?t)\s+work\b",
    r"\bthat'?s\s+(not\s+what\s+i|incomplete|not\s+right)\b",
    # --- Greek ---
    r"^\s*όχι\b",                                   # leading "no"
    r"\bόχι[,.!]?\s+(αυτό|έτσι|εκεί|τώρα|δεν|μην|θέλω|είναι|το)\b",
    r"\bλάθος\b",                                   # "wrong / mistake"
    r"\bμην\b\s+\S+",                               # "don't <verb>"
    r"\bμη\s+(κάνεις|βάλεις|τρέξεις|γράψεις|χρησιμοποιείς|αλλάξεις|σβήσεις|διαγράψεις|προσθέσεις|αγγίξεις)\b",
    r"\bσταμάτα\b|\bσταμάτησε\b",                   # "stop"
    r"\bδεν\s+(είναι\s+σωστό|είναι\s+αυτό|δουλεύει|λειτουργεί|θέλω|το\s+θέλω|χρειάζεται|πρέπει|ισχύει)\b",
    r"\bξανα(κάν|τσεκάρ|δές|δοκίμ|έλεγξ|δε\b)",     # "re-do / re-check / look again"
    r"\bδιόρθωσ(ε|έ|ου)?\b",                        # "correct it"
    r"\bανακάλεσ|\bκάνε\s+undo\b",                  # "undo / revert"
    r"\bόχι\s+έτσι\b",                              # "not like that"
    # --- Greeklish (Latin-script Greek) ---
    r"^\s*oxi\b|\boxi\s+(afto|etsi|den|min|thelo)\b",
    r"\blathos\b",
    r"\bstamata\b",
    r"\bden\s+(einai|douleuei|leitourgei|thelo|paizei)\b",
    r"\bmin\s+\S+",
]

_FP_RE = [re.compile(p, re.IGNORECASE) for p in _FP_PATTERNS]
_CORR_RE = [re.compile(p, re.IGNORECASE) for p in _CORRECTION_PATTERNS]


def is_correction(text: str) -> bool:
    """True if the user turn is a correction (EN/GR/Greeklish), not an approval."""
    t = (text or "").strip().lower()[:500]
    if not t:
        return False
    if any(p.search(t) for p in _FP_RE):
        return False
    return any(p.search(t) for p in _CORR_RE)
