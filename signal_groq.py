import json
import os
import re

from dotenv import load_dotenv
from groq import Groq


load_dotenv()


def _clamp_score(value: float) -> float:
    return max(0.0, min(1.0, value))


def score_text_with_groq(text: str, model: str = "llama-3.3-70b-versatile") -> float:
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY is missing. Add it to your local .env file.")

    client = Groq(api_key=api_key)

    prompt = (
        "You are scoring how likely text appears AI-generated based on semantic predictability and narrative smoothness. "
        "Return JSON only with a single key llm_score that is a float from 0.00 to 1.00. "
        "No markdown, no extra keys."
    )

    response = client.chat.completions.create(
        model=model,
        temperature=0,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": text},
        ],
    )

    content = response.choices[0].message.content or ""

    try:
        parsed = json.loads(content)
        score = float(parsed["llm_score"])
        return _clamp_score(score)
    except Exception:
        # Fallback for model responses that include extra text around JSON.
        match = re.search(r"\"llm_score\"\s*:\s*([0-9]*\.?[0-9]+)", content)
        if not match:
            raise RuntimeError(f"Could not parse llm_score from Groq response: {content}")
        return _clamp_score(float(match.group(1)))
