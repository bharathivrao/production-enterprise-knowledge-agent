from app.evaluation.gates import check_thresholds


def test_acceptance_gate_reports_below_minimum_and_above_maximum():
    report = {"mrr": 0.7, "latency": {"p95": 1200}}
    failures = check_thresholds(report, {
        "mrr": {"minimum": 0.8},
        "latency.p95": {"maximum": 1000},
    })
    assert len(failures) == 2


def test_acceptance_gate_passes_compliant_report():
    assert check_thresholds({"mrr": 0.9}, {"mrr": {"minimum": 0.8}}) == []
