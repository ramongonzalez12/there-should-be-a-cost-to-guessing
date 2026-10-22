"""Predeclared GPQA replication targets and an environment-validity gate.

The treatment experiment is downstream of this gate.  A model is not declared
replicated because its percentage "looks close": the observed correct count
must fall inside an approximate central 95% binomial diagnostic implied by the
published score, and the persisted request configuration must match the target.
The diagnostic does not model AA's question-level clustering across repeats.
"""

from __future__ import annotations

import json
import math

from .contracts import PARITY_CONTRACTS
from .datasets import BENCHMARKS
from .prompts import build_messages, messages_sha256
from .store import db

# Scores are Artificial Analysis' current GPQA Diamond pass@1 results.  Their
# protocol uses all 198 items and five repeats (990 trials), a published
# zero-shot prompt, temperature 0.6 for reasoning models unless the lab forbids
# it, and the maximum model-specific output allowance.  The first four pages
# expose an explicit effort level.  Qwen exposes a reasoning variant but not a
# public effort control, so omission of the reasoning field is intentional.
PARITY_TARGETS = {
    # Prospective Cohort B amendment, frozen 2026-08-16 before any calls. The
    # five rows deliberately cross lab, distribution, reasoning-control, and
    # expected behavior axes instead of adding five near-substitutes.
    "moonshotai/kimi-k3": {
        "label": "Kimi K3 (max)",
        "score": 0.935353535353535,
        "reasoning": "max",
        # Moonshot's first-party OpenRouter endpoint does not advertise the
        # temperature parameter, so AA's usual 0.6 is omitted rather than sent
        # to a provider that may silently ignore it.
        "temperature": None,
        # The endpoint publishes a 1,048,576-token context window but no
        # separate completion cap. Leave prompt headroom while retaining AA's
        # maximum-allowance intent.
        "max_tokens": 1000000,
        "min_timeout_s": 900,
        "provider": "moonshotai",
        "provider_name": "Moonshot AI",
        "planned_items": 198,
        "source": "https://artificialanalysis.ai/models/kimi-k3",
    },
    "qwen/qwen3.8-2.4t-a95b": {
        "label": "Qwen3.8 2.4T A95B (default reasoning)",
        "score": 0.935353535353535,
        # OpenRouter currently reports mandatory xhigh as the first-party
        # model default. Omission preserves AA's unqualified/default variant.
        "reasoning": "default",
        "temperature": 0.6,
        "max_tokens": 131072,
        "min_timeout_s": 900,
        "provider": "alibaba",
        "provider_name": "Alibaba",
        "planned_items": 198,
        "source": "https://artificialanalysis.ai/models/qwen3-8-2-4t-a95b",
    },
    "minimax/minimax-m3": {
        "label": "MiniMax M3 (default reasoning)",
        "score": 0.929292929292929,
        "reasoning": "default",
        # MiniMax documents 1.0 as the model's recommended/default sampling
        # temperature, which supersedes AA's generic 0.6 reasoning default.
        "temperature": 1.0,
        "max_tokens": 512000,
        "min_timeout_s": 900,
        "provider": "minimax",
        "provider_name": "Minimax",
        "planned_items": 198,
        "source": "https://artificialanalysis.ai/models/minimax-m3",
    },
    "meta/muse-spark-1.2": {
        "label": "Muse Spark 1.2 (xhigh)",
        "score": 0.904040404040404,
        "reasoning": "xhigh",
        "temperature": 0.6,
        # Meta's first-party route publishes the same 1,048,576-token context
        # window and no separate completion cap. Keep prompt headroom.
        "max_tokens": 1000000,
        "min_timeout_s": 900,
        "provider": "meta",
        "provider_name": "Meta",
        "planned_items": 198,
        "source": "https://artificialanalysis.ai/models/muse-spark-1-2",
    },
    "anthropic/claude-haiku-4.5": {
        "label": "Claude Haiku 4.5 (reasoning, OpenRouter ceiling)",
        "score": 0.671717171717172,
        # Anthropic's launch benchmarks used 128K thinking for most tasks, but
        # OpenRouter exposes a 64K total output cap for Haiku 4.5. A 63K budget
        # is the closest valid request because max_tokens must be larger than
        # the reasoning budget. This anchors to AA's independent score.
        "reasoning": {"max_tokens": 63000},
        "temperature": None,
        "max_tokens": 64000,
        "min_timeout_s": 900,
        "provider": "anthropic",
        "provider_name": "Anthropic",
        "planned_items": 198,
        "source": "https://artificialanalysis.ai/models/claude-4-5-haiku-reasoning",
    },
    "openai/gpt-5.6-terra": {
        "label": "GPT-5.6 Terra (max)",
        "score": 0.925252525252525,
        "reasoning": "max",
        "temperature": None,
        "max_tokens": 128000,
        "min_timeout_s": 600,
        "provider": "openai",
        "planned_items": 198,
        "source": "https://artificialanalysis.ai/models/gpt-5-6-terra",
    },
    "openai/gpt-5.6-luna": {
        "label": "GPT-5.6 Luna (max)",
        "score": 0.911111111111111,
        "reasoning": "max",
        "temperature": None,
        "max_tokens": 128000,
        "min_timeout_s": 300,
        "provider": "openai",
        "planned_items": 198,
        "source": "https://artificialanalysis.ai/models/gpt-5-6-luna",
    },
    "anthropic/claude-sonnet-5": {
        "label": "Claude Sonnet 5 (adaptive, max)",
        "score": 0.911111111111111,
        "reasoning": "max",
        "temperature": None,
        "max_tokens": 128000,
        "min_timeout_s": 900,
        "provider": "anthropic",
        # A full pass is about $72 at AA's measured token use.  Forty items
        # still give a useful environment check while keeping the whole gate
        # under the user's $50 cap.
        "planned_items": 40,
        "source": "https://artificialanalysis.ai/models/claude-sonnet-5",
    },
    "deepseek/deepseek-v4-pro-0813": {
        "label": "DeepSeek V4 Pro 0813 (max)",
        "score": 0.928282828282828,
        "reasoning": "max",
        "temperature": 0.6,
        "max_tokens": 384000,
        "min_timeout_s": 900,
        "provider": "deepseek",
        "planned_items": 198,
        "source": "https://artificialanalysis.ai/models/deepseek-v4-pro",
    },
    "qwen/qwen3.6-plus": {
        "label": "Qwen3.6 Plus (reasoning)",
        "score": 0.881818181818182,
        "reasoning": "default",
        "temperature": 0.6,
        "max_tokens": 65536,
        "min_timeout_s": 600,
        "provider": "alibaba",
        "planned_items": 198,
        "source": "https://artificialanalysis.ai/models/qwen3-6-plus",
    },
    "mistralai/mistral-small-2603": {
        "label": "Mistral Small 4 (reasoning)",
        "score": 0.768686868686869,
        "reasoning": "high",
        "temperature": 0.6,
        "max_tokens": 65536,
        "min_timeout_s": 600,
        "provider": "mistral",
        "planned_items": 198,
        "source": "https://artificialanalysis.ai/models/mistral-small-4",
    },
    "google/gemini-3.6-flash": {
        "label": "Gemini 3.6 Flash (high)",
        "score": 0.928282828282828,
        "reasoning": "high",
        "temperature": 0.6,
        "max_tokens": 65536,
        "min_timeout_s": 600,
        "provider": "google-ai-studio",
        # OpenRouter's request slug and returned display name intentionally
        # differ for this first-party route.
        "provider_name": "Google AI Studio",
        # The 40-item preflight was clean and inexpensive, so the replication
        # gate uses all 198 items rather than treating a wide pilot interval as
        # equivalent to Artificial Analysis' full-benchmark result.
        "planned_items": 198,
        "source": "https://artificialanalysis.ai/models/gemini-3-6-flash",
    },
}


def _prediction_interval(n: int, p: float, alpha: float = 0.05) -> tuple[int, int]:
    """Central binomial prediction interval for a future n-item replication."""
    if n <= 0:
        return 0, 0
    probabilities = [math.comb(n, k) * p ** k * (1 - p) ** (n - k)
                     for k in range(n + 1)]
    lower_tail = alpha / 2
    cumulative = 0.0
    lower = 0
    for k, probability in enumerate(probabilities):
        cumulative += probability
        if cumulative >= lower_tail:
            lower = k
            break
    cumulative = 0.0
    upper = n
    for k in range(n, -1, -1):
        cumulative += probabilities[k]
        if cumulative >= lower_tail:
            upper = k
            break
    return lower, upper


def _config_errors(request_json: str | None, target: dict,
                   expected_model: str | None = None) -> list[str]:
    try:
        request = json.loads(request_json or "{}")
    except json.JSONDecodeError:
        return ["request metadata unreadable"]
    errors = []
    if expected_model is not None and request.get("model") != expected_model:
        errors.append("requested model")
    if request.get("max_tokens") != target["max_tokens"]:
        errors.append("max_tokens")
    # Runs created before timeout persistence used the runner's 300-second
    # default.  Preserve that truthful default rather than rewriting metadata.
    if request.get("client_timeout_s", 300) < target["min_timeout_s"]:
        errors.append("client timeout")
    expected_temperature = target["temperature"]
    if expected_temperature is None:
        if "temperature" in request:
            errors.append("temperature should be omitted")
    elif request.get("temperature") != expected_temperature:
        errors.append("temperature")
    expected_reasoning = target["reasoning"]
    reasoning = request.get("reasoning")
    if isinstance(expected_reasoning, dict):
        if reasoning != expected_reasoning:
            errors.append("reasoning configuration")
    elif expected_reasoning == "default":
        if reasoning is not None:
            errors.append("reasoning should use model default")
    elif not isinstance(reasoning, dict) or reasoning.get("effort") != expected_reasoning:
        errors.append("reasoning effort")
    provider = request.get("provider") or {}
    if provider.get("only") != [target["provider"]] or provider.get("allow_fallbacks") is not False:
        errors.append("provider pin")
    if provider.get("require_parameters") is not True:
        errors.append("parameter enforcement")
    return errors


def parity_rows(db_path: str | None = None) -> list[dict]:
    """Return one audit row per predeclared model without mutating the DB."""
    con = db(db_path)
    out = []
    for model, target in PARITY_TARGETS.items():
        rows = con.execute(
            "SELECT a.item_id, a.verdict, a.error, a.parse_failure, "
            "m.request_json, m.provider, a.question, a.reference FROM answers a "
            "LEFT JOIN call_meta m ON m.key=a.key "
            "WHERE a.benchmark='gpqa_parity' AND a.contract='standard' "
            "AND a.model=?",
            (model,),
        ).fetchall()
        n = len(rows)
        correct = sum(row[1] == "CORRECT" for row in rows)
        errors = sum(row[2] is not None for row in rows)
        ungraded = sum(row[1] is None and row[2] is None for row in rows)
        parse_failures = sum(bool(row[3]) for row in rows)
        config_errors = sorted({error for row in rows for error in
                                _config_errors(row[4], target, model)})
        expected_provider_name = target.get("provider_name", target["provider"])
        wrong_provider = sum(
            not provider or provider.lower() != expected_provider_name.lower()
            for provider in (row[5] for row in rows))
        provenance_rows = con.execute(
            "SELECT a.error, m.upstream_model, m.reasoning_tokens FROM answers a "
            "LEFT JOIN call_meta m ON m.key=a.key "
            "WHERE a.benchmark='gpqa_parity' AND a.contract='standard' "
            "AND a.model=?",
            (model,),
        ).fetchall()
        wrong_upstream_model = sum(
            not upstream_model or upstream_model != model
            for _, upstream_model, _ in provenance_rows)
        missing_reasoning = sum(
            error is None and not (reasoning_tokens or 0) > 0
            for error, _, reasoning_tokens in provenance_rows)
        successful_calls = n - errors
        reasoning_unverifiable = bool(
            successful_calls and missing_reasoning == successful_calls)
        expected_items = {
            item["item_id"]: item
            for item in BENCHMARKS["gpqa_parity"](target["planned_items"])
        }
        expected_item_ids = set(expected_items)
        observed_item_ids = {row[0] for row in rows}
        # Incomplete runs may be a subset of the predeclared cohort. Extra
        # items, duplicates, or a complete set that does not match exactly are
        # invalid because they can silently combine two different pilots.
        item_set_mismatch = bool(observed_item_ids - expected_item_ids)
        item_set_mismatch = item_set_mismatch or n != len(observed_item_ids)
        if n >= target["planned_items"]:
            item_set_mismatch = item_set_mismatch or observed_item_ids != expected_item_ids
        item_snapshot_mismatch = sum(
            item_id in expected_items and (
                question != expected_items[item_id]["question"]
                or reference != expected_items[item_id]["reference"])
            for item_id, *_, question, reference in rows)
        prompt_provenance_missing = 0
        prompt_mismatch = 0
        for row in rows:
            item = expected_items.get(row[0])
            if item is None:
                continue
            try:
                request = json.loads(row[4] or "{}")
            except json.JSONDecodeError:
                continue  # Already represented by config_errors.
            sent_messages = request.get("messages")
            sent_hash = request.get("messages_sha256")
            if sent_messages is None or sent_hash is None:
                prompt_provenance_missing += 1
                continue
            expected_messages = build_messages(item, PARITY_CONTRACTS["standard"])
            if (sent_messages != expected_messages
                    or sent_hash != messages_sha256(sent_messages)
                    or sent_hash != messages_sha256(expected_messages)):
                prompt_mismatch += 1
        low, high = _prediction_interval(n, target["score"])
        # A malformed model response is an incorrect pass@1 outcome, not an API
        # failure and never an abstention.  It invalidates an arm only above the
        # experiment's predeclared 5% format-failure threshold.  Requiring
        # literally zero would selectively retry hard items that exhaust the
        # published maximum output allowance and inflate the replicated score.
        excessive_parse_failures = bool(n and parse_failures / n > 0.05)
        if not n:
            status = "MISSING"
        elif (errors or excessive_parse_failures or config_errors or wrong_provider
              or wrong_upstream_model or reasoning_unverifiable or item_set_mismatch
              or item_snapshot_mismatch or prompt_mismatch):
            status = "INVALID"
        elif n < target["planned_items"]:
            status = "INCOMPLETE"
        elif ungraded:
            status = "UNGRADED"
        elif low <= correct <= high:
            status = "PASS_RECONSTRUCTED" if prompt_provenance_missing else "PASS"
        else:
            status = "MISS"
        out.append({
            "model": model,
            "label": target["label"],
            "n": n,
            "correct": correct,
            "accuracy": correct / n if n else None,
            "target": target["score"],
            "prediction_low": low / n if n else None,
            "prediction_high": high / n if n else None,
            "errors": errors,
            "ungraded": ungraded,
            "parse_failures": parse_failures,
            "config_errors": config_errors,
            "wrong_provider": wrong_provider,
            "wrong_upstream_model": wrong_upstream_model,
            "missing_reasoning": missing_reasoning,
            "reasoning_unverifiable": reasoning_unverifiable,
            "item_set_mismatch": item_set_mismatch,
            "item_snapshot_mismatch": item_snapshot_mismatch,
            "prompt_provenance_missing": prompt_provenance_missing,
            "prompt_mismatch": prompt_mismatch,
            "status": status,
        })
    con.close()
    return out


def print_parity_report(db_path: str | None = None) -> None:
    rows = parity_rows(db_path)
    print("GPQA REPLICATION GATE")
    print("Published target: Artificial Analysis, 198 items x 5 repeats")
    print(f"{'model':39s} {'n':>4s} {'ours':>7s} {'target':>7s} "
          f"{'approx. 95%':>15s} {'status':>19s}")
    print("-" * 101)
    for row in rows:
        ours = f"{row['accuracy']:.1%}" if row["accuracy"] is not None else "-"
        interval = (f"{row['prediction_low']:.1%}-{row['prediction_high']:.1%}"
                    if row["prediction_low"] is not None else "-")
        print(f"{row['model']:39s} {row['n']:4d} {ours:>7s} {row['target']:7.1%} "
              f"{interval:>15s} {row['status']:>19s}")
        problems = row["config_errors"]
        if (row["errors"] or row["parse_failures"] or row["wrong_provider"]
                or row["wrong_upstream_model"] or row["missing_reasoning"]
                or row["item_set_mismatch"] or row["item_snapshot_mismatch"]
                or row["prompt_provenance_missing"] or row["prompt_mismatch"]
                or row["ungraded"] or problems):
            print(f"  errors={row['errors']}, ungraded={row['ungraded']}, "
                  f"parse={row['parse_failures']}, "
                  f"wrong_provider={row['wrong_provider']}, "
                  f"wrong_upstream={row['wrong_upstream_model']}, "
                  f"missing_reasoning={row['missing_reasoning']}, "
                  f"item_set_mismatch={row['item_set_mismatch']}, "
                  f"item_snapshot_mismatch={row['item_snapshot_mismatch']}, "
                  f"prompt_missing={row['prompt_provenance_missing']}, "
                  f"prompt_mismatch={row['prompt_mismatch']}, config={problems}")
