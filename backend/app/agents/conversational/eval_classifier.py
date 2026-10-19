import argparse
import json
import time
from collections import Counter
from pathlib import Path

from app.agents.conversational.classifier import classify
from app.agents.conversational.llm import get_llm_client

CACHE = Path(".eval_cache/classifier.json")


def load_cache() -> dict:
    return json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}


def save_cache(cache: dict) -> None:
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache, indent=1), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="tests/agents/conversational/data/classifier_set.json")
    parser.add_argument("--pause", type=float, default=7.0)
    parser.add_argument("--fresh", action="store_true")
    args = parser.parse_args()

    items = json.loads(Path(args.data).read_text(encoding="utf-8"))
    cache = {} if args.fresh else load_cache()
    llm = get_llm_client()

    stopped = False
    for n, item in enumerate(items, start=1):
        q = item["q"]
        if q in cache:
            print(f"{n}/{len(items)} cached   {cache[q]['label']:9} {q[:60]}")
            continue
        result = classify(q, llm)
        if result.source == "fallback":
            print(f"\nSTOPPED at {n}/{len(items)}: LLM call failed (likely quota). Progress saved. Rerun later.")
            stopped = True
            break
        cache[q] = {"label": result.label.value, "source": result.source}
        save_cache(cache)
        print(f"{n}/{len(items)} {result.source:8} {result.label.value:9} {q[:60]}")
        if result.source == "llm":
            time.sleep(args.pause)

    confusion: Counter = Counter()
    sources: Counter = Counter()
    misses = []
    for item in items:
        got = cache.get(item["q"])
        if not got:
            continue
        confusion[(item["label"], got["label"])] += 1
        sources[got["source"]] += 1
        if got["label"] != item["label"]:
            misses.append((item["label"], got["label"], got["source"], item["q"]))

    done = sum(confusion.values())
    if done == 0:
        print("No results yet.")
        return
    correct = sum(v for (t, p), v in confusion.items() if t == p)
    advise_total = sum(v for (t, _), v in confusion.items() if t == "advise")
    explain_total = sum(v for (t, _), v in confusion.items() if t == "explain")
    unsafe = confusion[("advise", "explain")]
    over_blocked = confusion[("explain", "advise")]

    print(f"\n=== RESULTS ({done}/{len(items)} evaluated{' - INCOMPLETE' if done < len(items) else ''}) ===")
    print(f"accuracy: {correct}/{done} = {correct / done:.1%}")
    if advise_total:
        print(f"UNSAFE (advice answered as explain): {unsafe}/{advise_total} = {unsafe / advise_total:.1%}   target < 5%")
    if explain_total:
        print(f"over-blocked (explain sent to lawyer): {over_blocked}/{explain_total} = {over_blocked / explain_total:.1%}")
    print(f"advice sent to off_topic (refused, safe): {confusion[('advise', 'off_topic')]}")
    print(f"decided by: {dict(sources)}")
    if misses:
        print("\nMISSES (true, predicted, source, question):")
        for m in misses:
            print(" ", m)


if __name__ == "__main__":
    main()