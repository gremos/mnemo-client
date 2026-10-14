"""Is a user prompt a correction of Claude's last move? Used by track-correction.py.

English phrasings, Greek ones (engineers wrote 94% of their judge-labelled corrections in Greek,
audit 2026-10-14), and English typed with the keyboard left on the Greek layout ("νο τηατ'σ ωρονγ").
Greek is matched without accents and with final sigma folded, since prompts are typed both ways.
"""
from __future__ import annotations

import re
import unicodedata

_FP_PATTERNS = [
    r"\bno\s+(problem|worries|issue|big deal|way)\b",
    r"\bno\s+need\b",
    r"that'?s\s+(fine|great|good|perfect|ok|okay|correct|right|exactly)\b",
    r"\bdon'?t\s+(worry|bother|hesitate|mind|sweat)\b",
    r"\b(never ?mind|no need to)\b",
]

_CORRECTION_PATTERNS = [
    r"^\s*no[.!,]?\s*$",
    r"\b(no|nope)[,.!]?\s+(that|this|you|don'?t|please|stop|more|again)\b",
    r"\bdon'?t\s+(do|say|use|write|add|include|create|make|change|remove|delete|run|call)\b",
    r"\bstop\s+(doing|using|adding|writing|saying|that|it|this)\b",
    r"\b(wrong|incorrect|that'?s not right|not correct)\b",
    r"\b(undo|revert|rollback|roll back)\b",
    r"\bthat'?s\s+(not|wrong)\b",
    r"\bactually[,\s]+(no|don'?t|use|do|instead)\b",
    r"\bi\s+(said|meant|asked for|told you|wanted)\b",
    r"\bplease\s+(stop|don'?t)\b",
    # Missed phrasings from session history
    r"\bwait[,.]?\s*(no|actually|that|hold on)\b",
    r"\bno[,.]?\s+actually\b",
    r"\bnot\s+quite\b",
    r"\b(you\s+)?(missed|forgot|skipped)\s+(the|that|this|a|to)\b",
    r"\bthat\s+(doesn'?t|didn'?t|won'?t)\s+work\b",
    r"\bthat'?s\s+(not\s+what\s+i|incomplete|not\s+right)\b",
    r"\bthat'?s\s+not\s+what\s+i\s+(meant|asked|wanted|said)\b",
]

# Greek, matched on _fold(text): lower case, accents stripped, ς -> σ.
_GR_FP_PATTERNS = [
    r"\bδεν\s+(πειραζει|πειραζ|εχει\s+σημασια)",
    r"\bοχι\s+(απαραιτητα|ακομα|ακομη)\b",
    r"\b(κανενα|κανεναν)\s+προβλημα\b",
]

# A bare "οχι" (an answer to a question) and "δεν δουλευει" (a fault report) were tried and dropped: on the
# judge-labelled pool (~/.mnemo-eval, 2026-10-14) each matched 0 corrections and 2 other prompts.
_GR_CORRECTION_PATTERNS = [
    r"\bοχι[,.!]?\s+(αυτο|αυτα|ετσι|δεν|μην|μη|ξανα|παλι|εγω|σου|θελω|ειπα|το|τα|λαθοσ)\b",
    r"\bλαθοσ\b|\bλαθη\b|\bλανθασμεν",
    r"\bδεν\s+(ειναι|ηταν)\s+(σωστ|αυτο|αυτα|ετσι|κατανοητ)",
    r"\bδεν\s+(εκανεσ|ζητησα|ειπα)\b",
    r"(?<!να )(?<!να\s)\bμην?\s+(το|τα|τον|την|τουσ|κανεισ|βαζεισ|γραφεισ|σβησεισ|σβηνεισ|αλλαξεισ|αλλαζεισ|"
    r"τρεξεισ|τρεχεισ|χρησιμοποιεισ|προσθετεισ|πειραξεισ|πειραζεισ|ξανα)\b",
    r"\bσταματ(α|ησε|ηστε)\b",
    r"\b(αναιρεσε|αναιρεστε|επαναφερε|γυρνα\s+πισω|γυρισε\s+πισω)\b",
    r"\b(σου|σασ)\s+(ειπα|εγραψα|ζητησα)\b",
    r"\b(εννοουσα|ζητησα)\b",
    r"\b(ακομα|ακομη)\s+δεν\b",
    r"\b(ξεχασεσ|παρελειψεσ|εχασεσ)\b",
    r"\bπαλι\s+(το\s+ιδιο|λαθοσ|δεν)\b",
]

# Greek keyboard layout -> the Latin key under each letter.
_LAYOUT = str.maketrans("ςερτυθιοπασδφγηξκλζχψωβνμ", "wertyuiopasdfghjklzxcvbnm")
_GREEK = re.compile(r"[\u0370-\u03ff]")


def _fold(text: str) -> str:
    nfd = unicodedata.normalize("NFD", text.lower())
    return "".join(ch for ch in nfd if unicodedata.category(ch) != "Mn").replace("ς", "σ")


def _english(text: str) -> bool:
    if any(re.search(p, text) for p in _FP_PATTERNS):
        return False
    return any(re.search(p, text) for p in _CORRECTION_PATTERNS)


def is_correction(text: str) -> bool:
    text = text.strip().lower()[:500]
    if _english(text):
        return True
    if not _GREEK.search(text):
        return False
    folded = _fold(text)
    if not any(re.search(p, folded) for p in _GR_FP_PATTERNS) and \
            any(re.search(p, folded) for p in _GR_CORRECTION_PATTERNS):
        return True
    # English typed on the Greek layout carries no accents; real Greek nearly always does.
    accentless = unicodedata.normalize("NFD", text) == text
    return accentless and _english(text.translate(_LAYOUT))
