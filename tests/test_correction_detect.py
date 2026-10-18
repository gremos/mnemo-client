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
    "νοτ ;θιτε",                                                              # "not quite" (; is the q key)
])
def test_corrections_detected(text):
    assert is_correction(text), text


@pytest.mark.parametrize("text", [
    "proceed", "check progress", "looks good, thanks", "no problem", "that's right",
    "προψεεδ", "ψηεψκ προγρεσσ", "στατθσ", "/μοδελ",                          # English on the Greek layout, no correction
    "συνδέσου στον gpml01 και δες τα αρχεία", "όχι απαραίτητα, όπως θέλεις", "δεν πειράζει",
    "σωστό, συνέχισε", "τέλεια", "για να μην χαθούν τα δεδομένα κράτα backup", "ωστε να μην το κανεις",
    "add also εγγραφές χωρίς ΑΦΜ", "ποιος είναι ο αριθμός των κομμωτηρίων",
    "ο server δεν απαντάει από χθες, έλεγξε το nginx",                       # a fault report, not a correction of Claude
    "το vpn δεν δουλεύει από το πρωί", "όχι",                                 # dropped patterns (see correction_detect)
])
def test_non_corrections_ignored(text):
    assert not is_correction(text), text


def test_writing_style_feedback_is_a_correction():
    """101, 2026-10-14: a legal-notice register correction was never captured, so Greek-writing corrections had no trend."""
    from correction_detect import is_correction
    real = ("«Το μήνυμα αποστέλλεται μία φορά» → «Στέλνουμε αυτό το μήνυμα μία φορά». they doesn reflect the "
            "communication style for the specific web seatch what is the correcy tone in greek communication")
    assert is_correction(real)
    assert is_correction("this doesn't read like Greek, it reads translated")
    assert is_correction("Δεν ακούγεται φυσικό, είναι μεταφρασμένο")
    assert not is_correction("make the tone match the brand guide")
