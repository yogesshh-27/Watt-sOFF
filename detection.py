"""
detection.py — Electricity Theft Detection Engine for Watt's Off.

CORE DOMAIN PRINCIPLE:
    The primary theft indicator is UNDER-CONSUMPTION compared to the expected baseline.
    When consumers bypass or tamper with meters, the meter records significantly LESS
    energy than actual consumption.
    
    Deviation % = ((Actual Consumption - Expected Baseline) / Expected Baseline) * 100

    Categories:
    - NORMAL:            -10% <= Deviation <= +20%   (Actual close to Expected)
    - SUSPICIOUS:        -30% <= Deviation < -10%    (Actual moderately below Expected)
    - HIGH_THEFT_RISK:   Deviation < -30%            (Actual significantly below Expected)
    - OVER_CONSUMPTION:  Deviation > +20%            (Load surge anomaly; NOT electricity theft)

    THEFT RISK SCORE (0–100):
    Calculated using multiple signals:
    1. Under-consumption magnitude (primary: up to 55 pts)
    2. Sudden drop from preceding reading (up to 15 pts)
    3. Repeated under-consumption history (up to 10 pts)
    4. Hardware tamper events (magnetic, cover open, neutral bypass) (up to 10 pts)
    5. Reverse energy / electrical abnormalities (up to 5 pts)
    6. Transformer feeder energy mismatch (up to 5 pts)
"""

THEFT_STATUS_NORMAL = 'NORMAL'
THEFT_STATUS_SUSPICIOUS = 'SUSPICIOUS'
THEFT_STATUS_HIGH_THEFT = 'HIGH_THEFT_RISK'
THEFT_STATUS_OVER_CONSUMPTION = 'OVER_CONSUMPTION'

import sys
import os
from datetime import datetime

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass



# ---------------------------------------------------------------------------
# Time-of-day buckets
# ---------------------------------------------------------------------------

TIME_BUCKETS = {
    'night':     (22, 5),    # 22:00 – 05:59
    'morning':   (6, 11),    # 06:00 – 11:59
    'afternoon': (12, 16),   # 12:00 – 16:59
    'evening':   (17, 21),   # 17:00 – 21:59
}


def get_time_bucket(hour):
    """Maps an hour (0-23) to its time-of-day bucket name."""
    if hour >= 22 or hour <= 5:
        return 'night'
    elif 6 <= hour <= 11:
        return 'morning'
    elif 12 <= hour <= 16:
        return 'afternoon'
    else:
        return 'evening'


def compute_expected(meter_id, hour, db):
    """
    Looks up the precomputed baseline average consumption (kWh) for a given
    meter in the time-of-day bucket that contains `hour`.
    """
    bucket = get_time_bucket(hour)
    cursor = db.execute(
        "SELECT avg_kwh FROM baselines WHERE meter_id = ? AND time_bucket = ?",
        (meter_id, bucket)
    )
    row = cursor.fetchone()
    if row and row['avg_kwh'] is not None:
        return row['avg_kwh']

    cursor = db.execute(
        """SELECT AVG(consumption_kwh) as avg_kwh FROM readings
           WHERE meter_id = ? AND hour >= ? AND hour <= ?""",
        (meter_id,
         TIME_BUCKETS[bucket][0] if bucket != 'night' else 0,
         TIME_BUCKETS[bucket][1] if bucket != 'night' else 23)
    )
    row = cursor.fetchone()
    if row and row['avg_kwh'] is not None:
        return row['avg_kwh']
    return 2.5  # safe default fallback


def compute_deviation(actual, expected):
    """
    Computes deviation percentage: ((actual - expected) / expected) * 100.
    Negative deviation = under-consumption (theft indicator).
    Positive deviation = over-consumption (load surge).
    """
    if expected <= 0:
        return 0.0 if actual <= 0 else 999.0
    return round(((actual - expected) / expected) * 100.0, 1)


# ---------------------------------------------------------------------------
# Theft Classification & Multi-Signal Scoring
# ---------------------------------------------------------------------------

def classify_theft_category(deviation_pct):
    """
    Categorizes the reading into one of four mutually exclusive statuses:
    - OVER_CONSUMPTION:  Deviation > +20% (NOT theft by default)
    - NORMAL:            -10% <= Deviation <= +20%
    - SUSPICIOUS:        -30% <= Deviation < -10%
    - HIGH_THEFT_RISK:   Deviation < -30%
    """
    if deviation_pct > 20.0:
        return 'OVER_CONSUMPTION'
    elif deviation_pct < -30.0:
        return 'HIGH_THEFT_RISK'
    elif deviation_pct < -10.0:
        return 'SUSPICIOUS'
    else:
        return 'NORMAL'


def compute_theft_info(deviation_pct):
    """
    Classifies theft status (NORMAL / SUSPICIOUS / HIGH_THEFT_RISK / OVER_CONSUMPTION)
    and computes theft_risk_score (0–100) based purely on under-consumption.
    """
    status = classify_theft_category(deviation_pct)
    if status == 'OVER_CONSUMPTION' or status == 'NORMAL':
        score = 0
    elif status == 'HIGH_THEFT_RISK':
        # Deviation < -30%: scaled from 65 to 100
        score = min(100, int(round(65 + (abs(deviation_pct) - 30.0) * 0.7)))
    elif status == 'SUSPICIOUS':
        # Deviation -10% to -30%: scaled from 30 to 60
        score = min(60, int(round(30 + (abs(deviation_pct) - 10.0) * 1.5)))
    else:
        score = 0
    return status, score


def score_theft_risk(deviation_pct, signals):
    """
    Computes a composite Theft Risk Score from 0–100.
    
    IMPORTANT: Over-consumption is NOT electricity theft and receives 0 theft risk.
    Under-consumption receives risk proportional to negative deviation depth and
    accompanying physical/grid evidence.

    Args:
        deviation_pct: float (e.g. -69.6)
        signals: dict with keys:
            - sudden_drop (bool): True if reading dropped >40% from preceding reading
            - repeated_theft (bool): True if 3+ under-consumption events in recent history
            - has_tamper (bool): True if recent hardware tamper event logged
            - reverse_flow (bool): True if reverse energy detected
            - transformer_mismatch (bool): True if feeder has >15% unaccounted loss
    
    Returns:
        int: Theft risk score (0 to 100).
    """
    category = classify_theft_category(deviation_pct)

    if category == 'OVER_CONSUMPTION':
        return 0

    if category == 'NORMAL':
        # Minor ambient fluctuations have near-zero risk
        return max(0, min(10, int(round(-deviation_pct)))) if deviation_pct < 0 else 0

    # Base score derived from magnitude of under-consumption (negative deviation)
    # Maps deviation from -10% to -80% into 30 to 60 base points
    abs_neg_dev = min(80.0, abs(deviation_pct))
    base_score = 30.0 + ((abs_neg_dev - 10.0) / 70.0) * 30.0

    score = base_score

    # Signal 1: Sudden drop from normal to near-zero/bypass (+15 pts)
    if signals.get('sudden_drop'):
        score += 15.0

    # Signal 2: Repeated under-consumption theft history (+10 pts)
    if signals.get('repeated_theft'):
        score += 10.0

    # Signal 3: Hardware tamper events (magnetic, cover open, neutral bypass) (+12 pts)
    if signals.get('has_tamper'):
        score += 12.0

    # Signal 4: Reverse energy flow / phase inversion (+6 pts)
    if signals.get('reverse_flow'):
        score += 6.0

    # Signal 5: Feeder / Transformer Energy Mismatch (+7 pts)
    if signals.get('transformer_mismatch'):
        score += 7.0

    # For HIGH_THEFT_RISK, ensure minimum threshold of 65
    if category == 'HIGH_THEFT_RISK':
        score = max(65.0, score)

    return min(100, int(round(score)))


def get_severity(theft_status_or_score, theft_risk_score=None):
    """Returns the visual severity classification."""
    if isinstance(theft_status_or_score, (int, float)):
        score = theft_status_or_score
        if score >= 65:
            return 'HIGH_THEFT_RISK'
        if score >= 30:
            return 'SUSPICIOUS'
        return 'NORMAL'

    theft_status = str(theft_status_or_score)
    score = theft_risk_score if theft_risk_score is not None else 0
    if theft_status == 'OVER_CONSUMPTION':
        return 'OVER_CONSUMPTION'
    if theft_status == 'HIGH_THEFT_RISK' or score >= 65:
        return 'HIGH_THEFT_RISK'
    if theft_status == 'SUSPICIOUS' or score >= 30:
        return 'SUSPICIOUS'
    return 'NORMAL'


# ---------------------------------------------------------------------------
# Orchestrator: process_reading
# ---------------------------------------------------------------------------

def process_reading(reading_data, db):
    """
    Full theft detection pipeline for one incoming meter reading.

    Args:
        reading_data: dict with keys:
            - meter_id (str)
            - consumption_kwh (float)
            - hour (int, 0-23)
            - timestamp (str, ISO 8601)
            - reading_id (int, the readings.id)
            - voltage_v (optional float)
            - current_a (optional float)
            - reverse_flow (optional int/bool)
        db: SQLite connection

    Returns:
        dict with detection results, theft classification, risk score, and alert details.
    """
    meter_id = reading_data['meter_id']
    actual = reading_data['consumption_kwh']
    hour = reading_data['hour']
    timestamp = reading_data['timestamp']
    reading_id = reading_data['reading_id']
    reverse_flow = bool(reading_data.get('reverse_flow', 0))

    # Step 1: Expected baseline lookup
    expected = compute_expected(meter_id, hour, db)

    # Step 2: Calculate deviation
    deviation_pct = compute_deviation(actual, expected)

    # Step 3: Categorize theft status and base risk
    theft_status, base_theft_risk = compute_theft_info(deviation_pct)

    # Step 4: Gather multi-signal evidence
    # A) Preceding reading for sudden drop check
    cursor = db.execute(
        """SELECT consumption_kwh FROM readings
           WHERE meter_id = ? AND id < ?
           ORDER BY id DESC LIMIT 1""",
        (meter_id, reading_id)
    )
    prev_row = cursor.fetchone()
    prev_kwh = prev_row['consumption_kwh'] if prev_row else None
    
    sudden_drop = False
    if prev_kwh is not None and prev_kwh > 0.5 and actual < prev_kwh:
        drop_pct = ((prev_kwh - actual) / prev_kwh) * 100.0
        if drop_pct >= 40.0 and actual < expected * 0.7:
            sudden_drop = True

    # B) Historical under-consumption count (last 5 anomalies)
    cursor = db.execute(
        """SELECT COUNT(*) as cnt FROM anomalies
           WHERE meter_id = ? AND theft_status IN ('SUSPICIOUS', 'HIGH_THEFT_RISK')
           AND reading_id IN (
               SELECT id FROM readings WHERE meter_id = ? AND id < ? ORDER BY id DESC LIMIT 5
           )""",
        (meter_id, meter_id, reading_id)
    )
    repeated_theft = cursor.fetchone()['cnt'] >= 2

    # C) Hardware tamper events (check if any tamper event recorded recently for this meter)
    cursor = db.execute(
        "SELECT COUNT(*) as cnt FROM tamper_events WHERE meter_id = ?",
        (meter_id,)
    )
    has_tamper = cursor.fetchone()['cnt'] > 0

    # D) Transformer energy mismatch check
    cursor = db.execute(
        """SELECT t.transformer_id, t.input_kwh FROM transformers t
           JOIN meters m ON m.transformer_id = t.transformer_id
           WHERE m.meter_id = ?""",
        (meter_id,)
    )
    t_row = cursor.fetchone()
    transformer_mismatch = False
    if t_row and t_row['input_kwh'] > 0:
        # Check sum of meters on this transformer
        cursor = db.execute(
            """SELECT SUM(r.consumption_kwh) as metered_sum
               FROM meters m
               JOIN readings r ON r.meter_id = m.meter_id
               WHERE m.transformer_id = ?
               AND r.id IN (SELECT MAX(id) FROM readings GROUP BY meter_id)""",
            (t_row['transformer_id'],)
        )
        sum_row = cursor.fetchone()
        metered_sum = sum_row['metered_sum'] or 0.0
        tech_loss = t_row['input_kwh'] * 0.055
        unaccounted = t_row['input_kwh'] - (metered_sum + tech_loss)
        if unaccounted > t_row['input_kwh'] * 0.15:
            transformer_mismatch = True

    signals = {
        'sudden_drop': sudden_drop,
        'repeated_theft': repeated_theft,
        'has_tamper': has_tamper,
        'reverse_flow': reverse_flow,
        'transformer_mismatch': transformer_mismatch
    }

    # Step 5: Score theft risk (0–100)
    theft_risk_score = score_theft_risk(deviation_pct, signals)
    severity = get_severity(theft_status, theft_risk_score)

    # Build active signals list
    active_signals = []
    if deviation_pct < -30:
        active_signals.append('severe_under_consumption')
    elif deviation_pct < -10:
        active_signals.append('moderate_under_consumption')
    elif deviation_pct > 20:
        active_signals.append('over_consumption')
        
    if sudden_drop:
        active_signals.append('sudden_drop')
    if repeated_theft:
        active_signals.append('repeated_pattern')
    if has_tamper:
        active_signals.append('hardware_tamper_event')
    if reverse_flow:
        active_signals.append('reverse_energy_flow')
    if transformer_mismatch:
        active_signals.append('transformer_mismatch')

    signals_str = ','.join(active_signals)
    is_anomaly = theft_status != 'NORMAL'

    result = {
        'meter_id': meter_id,
        'is_anomaly': is_anomaly,
        'actual_kwh': actual,
        'expected_kwh': round(expected, 2),
        'deviation_pct': deviation_pct,
        'theft_status': theft_status,
        'theft_risk_score': theft_risk_score,
        'severity': severity,
        'active_signals': active_signals,
        'anomaly_id': None,
        'alert_id': None
    }

    # Step 6: Persist anomaly and generate alerts if suspicious, high theft, or heavy over-consumption
    if is_anomaly:
        now = datetime.now().isoformat()
        cursor = db.execute(
            """INSERT INTO anomalies
               (meter_id, reading_id, anomaly_type, expected_kwh, actual_kwh,
                deviation_pct, risk_score, theft_status, theft_risk_score, theft_signals, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (meter_id, reading_id, theft_status.lower(), expected, actual,
             deviation_pct, theft_risk_score, theft_status, theft_risk_score, signals_str, 'flagged', now)
        )
        anomaly_id = cursor.lastrowid
        result['anomaly_id'] = anomaly_id

        # Step 7: Create Explainable Alert
        loc_cursor = db.execute("SELECT location FROM meters WHERE meter_id = ?", (meter_id,))
        loc_row = loc_cursor.fetchone()
        location = loc_row['location'] if loc_row else 'Unknown'

        # Generate alert text based on category
        if theft_status == 'HIGH_THEFT_RISK':
            alert_msg = (
                f"🔴 HIGH THEFT RISK ({theft_risk_score}/100) — Meter {meter_id} at {location}: "
                f"Actual consumption is {abs(deviation_pct):.1f}% below expected baseline "
                f"({actual:.1f} kWh vs {expected:.1f} kWh)."
            )
            if has_tamper:
                alert_msg += " Recent tamper event logged."
            if transformer_mismatch:
                alert_msg += " Feeder unaccounted energy mismatch detected."

            cursor = db.execute(
                """INSERT INTO alerts (anomaly_id, meter_id, location, risk_score, severity, alert_category, message, created_at)
                   VALUES (?, ?, ?, ?, ?, 'THEFT', ?, ?)""",
                (anomaly_id, meter_id, location, theft_risk_score, 'HIGH_THEFT_RISK', alert_msg, now)
            )
            result['alert_id'] = cursor.lastrowid

        elif theft_status == 'SUSPICIOUS':
            alert_msg = (
                f"🟡 SUSPICIOUS ({theft_risk_score}/100) — Meter {meter_id} at {location}: "
                f"Actual consumption is {abs(deviation_pct):.1f}% below expected baseline "
                f"({actual:.1f} kWh vs {expected:.1f} kWh)."
            )
            cursor = db.execute(
                """INSERT INTO alerts (anomaly_id, meter_id, location, risk_score, severity, alert_category, message, created_at)
                   VALUES (?, ?, ?, ?, ?, 'THEFT', ?, ?)""",
                (anomaly_id, meter_id, location, theft_risk_score, 'SUSPICIOUS', alert_msg, now)
            )
            result['alert_id'] = cursor.lastrowid

        elif theft_status == 'OVER_CONSUMPTION' and deviation_pct >= 50.0:
            # Over-consumption alert explicitly stating NOT THEFT
            alert_msg = (
                f"🟠 OVER-CONSUMPTION — Meter {meter_id} at {location}: "
                f"Actual consumption is {deviation_pct:+.0f}% above expected baseline "
                f"({actual:.1f} kWh vs {expected:.1f} kWh). This must NOT be classified as theft."
            )
            cursor = db.execute(
                """INSERT INTO alerts (anomaly_id, meter_id, location, risk_score, severity, alert_category, message, created_at)
                   VALUES (?, ?, ?, ?, ?, 'OVER_CONSUMPTION', ?, ?)""",
                (anomaly_id, meter_id, location, 0, 'OVER_CONSUMPTION', alert_msg, now)
            )
            result['alert_id'] = cursor.lastrowid

        db.commit()

    return result
