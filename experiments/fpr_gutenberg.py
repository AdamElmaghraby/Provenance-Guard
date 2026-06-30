#!/usr/bin/env python3
import argparse
import json
import random
import re
import time
import urllib.error
import urllib.request

import nltk
from nltk.corpus import gutenberg


def ensure_corpus() -> None:
    nltk.download("gutenberg", quiet=True)


def split_paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n", text)
    out: list[str] = []
    for part in parts:
        p = " ".join(part.split())
        if len(p) >= 50:
            out.append(p)
    return out


def sample_human_paragraphs(sample_size: int, seed: int) -> list[tuple[str, str]]:
    random.seed(seed)
    pool: list[tuple[str, str]] = []

    for fileid in gutenberg.fileids():
        raw = gutenberg.raw(fileid)
        for paragraph in split_paragraphs(raw):
            # Keep a practical upper bound similar to API validation limits.
            if len(paragraph) <= 10000:
                pool.append((fileid, paragraph))

    if len(pool) < sample_size:
        raise RuntimeError(
            f"Not enough paragraphs in corpus. requested={sample_size}, available={len(pool)}"
        )

    return random.sample(pool, sample_size)


def post_json(url: str, payload: dict, timeout: float = 60.0) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.getcode(), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {"error": raw}
        return err.code, data


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure FPR using human-authored Project Gutenberg paragraphs via NLTK."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:5051")
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--creator-prefix", default="fpr-gutenberg")
    parser.add_argument(
        "--retry-wait-seconds",
        type=float,
        default=6.2,
        help="Sleep time after 429 before retrying same sample",
    )
    parser.add_argument(
        "--max-429-retries",
        type=int,
        default=30,
        help="Maximum retries per sample after 429 responses",
    )
    parser.add_argument(
        "--inter-request-delay",
        type=float,
        default=0.0,
        help="Optional sleep between sample submissions to prevent route throttling",
    )
    args = parser.parse_args()

    started = time.time()
    ensure_corpus()
    samples = sample_human_paragraphs(args.sample_size, args.seed)

    high_confidence_ai = 0
    uncertain = 0
    high_confidence_human = 0
    non_200 = 0

    for idx, (source_file, paragraph) in enumerate(samples, start=1):
        payload = {
            "text": paragraph,
            "creator_id": f"{args.creator_prefix}-{idx:03d}",
        }
        retries = 0
        status, response = post_json(f"{args.base_url}/submit", payload)
        while status == 429 and retries < args.max_429_retries:
            retries += 1
            time.sleep(args.retry_wait_seconds)
            status, response = post_json(f"{args.base_url}/submit", payload)

        if status != 200:
            non_200 += 1
            print(
                f"[{idx:03d}/{args.sample_size}] status={status} source={source_file} retries={retries}"
            )
            continue

        attribution = response.get("attribution", "")
        if attribution == "high_confidence_ai":
            high_confidence_ai += 1
        elif attribution == "uncertain":
            uncertain += 1
        elif attribution == "high_confidence_human":
            high_confidence_human += 1

        print(
            f"[{idx:03d}/{args.sample_size}] source={source_file} -> "
            f"{attribution} confidence={response.get('confidence')}"
        )

        if args.inter_request_delay > 0:
            time.sleep(args.inter_request_delay)

    fpr = (high_confidence_ai / args.sample_size) * 100.0
    elapsed = time.time() - started

    print("\n=== Experiment Summary ===")
    print(f"Qualified samples submitted: {args.sample_size}")
    print(f"high_confidence_ai count (false positives): {high_confidence_ai}")
    print(f"uncertain count: {uncertain}")
    print(f"high_confidence_human count: {high_confidence_human}")
    print(f"Non-200 /submit responses: {non_200}")
    print(f"False Positive Rate: {fpr:.2f}%")
    print(f"Total runtime: {elapsed:.1f}s")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
