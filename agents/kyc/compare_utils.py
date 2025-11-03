import re
from dataclasses import dataclass
from typing import Iterable, Optional

from rapidfuzz import fuzz

DOB_PATTERN = re.compile(r"(?:19|20)\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])")


@dataclass
class ComparisonResult:
    match_score: float
    name_score: float
    dob_score: float
    ocr_name: Optional[str]
    ocr_dob: Optional[str]


def _normalise(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _score_strings(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return fuzz.token_set_ratio(a, b) / 100.0


def _score_dates(ocr_value: str, expected: str) -> float:
    if not ocr_value or not expected:
        return 0.0
    digits_only = re.sub(r"\D", "", ocr_value)
    expected_digits = re.sub(r"\D", "", expected)
    if not digits_only or not expected_digits:
        return 0.0
    if digits_only == expected_digits:
        return 1.0
    return fuzz.partial_ratio(digits_only, expected_digits) / 100.0


def evaluate_user_data(
    ocr_lines: Iterable[str], expected_full_name: Optional[str], expected_dob: Optional[str]
) -> ComparisonResult:
    lines = [line for line in ocr_lines if line]
    normalised_name = _normalise(expected_full_name) if expected_full_name else ""

    best_name_score = 0.0
    best_name_line: Optional[str] = None
    for line in lines:
        score = _score_strings(_normalise(line), normalised_name)
        if score > best_name_score:
            best_name_score = score
            best_name_line = line

    best_dob_score = 0.0
    best_dob_value: Optional[str] = None
    for line in lines:
        for match in DOB_PATTERN.finditer(line):
            candidate = match.group(0)
            score = _score_dates(candidate, expected_dob or "")
            if score > best_dob_score:
                best_dob_score = score
                best_dob_value = candidate

    # Average the available scores; if one is missing, rely on the other
    available_scores = [score for score in (best_name_score, best_dob_score) if score > 0]
    overall = sum(available_scores) / len(available_scores) if available_scores else 0.0

    return ComparisonResult(
        match_score=overall,
        name_score=best_name_score,
        dob_score=best_dob_score,
        ocr_name=best_name_line,
        ocr_dob=best_dob_value,
    )
