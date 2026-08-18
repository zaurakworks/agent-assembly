import hashlib
import json
from types import SimpleNamespace

__version__ = "0.2.0"

_calls = 0


def token_usage():
    return {
        "calls": _calls,
        "input_tokens": _calls * 100,
        "cached_input_tokens": 0,
        "uncached_input_tokens": _calls * 100,
        "output_tokens": _calls * 10,
        "reasoning_tokens": 0,
        "cache_hit_rate": 0.0,
    }


def select(problem, candidates, *, criteria, cache, **kwargs):
    global _calls
    if kwargs.get("model") == "missing-dependency":
        raise ModuleNotFoundError(
            "No module named 'google.genai'", name="google.genai")
    identity = hashlib.sha256(json.dumps(
        {"problem": problem, "candidates": candidates, "criteria": criteria},
        ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    cached_identity = None
    try:
        with open(cache, encoding="utf-8") as cache_file:
            cached_identity = json.load(cache_file).get("identity")
    except FileNotFoundError:
        pass
    if cached_identity != identity:
        _calls += 2
        with open(cache, "w", encoding="utf-8") as cache_file:
            json.dump({"identity": identity}, cache_file)
    order = sorted(
        range(len(candidates)),
        key=lambda index: ("EXPECTED_PASS" not in candidates[index], index),
    )
    scores = [0.5] * len(candidates)
    for index, candidate in enumerate(candidates):
        if "EXPECTED_PASS" in candidate:
            scores[index] = 1.0
        elif "EXPECTED_REJECT" in candidate:
            scores[index] = 0.0
    return SimpleNamespace(
        index=order[0], best=candidates[order[0]], scores=scores,
        ranking=order, n_comparisons=2,
        criteria=[criterion["id"] for criterion in criteria],
    )
