"""Helpers for experiment/device id filter syntax."""

from __future__ import annotations

import re
from typing import List, Tuple


ID_SPEC_SEPARATORS = (",", ";", "-", "\uFF0C", "\uFF1B", "\uFF0D", "\u2013", "\u2014", "\u2212")
ID_SPEC_TRANSLATION = str.maketrans({
    "\uFF0C": ",",
    "\uFF1B": ",",
    ";": ",",
    "\uFF0D": "-",
    "\u2013": "-",
    "\u2014": "-",
    "\u2212": "-",
})


def looks_like_id_spec(value: str) -> bool:
    if not value:
        return False
    value = value.strip()
    if not re.search(r"\d", value):
        return False
    return any(ch in value for ch in ID_SPEC_SEPARATORS)


def parse_exp_id_spec(spec: str) -> Tuple[List[int], List[Tuple[int, int]]]:
    if not spec:
        return [], []

    spec = spec.strip().translate(ID_SPEC_TRANSLATION)
    spec = re.sub(r"\s+", "", spec)

    singles: List[int] = []
    ranges: List[Tuple[int, int]] = []
    for part in [p for p in spec.split(",") if p]:
        if "-" in part:
            a, b = part.split("-", 1)
            if not a or not b:
                continue
            try:
                start = int(a)
                end = int(b)
            except ValueError:
                continue
            if start > end:
                start, end = end, start
            ranges.append((start, end))
        else:
            try:
                singles.append(int(part))
            except ValueError:
                continue

    singles = sorted(set(singles))
    ranges.sort()
    return singles, ranges


def in_spec(val: int, singles_set: set, ranges: List[Tuple[int, int]]) -> bool:
    if val in singles_set:
        return True
    for start, end in ranges:
        if start <= val <= end:
            return True
    return False
