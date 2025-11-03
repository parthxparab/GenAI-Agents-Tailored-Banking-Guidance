import os
from functools import lru_cache
from typing import Dict, List, Sequence

import easyocr

DEFAULT_LANGUAGES: Sequence[str] = ("en",)


@lru_cache(maxsize=8)
def _get_reader(languages: Sequence[str]) -> easyocr.Reader:
    """Initialise and cache EasyOCR readers per language tuple."""
    return easyocr.Reader(list(languages), gpu=False)


def extract_text(file_path: str, languages: Sequence[str] | None = None) -> Dict[str, List[str] | str]:
    """
    Run OCR on the provided image file and return recognised lines.

    Returns a dictionary with:
        lines: list of recognised text strings in reading order
        text: single string concatenation of all recognised lines
    """
    if not file_path:
        raise ValueError("file_path must be provided for OCR processing")

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"OCR input file does not exist: {file_path}")

    languages = tuple(languages or DEFAULT_LANGUAGES)
    reader = _get_reader(languages)
    lines = reader.readtext(file_path, detail=0)
    text = "\n".join(lines)
    return {"lines": lines, "text": text}
