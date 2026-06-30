#!/usr/bin/env python3
import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request


WIKI_API = "https://en.wikipedia.org/w/api.php"


def get_json(
    url: str,
    params: dict,
    timeout: float = 20.0,
    retries: int = 5,
    initial_backoff: float = 1.0,
) -> dict:
    query = urllib.parse.urlencode(params)
    full_url = f"{url}?{query}"
    req = urllib.request.Request(full_url, headers={"User-Agent": "ProvenanceGuardFPRExperiment/1.0"})
    backoff = initial_backoff

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            if err.code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)
                continue
            raise
        except urllib.error.URLError:
            if attempt < retries:
                time.sleep(backoff)
                backoff = min(backoff * 2.0, 30.0)
                continue
            raise

    raise RuntimeError("Unreachable retry state in get_json")


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
            status = response.getcode()
            data = json.loads(response.read().decode("utf-8"))
            return status, data
    except urllib.error.HTTPError as err:
        payload = err.read().decode("utf-8")
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            data = {"error": payload}
        return err.code, data


def fetch_random_titles_batch(batch_size: int = 10) -> list[str]:
    data = get_json(
        WIKI_API,
        {
            "action": "query",
            "format": "json",
            "list": "random",
            "rnnamespace": 0,
            "rnlimit": max(1, min(10, batch_size)),
        },
    )

    items = data.get("query", {}).get("random", [])
    titles: list[str] = []
    for item in items:
        title = item.get("title")
        if title:
            titles.append(title)
    return titles


def fetch_intro_year_for_titles(titles: list[str]) -> list[tuple[str, str, int | None]]:
    if not titles:
        return []

    data = get_json(
        WIKI_API,
        {
            "action": "query",
            "format": "json",
            "formatversion": 2,
            "redirects": 1,
            "prop": "extracts|revisions",
            "titles": "|".join(titles),
            "exintro": 1,
            "explaintext": 1,
            "rvprop": "timestamp",
            "rvdir": "newer",
            "rvlimit": 1,
        },
    )

    pages = data.get("query", {}).get("pages", [])
    out: list[tuple[str, str, int | None]] = []

    for page in pages:
        title = page.get("title") or ""
        extract = (page.get("extract") or "").strip()
        revisions = page.get("revisions") or []

        year: int | None = None
        if revisions:
            timestamp = revisions[0].get("timestamp")
            if timestamp and len(timestamp) >= 4:
                try:
                    year = int(timestamp[:4])
                except ValueError:
                    year = None

        if title and extract:
            out.append((title, extract, year))

    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure false-positive rate by submitting pre-2020 Wikipedia intros to /submit."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:5050", help="API base URL")
    parser.add_argument("--sample-size", type=int, default=100, help="Number of qualifying samples")
    parser.add_argument("--year-cutoff", type=int, default=2020, help="Keep pages created before this year")
    parser.add_argument(
        "--min-chars",
        type=int,
        default=50,
        help="Minimum intro length to satisfy /submit validation",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=400,
        help="Hard cap on batch attempts while collecting qualifying samples",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Random Wikipedia titles to fetch per API batch call (max 10).",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=0.15,
        help="Delay in seconds between Wikipedia fetch cycles to reduce throttling",
    )
    parser.add_argument(
        "--creator-prefix",
        default="fpr-wiki",
        help="Prefix used for creator_id values, useful for isolating reruns",
    )
    args = parser.parse_args()

    target = args.sample_size
    attempts = 0
    qualified = 0
    high_confidence_ai = 0
    uncertain = 0
    high_confidence_human = 0
    non_200 = 0
    seen_titles: set[str] = set()

    started = time.time()

    while qualified < target and attempts < args.max_attempts:
        attempts += 1
        try:
            titles = fetch_random_titles_batch(batch_size=args.batch_size)
            candidates = fetch_intro_year_for_titles(titles)
        except (urllib.error.HTTPError, urllib.error.URLError):
            time.sleep(args.request_delay)
            continue

        if not candidates:
            time.sleep(args.request_delay)
            continue

        for title, intro, year in candidates:
            if qualified >= target:
                break
            if title in seen_titles:
                continue
            seen_titles.add(title)

            if year is None or year >= args.year_cutoff:
                continue
            if len(intro) < args.min_chars:
                continue

            qualified += 1
            payload = {
                "text": intro,
                "creator_id": f"{args.creator_prefix}-{qualified:03d}",
            }
            status, response = post_json(f"{args.base_url}/submit", payload)

            if status != 200:
                non_200 += 1
                print(f"[{qualified:03d}/{target}] status={status} title={title}")
                continue

            attribution = response.get("attribution", "")
            if attribution == "high_confidence_ai":
                high_confidence_ai += 1
            elif attribution == "uncertain":
                uncertain += 1
            elif attribution == "high_confidence_human":
                high_confidence_human += 1

            print(
                f"[{qualified:03d}/{target}] {title} (created {year}) -> "
                f"{attribution} confidence={response.get('confidence')}"
            )

        time.sleep(args.request_delay)

    elapsed = time.time() - started
    fpr = (high_confidence_ai / qualified * 100.0) if qualified else 0.0

    print("\n=== Experiment Summary ===")
    print(f"Qualified samples submitted: {qualified}")
    print(f"Random attempts made: {attempts}")
    print(f"high_confidence_ai count (false positives): {high_confidence_ai}")
    print(f"uncertain count: {uncertain}")
    print(f"high_confidence_human count: {high_confidence_human}")
    print(f"Non-200 /submit responses: {non_200}")
    print(f"False Positive Rate: {fpr:.2f}%")
    print(f"Total runtime: {elapsed:.1f}s")

    if qualified < target:
        print("WARNING: Did not reach requested sample size before max-attempts.")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())