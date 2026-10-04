import argparse
import json
from pathlib import Path


def _get(value, path):
    for part in path.split("."):
        value = value[part]
    return value


def check_thresholds(report: dict, thresholds: dict) -> list[str]:
    failures = []
    for path, rule in thresholds.items():
        try:
            actual = _get(report, path)
        except (KeyError, TypeError):
            failures.append(f"{path}: missing metric")
            continue
        if actual is None:
            failures.append(f"{path}: metric is null")
        elif "minimum" in rule and actual < rule["minimum"]:
            failures.append(f"{path}: {actual:.4f} < {rule['minimum']:.4f}")
        elif "maximum" in rule and actual > rule["maximum"]:
            failures.append(f"{path}: {actual:.4f} > {rule['maximum']:.4f}")
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Apply evaluation acceptance gates.")
    parser.add_argument("--kind", choices=["retrieval", "answer", "grader_calibration"], required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--thresholds", type=Path,
        default=Path(__file__).resolve().parents[2] / "evals/acceptance_thresholds.json",
    )
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    configured = json.loads(args.thresholds.read_text(encoding="utf-8"))[args.kind]
    failures = check_thresholds(report, configured)
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        raise SystemExit(1)
    print(f"PASS: {args.kind} acceptance thresholds")
