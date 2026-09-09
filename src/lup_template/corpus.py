"""This repository's corpus types: the library's defaults, with its own words.

`lup.corpus` declares no grade vocabulary, because what a grade is called and
what one is worth is a project's question. This module is one project's
answer, and the shape every adopting project takes: subclass the default type,
narrow the word. The six here come from the mathematics repository whose
failures shaped the design, where senders wrote them on every claim unprompted
and carefully — including an explicit negative: *"[M] No loop was found at
small size. I have not run this search; the statement is that no such search
exists in this project's record."*

Six is not a recommendation. The split between kernel-checked and merely
native is a mathematics fact this library has no business owning, and a
project without a proof assistant has no use for either word.
"""

import lup.corpus.models as corpus
from pydantic import BaseModel, field_validator


class Grade(BaseModel, frozen=True):
    """One word a claim may carry, and what a reader should make of it."""

    name: str
    meaning: str


# lup: ignore[constant-declaration] — a vocabulary this repository defines
# for itself, replaced whole by an adopting project rather than tuned
GRADES = [
    Grade(name="literature", meaning="stated in a cited source, not checked here"),
    Grade(name="measured", meaning="observed by running something in this record"),
    Grade(name="argued", meaning="reasoned in prose, with no check behind it"),
    Grade(name="conjecture", meaning="believed, and offered as a target"),
    Grade(name="lean", meaning="kernel-checked, with the certificate attached"),
    Grade(name="mine", meaning="the sender's own, unchecked by anybody else"),
]


class Claim(corpus.Claim, frozen=True):
    """The library's claim, graded in this repository's six words or not at all.

    A validator over the list rather than a narrower type, so the words and
    their meanings are one table: what a rendering explains a grade as is what
    a record is checked against, and adding a seventh is one row.
    """

    @field_validator("grade")
    @classmethod
    def graded_in_our_words(cls, spelling: str) -> str:
        """Refuse a word outside the vocabulary; an empty grade is honest."""
        if spelling and spelling not in {grade.name for grade in GRADES}:
            names = ", ".join(grade.name for grade in GRADES)
            raise ValueError(f"{spelling!r} is not one of {names}")
        return spelling
