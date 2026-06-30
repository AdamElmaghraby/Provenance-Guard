def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def combine_signal_scores(llm_score: float, stylometric_score: float) -> float:
    """
    FPR-optimized weighting:
    confidence = (0.40 * llm_score) + (0.60 * stylometric_score)

    Human-safe heuristics:
    - If LLM is high but stylometric score is low, apply a confidence penalty.
    - If stylometric score is very low, cap confidence below AI attribution range.
    """
    llm = _clamp(llm_score)
    style = _clamp(stylometric_score)
    confidence = (0.40 * llm) + (0.60 * style)

    # Penalize disagreement where semantic model is high but structure is human-like.
    if llm >= 0.75 and style <= 0.30 and (llm - style) >= 0.40:
        confidence -= 0.20

    # Very low stylometric AI-likeness should never become high-confidence AI.
    if style <= 0.18:
        confidence = min(confidence, 0.74)

    return _clamp(confidence)


def attribution_from_confidence(confidence: float) -> str:
    """
    FPR-optimized threshold mapping:
    - 0.00 to 0.72 => high_confidence_human
    - 0.73 to 0.92 => uncertain
    - 0.93 to 1.00 => high_confidence_ai
    """
    score = _clamp(confidence)

    if score <= 0.72:
        return "high_confidence_human"
    if score <= 0.92:
        return "uncertain"
    return "high_confidence_ai"
