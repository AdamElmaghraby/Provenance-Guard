import math
import re
from typing import Any


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _split_sentences(text: str) -> list[str]:
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    return sentences


def _tokenize_words(text: str) -> list[str]:
    # Keep apostrophes so contractions count as one word.
    return re.findall(r"[A-Za-z0-9']+", text.lower())


def score_text_with_stylometrics(text: str) -> float:
    """
    Returns stylometric_score as a float in [0.0, 1.0].
    Higher score means more AI-like structural uniformity.
    """
    metrics = compute_stylometric_metrics(text)

    # Map coefficient of variation into an AI-likeness band.
    # CV near/below 0.20 is highly uniform, CV near/above 0.65 is highly variable.
    rhythm_uniformity_ai = _clamp((0.65 - metrics["sentence_length_cv"]) / 0.45)

    # Higher lexical repetition can indicate generic, templated phrasing.
    # TTR is often inflated on short texts, so keep this a weaker contribution.
    lexical_repetition_ai = _clamp((0.95 - metrics["type_token_ratio"]) / 0.30)

    base_score = (0.80 * rhythm_uniformity_ai) + (0.20 * lexical_repetition_ai)

    # Two-sentence samples are unreliable for rhythm metrics and over-trigger false positives.
    if metrics["sentence_count"] <= 2:
        base_score = base_score - 0.25

    return _clamp(base_score)


def compute_stylometric_metrics(text: str) -> dict[str, Any]:
    """
    Helpful for debugging and calibration.
    - sentence_length_variance
    - sentence_length_std
    - sentence_length_cv
    - type_token_ratio
    """
    sentences = _split_sentences(text)
    words = _tokenize_words(text)

    if not sentences or not words:
        return {
            "sentence_count": len(sentences),
            "word_count": len(words),
            "sentence_length_variance": 0.0,
            "sentence_length_std": 0.0,
            "sentence_length_cv": 0.0,
            "type_token_ratio": 0.0,
        }

    sentence_lengths = [len(_tokenize_words(sentence)) for sentence in sentences]
    mean_len = sum(sentence_lengths) / len(sentence_lengths)
    variance = sum((x - mean_len) ** 2 for x in sentence_lengths) / len(sentence_lengths)
    std = math.sqrt(variance)
    cv = std / mean_len if mean_len > 0 else 0.0

    unique_words = len(set(words))
    ttr = unique_words / len(words)

    return {
        "sentence_count": len(sentences),
        "word_count": len(words),
        "sentence_length_variance": variance,
        "sentence_length_std": std,
        "sentence_length_cv": cv,
        "type_token_ratio": ttr,
    }
