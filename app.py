import uuid

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from audit_log import append_entry, get_recent_entries, init_db
from signal_groq import score_text_with_groq


load_dotenv()

app = Flask(__name__)
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    storage_uri="memory://",
)

init_db()


def validate_submit_payload(payload: dict) -> tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "Request body must be a JSON object."

    text = payload.get("text")
    creator_id = payload.get("creator_id")

    if not text:
        return False, "text is required."
    if not creator_id:
        return False, "creator_id is required."
    if not isinstance(text, str):
        return False, "text must be a string."
    if not isinstance(creator_id, str):
        return False, "creator_id must be a string."

    text_len = len(text)
    if text_len < 50:
        return False, "text must be at least 50 characters."
    if text_len > 10000:
        return False, "text must be at most 10000 characters."

    return True, ""


def temporary_attribution(score: float) -> str:
    if score >= 0.81:
        return "high_confidence_ai"
    if score >= 0.61:
        return "uncertain"
    return "high_confidence_human"


def temporary_label(attribution: str) -> str:
    labels = {
        "high_confidence_ai": "Provisional result: likely AI-generated (M3 single-signal mode).",
        "uncertain": "Provisional result: uncertain attribution (M3 single-signal mode).",
        "high_confidence_human": "Provisional result: likely human-written (M3 single-signal mode).",
    }
    return labels[attribution]


@app.post("/submit")
@limiter.limit("100 per day")
@limiter.limit("10 per minute")
def submit() -> tuple:
    payload = request.get_json(silent=True)
    is_valid, error_message = validate_submit_payload(payload)
    if not is_valid:
        return jsonify({"error": error_message}), 400

    text = payload["text"]
    creator_id = payload["creator_id"]

    llm_score = score_text_with_groq(text)
    confidence = llm_score
    attribution = temporary_attribution(confidence)
    label = temporary_label(attribution)
    content_id = str(uuid.uuid4())

    append_entry(
        content_id=content_id,
        creator_id=creator_id,
        attribution=attribution,
        confidence=confidence,
        llm_score=llm_score,
        status="classified",
    )

    return (
        jsonify(
            {
                "content_id": content_id,
                "attribution": attribution,
                "confidence": confidence,
                "label": label,
            }
        ),
        200,
    )


@app.get("/log")
def get_log() -> tuple:
    entries = get_recent_entries(limit=50)
    return jsonify({"entries": entries}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
