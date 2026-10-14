#!/usr/bin/env python3
"""Score correction_detect.is_correction against the judge-labelled correction turns in ~/.mnemo-eval
(the Mnemo replay pool, laptop only). Prints pooled counts only, never prompt text: engineers' data.

  python3 scripts/eval_corrections.py [PLUGIN_DIR]

Recall is against every turn the judge says steered Claude, a wider set than explicit "no, wrong"
messages, so compare detector versions with it rather than reading it as an absolute.
"""
import glob, json, os, re, sys, collections
GR = re.compile(r"[Ͱ-Ͽἀ-῿]")
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from correction_detect import is_correction  # noqa: E402


c = collections.Counter()
for lf in glob.glob(os.path.expanduser("~/.mnemo-eval/*/labels/*.json")):
    lab = json.load(open(lf)); sf = lf.replace("/labels/", "/sessions/")
    if not os.path.exists(sf): continue
    turns = json.load(open(sf))["turns"]
    who = "gremos" if "gremos" in lab["profile"] else "eng"
    pos = {x["turn"] for x in lab["corrections"]}
    for i, t in enumerate(turns):
        if t.get("role") != "human": 
            if i in pos: c[who, "label_on_nonhuman"] += 1
            continue
        txt = (t.get("text") or "").strip()
        if not txt or txt.startswith("<"): continue
        lang = "gr" if GR.search(txt) else "en"
        y = i in pos; p = is_correction(txt)
        c[who, lang, "TP" if y and p else "FN" if y else "FP" if p else "TN"] += 1
for who in ("eng", "gremos"):
    for lang in ("en", "gr"):
        tp, fn, fp, tn = (c[who, lang, k] for k in ("TP", "FN", "FP", "TN"))
        print(f"{who:6} {lang}: labelled={tp+fn:4} caught={tp:3} recall={tp/max(tp+fn,1):.2f}  false_alarms={fp:3} of {fp+tn:5} unlabelled  precision={tp/max(tp+fp,1):.2f}")
print("labels on non-human turns:", c["eng","label_on_nonhuman"], c["gremos","label_on_nonhuman"])
