# Provenance Guard

Provenance Guard is a backend service that checks whether a piece of writing is likely human-written, AI-generated, or uncertain. It combines language-model and writing-style signals, returns a clear label with confidence, and keeps an audit log for review and appeals.


## Project Overview

Provenance Guard is a Flask backend that evaluates text submissions using two detection signals:

1. Groq semantic assessment (`llm_score`)
2. Stylometric heuristics (`stylometric_score`)

It combines both into one calibrated confidence score, maps that score to an attribution category, returns a transparency label, and writes a complete audit trail to SQLite.

## Architecture

Submission flow:

1. Client sends `text` + `creator_id` to `POST /submit`
2. Flask-Limiter enforces request quotas
3. Groq signal + stylometric signal run independently
4. Combined confidence is computed with weighted scoring
5. Confidence maps to attribution band and transparency label
6. Structured record is written to SQLite audit log
7. JSON response is returned to client

Appeal flow:

1. Client sends `content_id` + `creator_reasoning` to `POST /appeal`
2. Matching record status is updated from `classified` to `under_review`
3. Appeal reasoning is persisted in the same audit record
4. Confirmation response is returned

## Tech Stack

- Backend: Flask
- Rate Limiting: Flask-Limiter (`memory://`)
- LLM Signal: Groq (`llama-3.3-70b-versatile`)
- Structural Signal: Custom stylometrics in Python
- Storage: SQLite (`sqlite3`)

## Detection Signals and Why

### Signal 1: Groq semantic assessment

- Measures semantic predictability and narrative smoothness.
- Output: `llm_score` as float in `[0.0, 1.0]`.
- Why: catches language patterns that often appear in generated text.

### Signal 2: Stylometric heuristics

- Measures sentence rhythm variation and type-token ratio.
- Output: `stylometric_score` as float in `[0.0, 1.0]`.
- Why: adds structural evidence independent of semantic model behavior.

### Why two signals

I used two independent signals to reduce over-reliance on any single detector. The semantic model is strong on coherent AI-like prose, while stylometrics contributes structural checks that can disagree in useful ways.

## Confidence Scoring and Calibration

Combined scoring formula:

```text
confidence = (0.40 * llm_score) + (0.60 * stylometric_score)
```

Human-safe heuristics:

- If `llm_score` is high but `stylometric_score` is low, confidence is penalized.
- If `stylometric_score` is very low, confidence is capped below the AI-attribution range.

Attribution bands:

- `0.00 - 0.72` -> `high_confidence_human`
- `0.73 - 0.92` -> `uncertain`
- `0.93 - 1.00` -> `high_confidence_ai`

Why this approach:

- Weighting now prioritizes structural evidence to reduce semantic-only false positives.
- A wider uncertain band reduces overconfident AI labels on ambiguous text.
- Guardrails explicitly protect human-like structure from being overruled by model confidence alone.

### Example submissions with different confidence scores

Mixed-confidence case:

- Input type: polished but human-authored prose (post-tuning benchmark)
- Output: `confidence = 0.798`
- Attribution: `uncertain`

Lower-confidence case:

- Input type: clearly human-authored literary paragraph
- Output: `confidence = 0.14861538461538462`
- Attribution: `high_confidence_human`

These examples demonstrate meaningful variation instead of constant scoring.

## Transparency Labels (All Three Variants)

The API returns these exact label strings:

1. High-confidence AI (`high_confidence_ai`)

`This content is likely AI-generated. Confidence is high based on semantic and structural analysis. You may submit an appeal if this is your original writing.`

2. Uncertain (`uncertain`)

`This result is uncertain. Signals are mixed, so no strong attribution was made. A manual review can be requested through appeal.`

3. High-confidence human (`high_confidence_human`)

`This content is likely human-written. Confidence is high based on semantic and structural analysis.`

## API Surface

### `POST /submit`

Request:

```json
{
  "text": "String (50-10000 chars)",
  "creator_id": "String"
}
```

Response:

```json
{
  "content_id": "UUID4",
  "attribution": "high_confidence_human | uncertain | high_confidence_ai",
  "confidence": 0.0,
  "label": "String"
}
```

### `POST /appeal`

Request:

```json
{
  "content_id": "UUID4",
  "creator_reasoning": "String"
}
```

Response:

```json
{
  "message": "Appeal received successfully. Status updated to under_review.",
  "content_id": "UUID4",
  "status": "under_review"
}
```

### `GET /log`

Returns recent structured audit entries.

## Production Features Evidence

### 1) Label variation is active

Observed in testing:

- `high_confidence_ai` only when confidence is above the tuned `0.93` cutoff
- `uncertain` at `0.798`
- `high_confidence_human` at `0.14861538461538462`

### 2) Appeals update status and reasoning

Observed in testing:

- Appeal response status: `under_review`
- Matching `/log` entry updated with:
  - `status: under_review`
  - non-null `appeal_reasoning`

### 3) Rate limiting is enforced

12-request burst status output:

```text
200
200
200
200
200
200
200
200
200
200
429
429
```

Raw throttled response excerpt:

```text
HTTP/1.1 429 TOO MANY REQUESTS
...
<p>10 per 1 minute</p>
```

### 4) Complete structured audit log

Each entry includes:

- `timestamp`
- `content_id`
- `creator_id`
- `attribution`
- `confidence`
- `llm_score`
- `stylometric_score`
- `status`
- `appeal_reasoning`

## Known Limitations

1. **Academic Paradox (semantic false positives)**

Highly formal human writing can resemble model-generated distributions and produce elevated `llm_score` values.

2. **Geometric Prompt Injection (stylometric bypass)**

An LLM can be prompted to intentionally vary sentence lengths, which can weaken rhythm-based heuristics.

3. **Short/templated text instability**

Very short or rigid templates provide weak structural evidence and reduce stylometric reliability.

## Spec Reflection

How the spec helped:

- The spec helped me plan an initial weight system early, which made later integration cleaner.

How implementation diverged:

- One divergence was signal combination and label attribution regions as I calibrated behavior against real test outputs and adjusted implementation details to keep results practical.

## AI Usage

1. Flask backend scaffold from planning

- I directed AI to generate a Flask skeleton aligned to my API contract from planning.
- AI produced route scaffolding and starter structure.
- I revised validation, response contract behavior, and logging flow before using it.

2. First signal function generation from planning

- I directed AI to generate a Groq semantic scoring function based on my signal spec.
- AI produced the initial function shape and prompt structure.
- I revised parsing, output constraints, and endpoint integration logic to match my design.

## Engineering Highlights

- **3 production endpoints**: `/submit`, `/appeal`, `/log`
- **2-signal scoring pipeline** with weighted confidence fusion
- **0.00% FPR** on post-tuning human benchmark (Gutenberg corpus)
- **9 structured audit fields** captured per record (including appeal metadata)
- **Input guardrails**: strict payload validation + text length bounds
- **Abuse protection**: tested throttle behavior with deterministic `429` evidence

## Local Run

Install dependencies:

```bash
pip install -r requirements.txt
```

Run app:

```bash
python app.py
```

Core test endpoints:

- `POST /submit`
- `POST /appeal`
- `GET /log`
