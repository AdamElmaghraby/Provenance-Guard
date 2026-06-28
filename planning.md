# Provenance Guard Planning Spec

## 1. Detection Signals

### Signal 1: Groq LLM Semantic Assessment (`llama-3.3-70b-versatile`)

- What it measures: semantic coherence, narrative flow, and token-level predictability as a proxy for how closely text resembles LLM-generated prose.
- Output format: `llm_score` as a float in the range `0.00` to `1.00`.
- Why it is useful: AI systems generally produce statistically probable token sequences; human writing more often includes idiosyncratic, emotionally driven, or structurally surprising choices.
- Known blindspot: The Academic Paradox. Formal human writing such as legal briefs, academic papers, or technical documentation can look AI-like and trigger false positives.

### Signal 2: Python Stylometric Heuristics

- What it measures: structural variation using sentence length variance and type-token ratio.
- Output format: `stylometric_score` as a float in the range `0.00` to `1.00`.
- Why it is useful: human writing tends to be bursty, while AI output often trends toward smoother sentence rhythm and more uniform vocabulary density.
- Known blindspot: Geometric Prompt Injection. A user can prompt an LLM to alternate sentence lengths or otherwise inject artificial variance to defeat purely statistical heuristics.

### Signal Combination

- Inputs: `llm_score` and `stylometric_score`, each normalized to `0.00` to `1.00`.
- Combined confidence: `confidence = (0.70 * llm_score) + (0.30 * stylometric_score)`.
- Rationale: semantic signal is primary, stylometrics is corroborating. This supports the project goal of reducing false accusations on a creative-writing platform.

## 2. Uncertainty Representation

- System meaning of a score of `0.60`: upper boundary of likely human output. It is still classified as human, but it is near the uncertainty band.
- Calibration approach:
  1. Normalize each raw signal to `0.00` to `1.00`.
  2. Apply weighted combination to produce one confidence score.
  3. Map confidence to a closed attribution enum.
- Strict attribution enum rules:
  1. `high_confidence_human` maps to `0.00` to `0.60`
  2. `uncertain` maps to `0.61` to `0.80`
  3. `high_confidence_ai` maps to `0.81` to `1.00`
- Threshold policy: asymmetric by design. The uncertain zone is intentionally wide to reduce catastrophic false positives against real human creators.

## 3. Transparency Label Design

The API returns one of these exact label strings:

1. High-confidence AI (`high_confidence_ai`):
   `This content is likely AI-generated. Confidence is high based on semantic and structural analysis. You may submit an appeal if this is your original writing.`
2. High-confidence human (`high_confidence_human`):
   `This content is likely human-written. Confidence is high based on semantic and structural analysis.`
3. Uncertain (`uncertain`):
   `This result is uncertain. Signals are mixed, so no strong attribution was made. A manual review can be requested through appeal.`

## 4. Appeals Workflow

- Who can submit an appeal: the creator associated with the submitted content (`creator_id`) after receiving an attribution result.
- Endpoint and input:
  - Route: `POST /appeal`
  - Payload:

```json
{
  "content_id": "UUID4 String",
  "creator_reasoning": "String"
}
```

- System behavior on appeal receipt:
  1. Validate `content_id` exists.
  2. Update `status` from `classified` to `under_review`.
  3. Append and persist `creator_reasoning`.
  4. Return confirmation payload with `status: under_review`.
- Audit logging requirements:
  - Preserve original classification fields (`llm_score`, `stylometric_score`, `confidence`, `attribution`, label, timestamp).
  - Add appeal metadata (`creator_reasoning`, status transition, appeal timestamp).
- Human reviewer queue view:
  - `content_id`, `creator_id`, submission timestamp, attribution, confidence, both raw signal scores, current status, and creator appeal text.

## 5. Anticipated Edge Cases

1. Academic Paradox case:
   A human author submits polished formal prose with strict punctuation, high lexical diversity, and low error rate. The semantic model can over-score this as AI-like.
2. Geometric Prompt Injection case:
   An LLM-generated story is explicitly prompted to alternate sentence lengths and vary diction to spoof burstiness, inflating stylometric human-likeness.
3. Poetry and lyric-style repetition:
   A human poem with heavy repetition and deliberately simple vocabulary may look statistically uniform and can be misread as AI-generated.
4. Short or highly templated content near minimum length:
   Very short submissions or rigid templates provide weak signal diversity and can produce unstable confidence in either direction.

## Architecture

The submission flow starts at `POST /submit`, where the rate limiter checks quota before the text enters the two-signal pipeline. Groq provides the semantic assessment signal and the stylometric engine provides the structural signal, and the calibration layer combines them into one attribution decision. The appeal flow starts at `POST /appeal`, where the backend verifies the content record, moves it to `under_review`, stores the creator's reasoning, and leaves a full audit trail for human review.

```text
========================================================================================
               SUBMISSION FLOW (POST /submit)
========================================================================================

 [ Client ]
  |  (raw text, creator_id)
  v
+---------------------------+
|   Flask Rate Limiter      |--(Quotas Exceeded)--> [ 429 Too Many Requests ]
+---------------------------+
  |  (cleared payload)
  v
+--------------------------------------------------------------------------------------+
|  Multi-Signal Detection Pipeline                                                     |
|   |-> [ Groq LLM Service ]  -----------(Semantic Score: 0.0-1.0)--------+            |
|   '--> [ Stylometrics Engine ] -------(Structural Score: 0.0-1.0)--------+--+        |
+-------------------------------------------------------------------------+--+----------+
                                |  |
  +--------------------------------------------------------------------+  |
  | +--------------------------------------------------------------------+
  v v
+--------------------------------------------------------------------------------------+
|  Confidence and Calibration Engine                                                   |
|  Apply Asymmetric Weighting Formula --> Calculate Combined Confidence Score (0.0-1.0)|
+--------------------------------------------------------------------------------------+
  |  (Combined Score)
  +------------------------------+------------------------------+
  v                              v                              v
[ Score 0.00 - 0.60 ]          [ Score 0.61 - 0.80 ]          [ Score 0.81 - 1.00 ]
  |                              |                              |
  v                              v                              v
Verdict: high_confidence_human Verdict: uncertain             Verdict: high_confidence_ai
  |                              |                              |
  +------------------------------+------------------------------+
               | (Attribution Verdict)
               v
         +------------------------------+
         | Transparency Label Generator | --> [ Generate Plain-Text Badge ]
         +------------------------------+
               | (Verdict + Label + Metadata)
               v
         +------------------------------+
         |     SQLite Audit Logger      | --> [ Write DB Record: classified ]
         +------------------------------+
               |
               v
            [ Return 200 OK JSON ]


========================================================================================
              APPEAL FLOW (POST /appeal)
========================================================================================

 [ Client ] --(content_id, creator_reasoning)--> +------------------------------+
                      |      POST /appeal Endpoint    |
                      +------------------------------+
                            |
                            v
                      +------------------------------+
                      |   Query SQLite Audit Log     |
                      +------------------------------+
                            |
                  (Content Found)    |
                            v
                      +------------------------------+
                      | Update Record Status:        |
                      | 'classified' -> 'under_review'|
                      | Append: creator_reasoning    |
                      +------------------------------+
                            |
                            v
                      [ Return 200 OK JSON ]
```

## AI Tool Plan

### M3: Submission endpoint + first signal

- Spec sections provided: `## 1. Detection Signals`, `## 2. Uncertainty Representation`, and `## Architecture`.
- Ask the AI tool to generate: the Flask app skeleton plus the first signal function for Groq semantic assessment.
- Verify by: running the first signal directly on a few text samples before wiring it into the endpoint, then confirming the score direction looks sensible.

### M4: Second signal + confidence scoring

- Spec sections provided: `## 1. Detection Signals`, `## 2. Uncertainty Representation`, and `## Architecture`.
- Ask the AI tool to generate: the second signal function plus the scoring and calibration logic that combines both signals.
- Verify by: checking that scores vary meaningfully between clearly AI-like text and clearly human-like text, then confirming the combined score lands in the correct threshold band.

### M5: Production layer

- Spec sections provided: `## 3. Transparency Label Design`, `## 4. Appeals Workflow`, and `## Architecture`.
- Ask the AI tool to generate: label generation logic plus the `POST /appeal` endpoint.
- Verify by: testing that all three label variants are reachable and that an appeal updates status correctly from `classified` to `under_review`.

## Appendix A: API Surface Contract

### 1. Content Submission Endpoint

- Route: `POST /submit`
- Headers: `Content-Type: application/json`
- Rate limit: `10 per minute; 100 per day`
- Request payload:

```json
{
  "text": "String (min 50 chars, max 10,000 chars)",
  "creator_id": "String"
}
```

- Success response (`200 OK`):

```json
{
  "content_id": "UUID4 String",
  "attribution": "high_confidence_human | uncertain | high_confidence_ai",
  "confidence": "Float (0.00 - 1.00)",
  "label": "String"
}
```

- Error responses: `400 Bad Request` (missing keys), `429 Too Many Requests` (rate limit exceeded).

### 2. Appeals Workflow Endpoint

- Route: `POST /appeal`
- Headers: `Content-Type: application/json`
- Request payload:

```json
{
  "content_id": "UUID4 String",
  "creator_reasoning": "String"
}
```

- Success response (`200 OK`):

```json
{
  "message": "Appeal received successfully. Status updated to under_review.",
  "content_id": "UUID4 String",
  "status": "under_review"
}
```

- Error responses: `404 Not Found` (invalid `content_id`), `400 Bad Request`.

### 3. Audit Log Inspection Endpoint

- Route: `GET /log`
- Description: returns structured historical records for grading verification.
- Success response (`200 OK`):

```json
{
  "entries": [
    {
      "content_id": "UUID4 String",
      "creator_id": "String",
      "timestamp": "ISO-8601 String",
      "attribution": "String",
      "confidence": "Float",
      "llm_score": "Float",
      "stylometric_score": "Float",
      "status": "classified | under_review",
      "appeal_reasoning": "String | null"
    }
  ]
}
```