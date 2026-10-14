#!/usr/bin/env python3
"""Score correction_detect against the judge-labelled correction turns in ~/.mnemo-eval (the Mnemo
replay pool, laptop only). Prints pooled counts only, never prompt text: the pool holds engineers' data.

  python3 scripts/eval_corrections.py [PLUGIN_DIR]

Recall is against every turn the judge says steered Claude, a wider set than explicit "no, wrong"
messages, so compare detector versions with it rather than reading it as an absolute.
"""
from __future__ import annotations

import collections
import glob
import json
import os
import re
import sys
import unicodedata

PLUGIN_DIR = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, PLUGIN_DIR)
import correction_detect as cd  # noqa: E402

POOL = os.path.expanduser("~/.mnemo-eval/*/labels/*.json")


def _turns():
    """Yield (who, text, labelled) for every human turn in the pool."""
    for label_file in glob.glob(POOL):
        session_file = label_file.replace("/labels/", "/sessions/")
        if not os.path.exists(session_file):
            continue
        with open(label_file) as f:
            label = json.load(f)
        with open(session_file) as f:
            turns = json.load(f)["turns"]
        who = "gremos" if "gremos" in label["profile"] else "eng"
        labelled = {c["turn"] for c in label["corrections"]}
        for i, turn in enumerate(turns):
            text = (turn.get("text") or "").strip()
            if turn.get("role") == "human" and text and not text.startswith("<"):
                yield who, text, i in labelled


def _rules(text: str) -> list[str]:
    """Names of the Greek rules a prompt trips (fp-guard wins, as in is_correction)."""
    text = text.lower()[:500]
    if not cd._GREEK.search(text):
        return []
    folded = cd._fold(text)
    if any(re.search(p, folded) for p in cd._GR_FP_PATTERNS):
        return ["fp-guard"]
    hits = [f"gr{k}" for k, p in enumerate(cd._GR_CORRECTION_PATTERNS) if re.search(p, folded)]
    if unicodedata.normalize("NFD", text) == text and cd._english(text.translate(cd._LAYOUT)):
        hits.append("layout")
    return hits


def main() -> None:
    totals, rules = collections.Counter(), collections.Counter()
    for who, text, labelled in _turns():
        lang = "gr" if cd._GREEK.search(text.lower()) else "en"
        caught = cd.is_correction(text)
        totals[who, lang, ("TP" if caught else "FN") if labelled else ("FP" if caught else "TN")] += 1
        for rule in _rules(text):
            rules[rule, labelled] += 1
    for who in ("eng", "gremos"):
        for lang in ("en", "gr"):
            tp, fn, fp, tn = (totals[who, lang, k] for k in ("TP", "FN", "FP", "TN"))
            print(f"{who:6} {lang}: labelled={tp + fn:4} caught={tp:3} recall={tp / max(tp + fn, 1):.2f}  "
                  f"other_hits={fp:3} of {fp + tn:5}  precision={tp / max(tp + fp, 1):.2f}")
    print("per Greek rule (labelled / other):")
    names = ["fp-guard", "layout"] + [f"gr{k}" for k in range(len(cd._GR_CORRECTION_PATTERNS))]
    for name in names:
        if rules[name, True] or rules[name, False]:
            print(f"  {name:9} {rules[name, True]:3} / {rules[name, False]:3}")


if __name__ == "__main__":
    main()
