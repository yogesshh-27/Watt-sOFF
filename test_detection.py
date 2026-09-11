"""
test_detection.py — Assert-based tests for the Electricity Theft Detection Engine.

Verifies:
1. Hour-of-day time bucket mapping
2. Deviation % calculation: ((actual - expected) / expected) * 100
3. Theft categorization (NORMAL, SUSPICIOUS, HIGH_THEFT_RISK, OVER_CONSUMPTION)
4. Strict non-theft classification for OVER_CONSUMPTION (risk score = 0)
5. Multi-signal theft risk scoring (M009 scenario: expected 10.2, actual 3.1 -> -69.6% -> ~91/100)
"""

import sys
import os

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detection import (
    get_time_bucket,
    compute_deviation,
    classify_theft_category,
    compute_theft_info,
    score_theft_risk,
    get_severity,
)


def test_time_buckets():
    """Verify hour -> time-bucket mapping."""
    assert get_time_bucket(2) == 'night', "2 AM should be night"
    assert get_time_bucket(9) == 'morning', "9 AM should be morning"
    assert get_time_bucket(14) == 'afternoon', "2 PM should be afternoon"
    assert get_time_bucket(19) == 'evening', "7 PM should be evening"
    print("  ✓ test_time_buckets passed")


def test_deviation_calculation():
    """Verify deviation % math."""
    # Under-consumption (theft case: M009 expected 10.2, actual 3.1)
    dev_theft = compute_deviation(3.1, 10.2)
    assert -70.0 <= dev_theft <= -69.0, f"Expected ~ -69.6%, got {dev_theft}%"

    # Normal reading: actual 9.0, expected 10.0 -> -10%
    dev_norm = compute_deviation(9.0, 10.0)
    assert dev_norm == -10.0, f"Expected -10.0%, got {dev_norm}%"

    # Over-consumption: actual 14.0, expected 10.0 -> +40%
    dev_over = compute_deviation(14.0, 10.0)
    assert dev_over == 40.0, f"Expected +40.0%, got {dev_over}%"

    print("  ✓ test_deviation_calculation passed")


def test_theft_categorization():
    """
    Verify categories:
    - Expected = 10, Actual = 9  (-10%) -> NORMAL
    - Expected = 10, Actual = 5  (-50%) -> HIGH_THEFT_RISK
    - Expected = 10, Actual = 2  (-80%) -> HIGH_THEFT_RISK
    - Expected = 10, Actual = 8  (-20%) -> SUSPICIOUS
    - Expected = 10, Actual = 14 (+40%) -> OVER_CONSUMPTION
    """
    assert classify_theft_category(-5.0) == 'NORMAL'
    assert classify_theft_category(-10.0) == 'NORMAL'
    assert classify_theft_category(-20.0) == 'SUSPICIOUS'
    assert classify_theft_category(-50.0) == 'HIGH_THEFT_RISK'
    assert classify_theft_category(-80.0) == 'HIGH_THEFT_RISK'
    assert classify_theft_category(40.0) == 'OVER_CONSUMPTION'
    print("  ✓ test_theft_categorization passed")


def test_over_consumption_not_theft():
    """Verify that over-consumption is NOT marked as electricity theft."""
    risk = score_theft_risk(deviation_pct=180.0, signals={})
    assert risk == 0, f"Over-consumption must have 0 theft risk, got {risk}"
    assert get_severity('OVER_CONSUMPTION', risk) == 'OVER_CONSUMPTION'
    print("  ✓ test_over_consumption_not_theft passed")


def test_theft_risk_scoring():
    """
    Verify multi-signal scoring:
    Meter M009: Expected 10.2 kWh, Actual 3.1 kWh (-69.6% deviation),
    with sudden drop, tamper event, and transformer mismatch -> ~91/100 (HIGH_THEFT_RISK).
    """
    signals = {
        'sudden_drop': True,
        'repeated_theft': True,
        'has_tamper': True,
        'reverse_flow': False,
        'transformer_mismatch': True
    }
    risk = score_theft_risk(-69.6, signals)
    assert 85 <= risk <= 100, f"Expected M009 theft risk 85-100, got {risk}"
    assert get_severity('HIGH_THEFT_RISK', risk) == 'HIGH_THEFT_RISK'

    # Moderate suspicious case without tamper
    risk_suspicious = score_theft_risk(-25.0, {'sudden_drop': False, 'has_tamper': False})
    assert 30 <= risk_suspicious <= 60, f"Expected suspicious risk 30-60, got {risk_suspicious}"
    assert get_severity('SUSPICIOUS', risk_suspicious) == 'SUSPICIOUS'

    print("  ✓ test_theft_risk_scoring passed")


def test_compute_theft_info():
    """Verify compute_theft_info returns status and under-consumption risk score."""
    status_norm, score_norm = compute_theft_info(-5.0)
    assert status_norm == 'NORMAL' and score_norm == 0

    status_susp, score_susp = compute_theft_info(-20.0)
    assert status_susp == 'SUSPICIOUS' and 30 <= score_susp <= 60

    status_theft, score_theft = compute_theft_info(-69.6)
    assert status_theft == 'HIGH_THEFT_RISK' and 80 <= score_theft <= 100

    status_over, score_over = compute_theft_info(180.0)
    assert status_over == 'OVER_CONSUMPTION' and score_over == 0
    print("  ✓ test_compute_theft_info passed")


if __name__ == '__main__':
    print("\n🔍 Running Watt's Off Electricity Theft Detection Engine tests...\n")
    test_time_buckets()
    test_deviation_calculation()
    test_theft_categorization()
    test_over_consumption_not_theft()
    test_theft_risk_scoring()
    test_compute_theft_info()
    print("\n✅ All Electricity Theft Detection tests passed successfully!\n")
