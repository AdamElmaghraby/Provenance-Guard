def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def combine_signal_scores(llm_score: float, stylometric_score: float) -> float:
    """
    Locked M4 weighting from planning.md:
    confidence = (0.70 * llm_score) + (0.30 * stylometric_score)
    """
    llm = _clamp(llm_score)
    style = _clamp(stylometric_score)
    return _clamp((0.70 * llm) + (0.30 * style))


def attribution_from_confidence(confidence: float) -> str:
    """
    Locked threshold mapping from planning.md:
    - 0.00 to 0.60 => high_confidence_human
    - 0.61 to 0.80 => uncertain
    - 0.81 to 1.00 => high_confidence_ai
    """
    score = _clamp(confidence)

    if score <= 0.60:
        return "high_confidence_human"
    if score <= 0.80:
        return "uncertain"
    return "high_confidence_ai"
