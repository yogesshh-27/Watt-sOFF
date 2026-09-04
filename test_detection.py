"""
test_detection.py — Assert-based tests for the Watt's Off detection engine.

Tests use known expected/actual pairs from the project brief's worked examples
to verify detection logic is correct.

Run:  python test_detection.py
"""

import sys
import os

# Ensure we can import from project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from detection import (
    get_time_bucket,
    compute_deviation,
    classify_anomaly,
    score_risk,
    get_severity,
)


def test_time_buckets():
    """Verify hour → time-bucket mapping."""
    assert get_time_bucket(2) == 'night',     f"2 AM should be night"
    assert get_time_bucket(5) == 'night',     f"5 AM should be night"
    assert get_time_bucket(6) == 'morning',   f"6 AM should be morning"
    assert get_time_bucket(9) == 'morning',   f"9 AM should be morning"
    assert get_time_bucket(12) == 'afternoon', f"12 PM should be afternoon"
    assert get_time_bucket(14) == 'afternoon', f"2 PM should be afternoon"
    assert get_time_bucket(17) == 'evening',   f"5 PM should be evening"
    assert get_time_bucket(21) == 'evening',   f"9 PM should be evening"
    assert get_time_bucket(22) == 'night',     f"10 PM should be night"
    assert get_time_bucket(0) == 'night',      f"12 AM should be night"
    print("  ✓ test_time_buckets passed")


def test_deviation_calculation():
    """Verify deviation % math — core brief example: expected 2.5, actual 9.2."""
    # Brief worked example: M027 expected 2.5 kWh, actual 9.2 kWh
    dev = compute_deviation(9.2, 2.5)
    assert 267 <= dev <= 269, f"Expected ~268%, got {dev}%"

    # Normal reading: no deviation
    dev_normal = compute_deviation(2.5, 2.5)
    assert dev_normal == 0.0, f"Expected 0%, got {dev_normal}%"

    # Under-consumption
    dev_under = compute_deviation(1.0, 2.5)
    assert dev_under == -60.0, f"Expected -60%, got {dev_under}%"

    # Edge case: zero expected, non-zero actual
    dev_zero = compute_deviation(5.0, 0.0)
    assert dev_zero == 999.0, f"Expected 999% (cap), got {dev_zero}%"

    print("  ✓ test_deviation_calculation passed")


def test_classify_anomaly():
    """Verify anomaly type classification."""
    # Case 1: Sudden spike — actual 9.2, previous reading 2.5 → jump of 268%
    types = classify_anomaly(
        actual=9.2, expected=2.5, hour=14,
        prev_reading_kwh=2.5, recent_anomaly_count=0
    )
    assert 'sudden_spike' in types, f"Should detect sudden_spike, got {types}"
    assert 'unusual_time' in types, f"Should detect unusual_time (9.2 >> 2.5), got {types}"

    # Case 2: Unusual nighttime — high usage at 2 AM when normally near zero
    types_night = classify_anomaly(
        actual=5.0, expected=0.8, hour=2,
        prev_reading_kwh=0.7, recent_anomaly_count=0
    )
    assert 'unusual_time' in types_night, f"Should detect unusual_time at night, got {types_night}"

    # Case 3: Repeated pattern — 3+ anomalies in last 5 readings
    types_repeated = classify_anomaly(
        actual=6.0, expected=2.5, hour=10,
        prev_reading_kwh=2.5, recent_anomaly_count=3
    )
    assert 'repeated_pattern' in types_repeated, f"Should detect repeated_pattern, got {types_repeated}"

    # Case 4: Normal reading — within range, no history
    types_normal = classify_anomaly(
        actual=2.6, expected=2.5, hour=10,
        prev_reading_kwh=2.4, recent_anomaly_count=0
    )
    assert len(types_normal) == 0, f"Should be normal (no anomalies), got {types_normal}"

    print("  ✓ test_classify_anomaly passed")


def test_risk_scoring():
    """
    Verify risk score computation — brief's worked example:
    M027: expected 2.5, actual 9.2, deviation 268%, sudden_spike + unusual_time
    + repeated_pattern → risk ~95, CRITICAL.
    """
    # Full anomaly scenario from the brief
    risk = score_risk(
        deviation_pct=268.0,
        anomaly_types=['sudden_spike', 'unusual_time', 'repeated_pattern'],
        recent_anomaly_count=3
    )
    assert 90 <= risk <= 100, f"Expected risk ~95, got {risk}"
    assert get_severity(risk) == 'CRITICAL', f"Expected CRITICAL, got {get_severity(risk)}"

    # Normal reading — no flags
    risk_normal = score_risk(
        deviation_pct=0.0,
        anomaly_types=[],
        recent_anomaly_count=0
    )
    assert risk_normal == 0, f"Expected risk 0, got {risk_normal}"
    assert get_severity(risk_normal) == 'LOW', f"Expected LOW, got {get_severity(risk_normal)}"

    # Medium risk — moderate deviation only
    risk_medium = score_risk(
        deviation_pct=120.0,
        anomaly_types=['unusual_time'],
        recent_anomaly_count=0
    )
    assert 25 <= risk_medium <= 40, f"Expected risk 25-40, got {risk_medium}"

    # Severity bands
    assert get_severity(15) == 'LOW'
    assert get_severity(30) == 'LOW'
    assert get_severity(31) == 'MEDIUM'
    assert get_severity(60) == 'MEDIUM'
    assert get_severity(61) == 'HIGH'
    assert get_severity(80) == 'HIGH'
    assert get_severity(81) == 'CRITICAL'
    assert get_severity(100) == 'CRITICAL'

    print("  ✓ test_risk_scoring passed")


if __name__ == '__main__':
    print("\n🔍 Running Watt's Off detection engine tests...\n")

    test_time_buckets()
    test_deviation_calculation()
    test_classify_anomaly()
    test_risk_scoring()

    print("\n✅ All 4 tests passed!\n")
