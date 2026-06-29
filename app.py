import uuid
from typing import Any

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from audit_log import append_entry, get_recent_entries, init_db, mark_under_review
from scoring import attribution_from_confidence, combine_signal_scores
from signal_groq import score_text_with_groq
from signal_stylometric import score_text_with_stylometrics


load_dotenv()

app = Flask(__name__)
limiter = Limiter(
    key_func=get_remote_address,
    app=app,
    storage_uri="memory://",
)

init_db()


def validate_submit_payload(payload: Any) -> tuple[bool, str]:
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


def label_from_attribution(attribution: str) -> str:
    labels = {
        "high_confidence_ai": "This content is likely AI-generated. Confidence is high based on semantic and structural analysis. You may submit an appeal if this is your original writing.",
        "uncertain": "This result is uncertain. Signals are mixed, so no strong attribution was made. A manual review can be requested through appeal.",
        "high_confidence_human": "This content is likely human-written. Confidence is high based on semantic and structural analysis.",
    }
    return labels[attribution]


def label_from_confidence(confidence: float) -> str:
    attribution = attribution_from_confidence(confidence)
    return label_from_attribution(attribution)


def validate_appeal_payload(payload: Any) -> tuple[bool, str]:
    if not isinstance(payload, dict):
        return False, "Request body must be a JSON object."

    content_id = payload.get("content_id")
    creator_reasoning = payload.get("creator_reasoning")

    if not content_id:
        return False, "content_id is required."
    if not creator_reasoning:
        return False, "creator_reasoning is required."
    if not isinstance(content_id, str):
        return False, "content_id must be a string."
    if not isinstance(creator_reasoning, str):
        return False, "creator_reasoning must be a string."

    return True, ""


@app.post("/submit")
@limiter.limit("100 per day")
@limiter.limit("10 per minute")
def submit() -> tuple:
    payload = request.get_json(silent=True)
    is_valid, error_message = validate_submit_payload(payload)
    if not is_valid:
        return jsonify({"error": error_message}), 400

    # Type is guaranteed by validate_submit_payload.
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400

    text = payload["text"]
    creator_id = payload["creator_id"]

    llm_score = score_text_with_groq(text)
    stylometric_score = score_text_with_stylometrics(text)
    confidence = combine_signal_scores(llm_score, stylometric_score)
    attribution = attribution_from_confidence(confidence)
    label = label_from_confidence(confidence)
    content_id = str(uuid.uuid4())

    append_entry(
        content_id=content_id,
        creator_id=creator_id,
        attribution=attribution,
        confidence=confidence,
        llm_score=llm_score,
        stylometric_score=stylometric_score,
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


@app.post("/appeal")
def appeal() -> tuple:
    payload = request.get_json(silent=True)
    is_valid, error_message = validate_appeal_payload(payload)
    if not is_valid:
        return jsonify({"error": error_message}), 400

    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400

    content_id = payload["content_id"]
    creator_reasoning = payload["creator_reasoning"]

    updated = mark_under_review(
        content_id=content_id,
        creator_reasoning=creator_reasoning,
    )
    if not updated:
        return jsonify({"error": "content_id not found."}), 404

    return (
        jsonify(
            {
                "message": "Appeal received successfully. Status updated to under_review.",
                "content_id": content_id,
                "status": "under_review",
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
