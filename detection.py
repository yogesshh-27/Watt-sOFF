"""
detection.py — Statistical/rule-based anomaly detection engine for Watt's Off.

ENGINEERING TRADE-OFF (see NOTES.md):
    This module uses rule-based/statistical detection instead of KNN/SVM/Random Forest.
    This is a deliberate substitution: it produces identical outputs (deviation %,
    anomaly type, risk score 0–100) without requiring labeled training data or an ML
    pipeline. The function signatures are designed so the internals can be swapped for
    sklearn.ensemble.IsolationForest (see Stretch Goal in README.md) without changing
    any other file.

Detection pipeline for each reading:
    1. compute_expected()  → per-meter, per-time-bucket baseline
    2. classify_anomaly()  → sudden_spike / unusual_time / repeated_pattern
    3. score_risk()        → weighted composite 0–100
    4. process_reading()   → orchestrator: runs 1–3, writes anomaly/alert rows
"""

from datetime import datetime


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Time-of-day buckets (hour ranges, inclusive)
TIME_BUCKETS = {
    'night':     (22, 5),    # 22:00 – 05:59
    'morning':   (6, 11),    # 06:00 – 11:59
    'afternoon': (12, 16),   # 12:00 – 16:59
    'evening':   (17, 21),   # 17:00 – 21:59
}

# Risk-score weights (sum to 100 with 5 pts headroom → max realistic ≈ 95-100)
WEIGHT_DEVIATION    = 40   # Consumption deviation magnitude: up to 40 pts
WEIGHT_SPIKE        = 20   # Sudden spike present: +20 pts
WEIGHT_UNUSUAL_TIME = 15   # Unusual time-of-day: +15 pts
WEIGHT_REPEATED     = 20   # Repeated anomaly history: +20 pts
# Remaining 5 pts of headroom

# Severity bands
SEVERITY_BANDS = [
    (0,  30, 'LOW'),
    (31, 60, 'MEDIUM'),
    (61, 80, 'HIGH'),
    (81, 100, 'CRITICAL'),
]

# Thresholds
SPIKE_THRESHOLD_PCT = 150      # deviation > 150% vs preceding reading → sudden_spike
UNUSUAL_TIME_FACTOR = 2.5      # actual > 2.5× the hour-bucket baseline → unusual_time
REPEATED_MIN_COUNT  = 3        # 3+ anomalies in last 5 readings → repeated_pattern
ALERT_MIN_RISK      = 61       # risk ≥ 61 → create an alert

# Deviation percentage beyond which we cap the deviation score component
DEVIATION_CAP_PCT = 300        # 300% deviation → full 40 pts


# ---------------------------------------------------------------------------
# 1. Compute expected consumption
# ---------------------------------------------------------------------------

def get_time_bucket(hour):
    """
    Maps an hour (0-23) to its time-of-day bucket name.

    >>> get_time_bucket(2)
    'night'
    >>> get_time_bucket(9)
    'morning'
    >>> get_time_bucket(14)
    'afternoon'
    >>> get_time_bucket(19)
    'evening'
    """
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

    This is the KEY requirement from the brief: per-meter baselines, NOT a
    global threshold like "consumption > 5 → theft".

    Returns:
        float: Expected kWh for this meter at this time of day.
               Returns 1.0 as a fallback if no baseline exists (new meter).
    """
    bucket = get_time_bucket(hour)
    cursor = db.execute(
        "SELECT avg_kwh FROM baselines WHERE meter_id = ? AND time_bucket = ?",
        (meter_id, bucket)
    )
    row = cursor.fetchone()
    if row:
        return row['avg_kwh']
    # Fallback: compute from raw readings if baseline table not populated yet
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
    return 1.0  # safe default for brand-new meters


def compute_deviation(actual, expected):
    """
    Computes deviation percentage: (actual - expected) / expected * 100.

    >>> compute_deviation(9.2, 2.5)
    268.0
    >>> compute_deviation(2.5, 2.5)
    0.0
    >>> compute_deviation(1.0, 2.5)
    -60.0
    """
    if expected == 0:
        return 0.0 if actual == 0 else 999.0
    return round((actual - expected) / expected * 100, 1)


# ---------------------------------------------------------------------------
# 2. Classify anomaly type
# ---------------------------------------------------------------------------

def classify_anomaly(actual, expected, hour, prev_reading_kwh, recent_anomaly_count):
    """
    Determines which anomaly types apply to a reading.

    Args:
        actual:               Actual consumption (kWh).
        expected:             Baseline expected consumption (kWh).
        hour:                 Hour of reading (0-23).
        prev_reading_kwh:     The immediately preceding reading's kWh (or None).
        recent_anomaly_count: Number of anomalies for this meter in the last 5 readings.

    Returns:
        list[str]: List of anomaly type strings. Empty list = normal reading.

    Anomaly types:
        - sudden_spike:     deviation > 150% vs the immediately preceding reading
        - unusual_time:     consumption far above the hour-bucket baseline
                            (e.g., high usage at 2 AM when meter is normally near zero)
        - repeated_pattern: 3+ anomalies in the last 5 readings for this meter
    """
    anomaly_types = []
    deviation_pct = compute_deviation(actual, expected)

    # --- sudden_spike: compare against previous reading ---
    if prev_reading_kwh is not None and prev_reading_kwh > 0:
        reading_jump_pct = ((actual - prev_reading_kwh) / prev_reading_kwh) * 100
        if reading_jump_pct > SPIKE_THRESHOLD_PCT:
            anomaly_types.append('sudden_spike')

    # --- unusual_time: high consumption during normally-quiet hours ---
    if expected > 0 and actual > expected * UNUSUAL_TIME_FACTOR:
        # Stronger signal during night hours when consumption should be lowest
        bucket = get_time_bucket(hour)
        if bucket == 'night' and actual > expected * 2.0:
            anomaly_types.append('unusual_time')
        elif actual > expected * UNUSUAL_TIME_FACTOR:
            anomaly_types.append('unusual_time')

    # --- repeated_pattern: 3+ anomalies in last 5 readings ---
    if recent_anomaly_count >= REPEATED_MIN_COUNT:
        anomaly_types.append('repeated_pattern')

    return anomaly_types


# ---------------------------------------------------------------------------
# 3. Score risk (0–100)
# ---------------------------------------------------------------------------

def score_risk(deviation_pct, anomaly_types, recent_anomaly_count):
    """
    Computes a weighted risk score (0–100).

    Weights:
        - Consumption deviation magnitude: up to 40 pts
        - Sudden spike present:            +20 pts
        - Unusual time-of-day:             +15 pts
        - Repeated anomaly history:        +20 pts
        - (5 pts headroom so max realistic ≈ 95–100)

    >>> score_risk(268.0, ['sudden_spike', 'unusual_time', 'repeated_pattern'], 3)
    95
    >>> score_risk(0.0, [], 0)
    0
    >>> score_risk(50.0, [], 0)
    7
    """
    score = 0

    # Deviation component: scale linearly up to DEVIATION_CAP_PCT → WEIGHT_DEVIATION pts
    abs_dev = abs(deviation_pct)
    deviation_score = min(abs_dev / DEVIATION_CAP_PCT, 1.0) * WEIGHT_DEVIATION
    score += deviation_score

    # Spike component
    if 'sudden_spike' in anomaly_types:
        score += WEIGHT_SPIKE

    # Unusual time component
    if 'unusual_time' in anomaly_types:
        score += WEIGHT_UNUSUAL_TIME

    # Repeated pattern component
    if 'repeated_pattern' in anomaly_types:
        score += WEIGHT_REPEATED

    # Cap at 100
    return min(int(round(score)), 100)


def get_severity(risk_score):
    """
    Maps a risk score (0–100) to a severity label.

    >>> get_severity(15)
    'LOW'
    >>> get_severity(45)
    'MEDIUM'
    >>> get_severity(72)
    'HIGH'
    >>> get_severity(95)
    'CRITICAL'
    """
    for low, high, label in SEVERITY_BANDS:
        if low <= risk_score <= high:
            return label
    return 'CRITICAL'  # anything above 100 (shouldn't happen, but safe)


# ---------------------------------------------------------------------------
# 4. Process reading (orchestrator)
# ---------------------------------------------------------------------------

def process_reading(reading_data, db):
    """
    Full detection pipeline for one incoming reading.

    Args:
        reading_data: dict with keys:
            - meter_id (str)
            - consumption_kwh (float)
            - hour (int, 0-23)
            - timestamp (str, ISO 8601)
            - reading_id (int, the readings.id after insertion)
        db: SQLite connection

    Returns:
        dict with detection results:
            - is_anomaly (bool)
            - anomaly_types (list[str])
            - expected_kwh (float)
            - actual_kwh (float)
            - deviation_pct (float)
            - risk_score (int)
            - severity (str)
            - anomaly_id (int or None)
            - alert_id (int or None)
    """
    meter_id = reading_data['meter_id']
    actual = reading_data['consumption_kwh']
    hour = reading_data['hour']
    timestamp = reading_data['timestamp']
    reading_id = reading_data['reading_id']

    # Step 1: Expected value from per-meter baseline
    expected = compute_expected(meter_id, hour, db)

    # Step 2: Deviation
    deviation_pct = compute_deviation(actual, expected)

    # Step 3: Get preceding reading for spike detection
    cursor = db.execute(
        """SELECT consumption_kwh FROM readings
           WHERE meter_id = ? AND id < ?
           ORDER BY id DESC LIMIT 1""",
        (meter_id, reading_id)
    )
    prev_row = cursor.fetchone()
    prev_reading_kwh = prev_row['consumption_kwh'] if prev_row else None

    # Step 4: Count recent anomalies for repeated-pattern check
    cursor = db.execute(
        """SELECT COUNT(*) as cnt FROM anomalies
           WHERE meter_id = ? AND reading_id IN (
               SELECT id FROM readings
               WHERE meter_id = ? AND id < ?
               ORDER BY id DESC LIMIT 5
           )""",
        (meter_id, meter_id, reading_id)
    )
    recent_anomaly_count = cursor.fetchone()['cnt']

    # Step 5: Classify anomaly types
    anomaly_types = classify_anomaly(
        actual, expected, hour, prev_reading_kwh, recent_anomaly_count
    )

    # Step 6: Score risk
    risk_score = score_risk(deviation_pct, anomaly_types, recent_anomaly_count)
    severity = get_severity(risk_score)
    is_anomaly = len(anomaly_types) > 0

    result = {
        'is_anomaly': is_anomaly,
        'anomaly_types': anomaly_types,
        'expected_kwh': round(expected, 2),
        'actual_kwh': actual,
        'deviation_pct': deviation_pct,
        'risk_score': risk_score,
        'severity': severity,
        'anomaly_id': None,
        'alert_id': None,
    }

    # Step 7: Persist anomaly if flagged
    if is_anomaly:
        now = datetime.now().isoformat()
        anomaly_type_str = ','.join(anomaly_types)
        status = 'flagged'

        cursor = db.execute(
            """INSERT INTO anomalies
               (meter_id, reading_id, anomaly_type, expected_kwh, actual_kwh,
                deviation_pct, risk_score, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (meter_id, reading_id, anomaly_type_str, expected, actual,
             deviation_pct, risk_score, status, now)
        )
        anomaly_id = cursor.lastrowid
        result['anomaly_id'] = anomaly_id

        # Step 8: Create alert if risk ≥ 61
        if risk_score >= ALERT_MIN_RISK:
            # Get location for alert message
            loc_cursor = db.execute(
                "SELECT location FROM meters WHERE meter_id = ?", (meter_id,)
            )
            loc_row = loc_cursor.fetchone()
            location = loc_row['location'] if loc_row else 'Unknown'

            message = (
                f"⚠️ {severity} risk ({risk_score}/100) — Meter {meter_id} at {location}: "
                f"{actual:.1f} kWh (expected {expected:.1f} kWh, "
                f"deviation {deviation_pct:+.0f}%). "
                f"Flags: {', '.join(anomaly_types)}."
            )

            cursor = db.execute(
                """INSERT INTO alerts
                   (anomaly_id, meter_id, location, risk_score, severity, message, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (anomaly_id, meter_id, location, risk_score, severity, message, now)
            )
            result['alert_id'] = cursor.lastrowid

        db.commit()

    return result
