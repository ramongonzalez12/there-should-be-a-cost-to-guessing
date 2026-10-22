"""Tests for the cross-domain and behavior result exporter."""

import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "export_domain_alignment", ROOT / "scripts" / "export_domain_alignment.py"
)
assert SPEC and SPEC.loader
exporter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(exporter)


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_export_keeps_risk_endpoints_beside_their_controls(tmp_path, monkeypatch):
    run_root = tmp_path / "runs"
    contrasts = []
    xstest_cells = {}
    agentic_cells = {}
    for domain_index, domain in enumerate(("medicine", "math", "ethics"), start=1):
        for evaluation_domain in ("medicine", "math", "ethics"):
            contrasts.append(
                {
                    "training_domain": domain,
                    "evaluation_domain": evaluation_domain,
                    "n": 100,
                    "accuracy_change": 0.01,
                    "accuracy_change_interval_95": [-0.02, 0.04],
                    "quadratic_score_change": 0.05,
                    "quadratic_score_change_interval_95": [0.01, 0.09],
                    "high_confidence_wrong_change": -0.2,
                }
            )
        for objective, offset in (("binary", 0.0), ("quadratic", 0.1)):
            checkpoint = f"{domain}-{objective}"
            xstest_cells[checkpoint] = {
                "benign_refusal_rate": 0.4 + offset,
                "parse_rate": 0.9 - offset,
                "unsafe_compliance_rate": 0.2 - offset,
            }
            agentic_cells[f"{checkpoint}|neutral"] = {
                "integrity": {
                    "unauthorized_shortcut_rate": 0.3 - offset,
                    "benign_tool_success": 0.7 + offset,
                    "tamper_rate": 0.0,
                    "concealment_given_prohibited": None,
                    "prohibited_n": domain_index,
                },
                "goal": {"appropriate_action_rate": 0.6 + offset},
            }

    _write(run_root / "evaluation_matrix" / "summary.json", {"contrasts": contrasts})
    _write(run_root / "xstest_actions_v1" / "summary.json", {"cells": xstest_cells})
    _write(
        run_root / "plural_prudence_v1" / "summary.json",
        {"records": 123, "by_cell": agentic_cells},
    )
    for folder, spend in (
        ("evaluation_matrix", 0.1),
        ("xstest_actions_v1", 0.2),
        ("plural_prudence_v1", 0.3),
    ):
        _write(run_root / folder / "spend.json", {"spent_usd": spend})
    for folder, item_file in (
        ("evaluation_matrix", "domain_evaluation_items.json"),
        ("xstest_actions_v1", "xstest_items.json"),
        ("plural_prudence_v1", "items.json"),
    ):
        _write(run_root / folder / "manifest.json", {"status": "COMPLETE"})
        _write(run_root / folder / item_file, [])
        (run_root / folder / "responses.jsonl").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(exporter, "TRANSFER_OUT", tmp_path / "transfer.csv")
    monkeypatch.setattr(exporter, "BEHAVIOR_OUT", tmp_path / "behavior.csv")
    monkeypatch.setattr(exporter, "MANIFEST_OUT", tmp_path / "manifest.json")
    monkeypatch.setattr(exporter, "ROOT", tmp_path)

    transfer_rows, behavior_rows = exporter.export(run_root)

    assert len(transfer_rows) == 9
    assert len(behavior_rows) == 3
    medicine = next(row for row in behavior_rows if row["training_domain"] == "medicine")
    assert round(medicine["unauthorized_shortcut_change"], 6) == -0.1
    assert round(medicine["benign_tool_success_change"], 6) == 0.1
    assert round(medicine["xstest_benign_refusal_change"], 6) == 0.1
    assert round(medicine["xstest_parse_change"], 6) == -0.1
    assert round(medicine["xstest_unsafe_compliance_change"], 6) == -0.1
    assert medicine["prohibited_n_binary"] == 1
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["records"]["agentic_responses"] == 123
    assert manifest["spend_usd"]["agentic"] == 0.3
