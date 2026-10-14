"""Correction detection (track-correction.py). 2026-10-14: engineers write 94% of their judge-labelled
corrections in Greek and the English-only regex caught none of them."""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from correction_detect import is_correction  # noqa: E402


@pytest.mark.parametrize("text", [
    "no, that's wrong", "stop doing that", "don't use sudo here",            # English (unchanged)
    "όχι, λάθος", "οχι δεν θελω αυτο", "λάθος, ξανά", "λαθος αρχειο",
    "μην το κάνεις αυτό", "μη το σβήσεις", "δεν είναι σωστό", "δεν ειναι αυτο που ζητησα",
    "ακόμα δεν λειτουργεί", "σταμάτα", "σταματα να γραφεις", "αναίρεσε το",
    "γύρνα πίσω την αλλαγή", "σου είπα να μην το πειράξεις", "εννοούσα το άλλο αρχείο",
    "ξέχασες το README", "πάλι το ίδιο λάθος",
    "νο τηατ'σ ωρονγ",                                                       # "no that's wrong" on the Greek layout
    "δον'τ δο τηατ",                                                          # "don't do that"
])
def test_corrections_detected(text):
    assert is_correction(text), text


@pytest.mark.parametrize("text", [
    "proceed", "check progress", "looks good, thanks", "no problem", "that's right",
    "προψεεδ", "ψηεψκ προγρεσσ", "στατθσ", "/μοδελ",                          # English on the Greek layout, no correction
    "συνδέσου στον gpml01 και δες τα αρχεία", "όχι απαραίτητα, όπως θέλεις", "δεν πειράζει",
    "σωστό, συνέχισε", "τέλεια", "για να μην χαθούν τα δεδομένα κράτα backup",
    "add also εγγραφές χωρίς ΑΦΜ", "ποιος είναι ο αριθμός των κομμωτηρίων",
    "ο server δεν απαντάει από χθες, έλεγξε το nginx",                       # a fault report, not a correction of Claude
    "το vpn δεν δουλεύει από το πρωί", "όχι",                                 # dropped patterns (see correction_detect)
])
def test_non_corrections_ignored(text):
    assert not is_correction(text), text
