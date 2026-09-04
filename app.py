"""
app.py — Flask application for Watt's Off.

Serves the REST API and static frontend from a single origin.
Start with: python app.py

API Endpoints:
    POST /api/readings                 - Ingest one reading, run detection
    GET  /api/dashboard/summary        - Dashboard summary statistics
    GET  /api/meters                   - List all meters with latest status
    GET  /api/meters/<meter_id>        - Full meter detail
    GET  /api/meters/<meter_id>/history - Reading history for charts
    GET  /api/alerts                   - Active alerts sorted by risk desc
    POST /api/alerts/<id>/action       - Update alert status (inspect/false_alarm)
    GET  /api/map                      - Meters with lat/lng and status for map
"""

import os
import sys
import threading
from datetime import datetime
from flask import Flask, jsonify, request, send_from_directory, redirect
from flask_cors import CORS

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_db, init_db, IS_VERCEL, DB_PATH
from detection import process_reading, get_severity, compute_expected, compute_deviation

app = Flask(__name__, static_folder='static', static_url_path='/static')
CORS(app)


# ---------------------------------------------------------------------------
# Auto-seed on Vercel cold start (DB lives in /tmp, gets wiped periodically)
# ---------------------------------------------------------------------------

def ensure_seeded():
    """Auto-seed the database if it doesn't exist (Vercel cold start)."""
    if not os.path.exists(DB_PATH):
        init_db()
        # Import and run the seeder
        from simulate import seed_meters, seed_historical_readings, compute_baselines, inject_anomalies
        db = get_db()
        seed_meters(db)
        seed_historical_readings(db)
        compute_baselines(db)
        inject_anomalies(db)
        db.close()


@app.before_request
def before_request():
    """Ensure DB is seeded before handling any request."""
    ensure_seeded()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def row_to_dict(row):
    """Convert a sqlite3.Row to a plain dict."""
    if row is None:
        return None
    return dict(row)


def rows_to_list(rows):
    """Convert a list of sqlite3.Row objects to a list of dicts."""
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Static file serving — serve frontend from /static/
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    """Redirect root to login page."""
    return redirect('/static/login.html')


# ---------------------------------------------------------------------------
# API: Readings
# ---------------------------------------------------------------------------

@app.route('/api/readings', methods=['POST'])
def post_reading():
    """
    Ingest one meter reading, run anomaly detection, return result.

    Body: {
        "meter_id": "M027",
        "consumption_kwh": 9.2,
        "hour": 14,
        "timestamp": "2026-09-04T14:30:00"  (optional, defaults to now)
    }
    """
    data = request.get_json()
    if not data or 'meter_id' not in data or 'consumption_kwh' not in data:
        return jsonify({'error': 'meter_id and consumption_kwh are required'}), 400

    meter_id = data['meter_id']
    consumption = float(data['consumption_kwh'])
    hour = data.get('hour', datetime.now().hour)
    timestamp = data.get('timestamp', datetime.now().isoformat())

    db = get_db()

    # Verify meter exists
    meter = db.execute("SELECT * FROM meters WHERE meter_id = ?", (meter_id,)).fetchone()
    if not meter:
        db.close()
        return jsonify({'error': f'Meter {meter_id} not found'}), 404

    # Insert reading
    cursor = db.execute(
        "INSERT INTO readings (meter_id, timestamp, consumption_kwh, hour, season) VALUES (?, ?, ?, ?, ?)",
        (meter_id, timestamp, consumption, hour, 'summer')
    )
    reading_id = cursor.lastrowid
    db.commit()

    # Run detection
    result = process_reading({
        'meter_id': meter_id,
        'consumption_kwh': consumption,
        'hour': hour,
        'timestamp': timestamp,
        'reading_id': reading_id,
    }, db)

    db.close()
    return jsonify(result), 201


# ---------------------------------------------------------------------------
# API: Dashboard Summary
# ---------------------------------------------------------------------------

@app.route('/api/dashboard/summary')
def dashboard_summary():
    """
    Returns dashboard summary stats:
    total meters, normal count, anomaly count, high-risk count.
    """
    db = get_db()

    total_meters = db.execute("SELECT COUNT(*) as cnt FROM meters").fetchone()['cnt']

    # Get meters that have anomalies with status 'flagged'
    anomaly_meters = db.execute(
        """SELECT COUNT(DISTINCT meter_id) as cnt FROM anomalies
           WHERE status = 'flagged'"""
    ).fetchone()['cnt']

    high_risk_meters = db.execute(
        """SELECT COUNT(DISTINCT meter_id) as cnt FROM anomalies
           WHERE status = 'flagged' AND risk_score >= 61"""
    ).fetchone()['cnt']

    normal_meters = total_meters - anomaly_meters

    # Recent alerts (last 10)
    recent_alerts = rows_to_list(db.execute(
        """SELECT * FROM alerts ORDER BY created_at DESC LIMIT 10"""
    ).fetchall())

    # High-risk meters for the table
    high_risk_list = rows_to_list(db.execute(
        """SELECT a.meter_id, m.location, m.consumer_name,
                  a.actual_kwh, a.expected_kwh, a.deviation_pct,
                  a.risk_score, a.anomaly_type, a.status,
                  a.created_at
           FROM anomalies a
           JOIN meters m ON a.meter_id = m.meter_id
           WHERE a.status = 'flagged' AND a.risk_score >= 61
           ORDER BY a.risk_score DESC
           LIMIT 10"""
    ).fetchall())

    db.close()

    return jsonify({
        'total_meters': total_meters,
        'normal_meters': max(0, normal_meters),
        'anomaly_meters': anomaly_meters,
        'high_risk_meters': high_risk_meters,
        'recent_alerts': recent_alerts,
        'high_risk_list': high_risk_list,
    })


# ---------------------------------------------------------------------------
# API: Meters
# ---------------------------------------------------------------------------

@app.route('/api/meters')
def list_meters():
    """List all meters with their latest reading and status."""
    db = get_db()
    meters = rows_to_list(db.execute("SELECT * FROM meters").fetchall())

    for meter in meters:
        mid = meter['meter_id']

        # Latest reading
        latest = db.execute(
            "SELECT * FROM readings WHERE meter_id = ? ORDER BY id DESC LIMIT 1",
            (mid,)
        ).fetchone()

        if latest:
            meter['latest_reading'] = row_to_dict(latest)
            expected = compute_expected(mid, latest['hour'], db)
            meter['expected_kwh'] = round(expected, 2)
            meter['deviation_pct'] = compute_deviation(latest['consumption_kwh'], expected)
        else:
            meter['latest_reading'] = None
            meter['expected_kwh'] = None
            meter['deviation_pct'] = 0

        # Latest anomaly status
        anomaly = db.execute(
            "SELECT * FROM anomalies WHERE meter_id = ? ORDER BY id DESC LIMIT 1",
            (mid,)
        ).fetchone()

        if anomaly and anomaly['status'] == 'flagged':
            meter['status'] = 'flagged'
            meter['risk_score'] = anomaly['risk_score']
            meter['severity'] = get_severity(anomaly['risk_score'])
            meter['anomaly_type'] = anomaly['anomaly_type']
        else:
            meter['status'] = anomaly['status'] if anomaly else 'normal'
            meter['risk_score'] = anomaly['risk_score'] if anomaly else 0
            meter['severity'] = get_severity(anomaly['risk_score']) if anomaly else 'LOW'
            meter['anomaly_type'] = None

    db.close()
    return jsonify(meters)


@app.route('/api/meters/<meter_id>')
def get_meter(meter_id):
    """
    Full meter detail: current vs expected, deviation, why-flagged reasons.
    """
    db = get_db()

    meter = db.execute("SELECT * FROM meters WHERE meter_id = ?", (meter_id,)).fetchone()
    if not meter:
        db.close()
        return jsonify({'error': f'Meter {meter_id} not found'}), 404

    result = row_to_dict(meter)

    # Latest reading
    latest = db.execute(
        "SELECT * FROM readings WHERE meter_id = ? ORDER BY id DESC LIMIT 1",
        (meter_id,)
    ).fetchone()

    if latest:
        result['latest_reading'] = row_to_dict(latest)
        expected = compute_expected(meter_id, latest['hour'], db)
        result['expected_kwh'] = round(expected, 2)
        result['actual_kwh'] = latest['consumption_kwh']
        result['deviation_pct'] = compute_deviation(latest['consumption_kwh'], expected)
    else:
        result['latest_reading'] = None
        result['expected_kwh'] = None
        result['actual_kwh'] = None
        result['deviation_pct'] = 0

    # Latest anomaly with full detail
    anomaly = db.execute(
        "SELECT * FROM anomalies WHERE meter_id = ? ORDER BY id DESC LIMIT 1",
        (meter_id,)
    ).fetchone()

    if anomaly:
        result['anomaly'] = row_to_dict(anomaly)
        result['status'] = anomaly['status']
        result['risk_score'] = anomaly['risk_score']
        result['severity'] = get_severity(anomaly['risk_score'])
        # Parse anomaly types for "why flagged" checklist
        types = anomaly['anomaly_type'].split(',') if anomaly['anomaly_type'] else []
        result['why_flagged'] = {
            'sudden_spike': 'sudden_spike' in types,
            'unusual_time': 'unusual_time' in types,
            'repeated_pattern': 'repeated_pattern' in types,
        }
    else:
        result['anomaly'] = None
        result['status'] = 'normal'
        result['risk_score'] = 0
        result['severity'] = 'LOW'
        result['why_flagged'] = {
            'sudden_spike': False,
            'unusual_time': False,
            'repeated_pattern': False,
        }

    # Related alert (for action buttons)
    alert = db.execute(
        "SELECT * FROM alerts WHERE meter_id = ? ORDER BY id DESC LIMIT 1",
        (meter_id,)
    ).fetchone()
    result['alert'] = row_to_dict(alert) if alert else None

    db.close()
    return jsonify(result)


@app.route('/api/meters/<meter_id>/history')
def meter_history(meter_id):
    """
    Reading history for a meter — for the actual-vs-expected chart.
    Returns the last 72 readings (3 days of hourly data).
    """
    db = get_db()

    readings = rows_to_list(db.execute(
        """SELECT id, meter_id, timestamp, consumption_kwh, hour, season
           FROM readings WHERE meter_id = ?
           ORDER BY id DESC LIMIT 72""",
        (meter_id,)
    ).fetchall())

    # Reverse to chronological order
    readings.reverse()

    # Add expected values for each reading
    for r in readings:
        r['expected_kwh'] = round(compute_expected(meter_id, r['hour'], db), 2)

    db.close()
    return jsonify(readings)


# ---------------------------------------------------------------------------
# API: Alerts
# ---------------------------------------------------------------------------

@app.route('/api/alerts')
def list_alerts():
    """List all alerts, sorted by risk score descending."""
    db = get_db()
    alerts = rows_to_list(db.execute(
        """SELECT al.*, an.status as anomaly_status, an.anomaly_type,
                  an.actual_kwh, an.expected_kwh, an.deviation_pct,
                  m.consumer_name
           FROM alerts al
           JOIN anomalies an ON al.anomaly_id = an.id
           JOIN meters m ON al.meter_id = m.meter_id
           ORDER BY al.risk_score DESC"""
    ).fetchall())
    db.close()
    return jsonify(alerts)


@app.route('/api/alerts/<int:alert_id>/action', methods=['POST'])
def alert_action(alert_id):
    """
    Update an alert's associated anomaly status.
    Body: {"action": "inspect"} or {"action": "false_alarm"}
    """
    data = request.get_json()
    if not data or 'action' not in data:
        return jsonify({'error': 'action is required (inspect or false_alarm)'}), 400

    action = data['action']
    if action not in ('inspect', 'false_alarm'):
        return jsonify({'error': 'action must be "inspect" or "false_alarm"'}), 400

    new_status = 'inspection_assigned' if action == 'inspect' else 'false_alarm'

    db = get_db()

    # Get the alert
    alert = db.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    if not alert:
        db.close()
        return jsonify({'error': f'Alert {alert_id} not found'}), 404

    # Update anomaly status
    db.execute(
        "UPDATE anomalies SET status = ? WHERE id = ?",
        (new_status, alert['anomaly_id'])
    )
    db.commit()

    db.close()
    return jsonify({
        'success': True,
        'alert_id': alert_id,
        'new_status': new_status,
        'message': f'Alert {alert_id} marked as {new_status}'
    })


# ---------------------------------------------------------------------------
# API: Map data
# ---------------------------------------------------------------------------

@app.route('/api/map')
def map_data():
    """
    Meters with lat/lng + status/severity, for the map page.
    """
    db = get_db()
    meters = rows_to_list(db.execute("SELECT * FROM meters").fetchall())

    for meter in meters:
        mid = meter['meter_id']

        # Latest anomaly for status/severity
        anomaly = db.execute(
            "SELECT * FROM anomalies WHERE meter_id = ? ORDER BY id DESC LIMIT 1",
            (mid,)
        ).fetchone()

        if anomaly and anomaly['status'] == 'flagged':
            meter['status'] = 'flagged'
            meter['risk_score'] = anomaly['risk_score']
            meter['severity'] = get_severity(anomaly['risk_score'])
            meter['anomaly_type'] = anomaly['anomaly_type']
        else:
            meter['status'] = anomaly['status'] if anomaly else 'normal'
            meter['risk_score'] = anomaly['risk_score'] if anomaly else 0
            meter['severity'] = get_severity(anomaly['risk_score']) if anomaly else 'LOW'
            meter['anomaly_type'] = None

    db.close()
    return jsonify(meters)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

# Vercel uses this as the WSGI app entry point
application = app

if __name__ == '__main__':
    init_db()
    print("\n" + "=" * 50)
    print("  Watt's Off — AI Anomaly Detection Dashboard")
    print("  http://localhost:5000")
    print("=" * 50 + "\n")
    app.run(debug=True, port=5000, use_reloader=False)
