#!/usr/bin/env python3
import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request


WIKI_API = "https://en.wikipedia.org/w/api.php"


def get_json(url: str, params: dict, timeout: float = 25.0, retries: int = 6) -> dict:
    full_url = f"{url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(
        full_url,
        headers={
            "User-Agent": "ProvenanceGuardFPRExperiment/1.0",
            "Api-User-Agent": "ProvenanceGuardFPRExperiment/1.0",
        },
    )

    backoff = 1.0
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            if err.code in (429, 500, 502, 503, 504) and attempt < retries:
                retry_after = err.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    time.sleep(float(retry_after))
                else:
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

    raise RuntimeError("Unreachable retry state")


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


def fetch_featured_titles(max_titles: int = 300) -> list[str]:
    titles: list[str] = []
    cmcontinue: str | None = None

    while len(titles) < max_titles:
        params = {
            "action": "query",
            "format": "json",
            "list": "categorymembers",
            "cmtitle": "Category:Featured_articles",
            "cmnamespace": 0,
            "cmlimit": 500,
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue

        data = get_json(WIKI_API, params)
        members = data.get("query", {}).get("categorymembers", [])
        for member in members:
            title = member.get("title")
            if title:
                titles.append(title)
                if len(titles) >= max_titles:
                    break

        cmcontinue = data.get("continue", {}).get("cmcontinue")
        if not cmcontinue:
            break

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

    out: list[tuple[str, str, int | None]] = []
    pages = data.get("query", {}).get("pages", [])
    for page in pages:
        title = page.get("title") or ""
        extract = (page.get("extract") or "").strip()
        revisions = page.get("revisions") or []

        year: int | None = None
        if revisions:
            ts = revisions[0].get("timestamp")
            if ts and len(ts) >= 4:
                try:
                    year = int(ts[:4])
                except ValueError:
                    year = None

        if title and extract:
            out.append((title, extract, year))

    return out


def chunks(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Measure FPR using pre-2020 Wikipedia Featured Article intros."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:5051")
    parser.add_argument("--sample-size", type=int, default=100)
    parser.add_argument("--title-pool", type=int, default=800)
    parser.add_argument("--chunk-size", type=int, default=20)
    parser.add_argument("--year-cutoff", type=int, default=2020)
    parser.add_argument("--min-chars", type=int, default=50)
    parser.add_argument("--creator-prefix", default="fpr-featured")
    args = parser.parse_args()

    started = time.time()
    high_confidence_ai = 0
    uncertain = 0
    high_confidence_human = 0
    non_200 = 0
    qualified = 0

    titles = fetch_featured_titles(max_titles=args.title_pool)
    seen: set[str] = set()

    for batch in chunks(titles, args.chunk_size):
        if qualified >= args.sample_size:
            break

        try:
            candidates = fetch_intro_year_for_titles(batch)
        except (urllib.error.HTTPError, urllib.error.URLError):
            continue

        for title, intro, year in candidates:
            if qualified >= args.sample_size:
                break
            if title in seen:
                continue
            seen.add(title)

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
                print(f"[{qualified:03d}/{args.sample_size}] status={status} title={title}")
                continue

            attribution = response.get("attribution", "")
            if attribution == "high_confidence_ai":
                high_confidence_ai += 1
            elif attribution == "uncertain":
                uncertain += 1
            elif attribution == "high_confidence_human":
                high_confidence_human += 1

            print(
                f"[{qualified:03d}/{args.sample_size}] {title} (created {year}) -> "
                f"{attribution} confidence={response.get('confidence')}"
            )

    elapsed = time.time() - started
    fpr = (high_confidence_ai / qualified * 100.0) if qualified else 0.0

    print("\n=== Experiment Summary ===")
    print(f"Qualified samples submitted: {qualified}")
    print(f"high_confidence_ai count (false positives): {high_confidence_ai}")
    print(f"uncertain count: {uncertain}")
    print(f"high_confidence_human count: {high_confidence_human}")
    print(f"Non-200 /submit responses: {non_200}")
    print(f"False Positive Rate: {fpr:.2f}%")
    print(f"Total runtime: {elapsed:.1f}s")

    if qualified < args.sample_size:
        print("WARNING: Not enough qualifying samples from current title pool.")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
