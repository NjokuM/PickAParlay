from src.analysis import scorer
from src.models import FactorResult


def f(score, weight, conf=1.0):
    return FactorResult(name="x", score=score, weight=weight, evidence=[], data={}, confidence=conf)


def test_value_score_is_weighted_average():
    assert scorer.compute_value_score([f(80, 0.5), f(60, 0.5)]) == 70.0


def test_low_confidence_blends_toward_neutral():
    # conf 0 → the factor counts as 50
    assert scorer.compute_value_score([f(100, 1.0, conf=0.0)]) == 50.0
    assert scorer.compute_value_score([f(100, 1.0, conf=0.5)]) == 75.0


def test_value_score_edge_cases():
    assert scorer.compute_value_score([]) == 0.0
    assert scorer.compute_value_score([f(90, 0.0)]) == 0.0


def test_labels():
    assert scorer.label_recommendation(85) == "Strong Value"
    assert scorer.label_recommendation(70) == "Good Value"
    assert scorer.label_recommendation(55) == "Marginal Value"
    assert scorer.label_recommendation(10) == "Poor Value"


def test_suspicious_line():
    assert scorer.detect_suspicious_line(10.5, 20.0)[0] is True          # line far below average
    assert "below" in scorer.detect_suspicious_line(10.5, 20.0)[1]
    assert scorer.detect_suspicious_line(30.5, 20.0)[0] is True          # far above
    assert "above" in scorer.detect_suspicious_line(30.5, 20.0)[1]
    assert scorer.detect_suspicious_line(20.5, 21.0) == (False, "")
    assert scorer.detect_suspicious_line(20.5, None) == (False, "")
    assert scorer.detect_suspicious_line(0, 10.0) == (False, "")
