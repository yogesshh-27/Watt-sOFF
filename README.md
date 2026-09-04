# Watt's Off ⚡

**AI-Powered Anomaly Detection for Electricity Theft Monitoring**

A hackathon prototype that ingests meter/billing-style readings, flags abnormal consumption patterns, scores risk, generates alerts, and provides a DISCOM (power distribution company) officer dashboard to investigate and act on them.

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Seed the database with demo data
python simulate.py --seed

# 3. Start the application
python app.py

# 4. Open in browser
# http://localhost:5000
# Login: demo@discom.gov.in / wattsoff
```

### Real-Time Demo Mode

In a second terminal, start the live simulator to generate new readings every 5 seconds:

```bash
python simulate.py --live
```

The dashboard auto-refreshes and shows new anomalies as they're detected.

### Reset Demo Data

```bash
python simulate.py --seed
```

This drops and recreates the database with fresh meters, historical readings, baselines, and pre-injected anomalies.

---

## Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  simulate.py │────▶│  detection.py│────▶│  SQLite DB   │
│  (data gen)  │     │  (analysis)  │     │  (wattsoff.db)│
└──────────────┘     └──────────────┘     └──────┬───────┘
                                                  │
                                           ┌──────┴───────┐
                                           │   app.py     │
                                           │   (Flask API)│
                                           └──────┬───────┘
                                                  │
                                           ┌──────┴───────┐
                                           │   Frontend   │
                                           │ (HTML/CSS/JS)│
                                           └──────────────┘
```

| Component | File | Purpose |
|-----------|------|---------|
| **Data Simulator** | `simulate.py` | Generates fake meters, backfills history, injects anomalies, runs live loop |
| **Detection Engine** | `detection.py` | Per-meter baseline comparison, anomaly classification, risk scoring |
| **Database** | `schema.sql`, `db.py` | SQLite schema (5 tables) and connection helpers |
| **API Server** | `app.py` | Flask REST API (8 endpoints) + static file serving |
| **Frontend** | `static/` | 7-page dark dashboard (HTML/CSS/JS, Chart.js, Leaflet.js) |

---

## Detection Engine — Engineering Trade-Off

> **This prototype uses rule-based/statistical detection instead of KNN/SVM/Random Forest.**

This is a **deliberate engineering trade-off**, not a shortcut:

- **No labeled training data required** — works from each meter's own historical baseline
- **Identical outputs** — deviation %, anomaly type, risk score 0–100
- **Deterministic & explainable** — every flag has a human-readable reason
- **Same function signatures** — internals can be swapped for `sklearn.ensemble.IsolationForest` without changing any other file

See [`NOTES.md`](NOTES.md) for the full rationale.

### Detection Pipeline

1. **`compute_expected()`** — Looks up per-meter, per-time-bucket baseline average
2. **`classify_anomaly()`** — Identifies `sudden_spike`, `unusual_time`, `repeated_pattern`
3. **`score_risk()`** — Weighted composite: deviation(40) + spike(20) + unusual_time(15) + repeated(20) + headroom(5)
4. **`process_reading()`** — Orchestrator: runs 1–3, writes anomaly/alert rows

### Severity Bands

| Score | Severity | Color |
|-------|----------|-------|
| 0–30  | LOW      | 🟢 Green  |
| 31–60 | MEDIUM   | 🟡 Yellow |
| 61–80 | HIGH     | 🟠 Orange |
| 81–100| CRITICAL | 🔴 Red    |

Alerts are auto-created when risk ≥ 61.

---

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/readings` | Ingest one reading → run detection → return result |
| `GET`  | `/api/dashboard/summary` | Dashboard summary stats |
| `GET`  | `/api/meters` | All meters with latest status |
| `GET`  | `/api/meters/<meter_id>` | Full meter detail |
| `GET`  | `/api/meters/<meter_id>/history` | Reading time series (for charts) |
| `GET`  | `/api/alerts` | Active alerts sorted by risk |
| `POST` | `/api/alerts/<id>/action` | `{"action": "inspect"\|"false_alarm"}` |
| `GET`  | `/api/map` | Meters with lat/lng + severity |

---

## Frontend Pages

1. **Login** — Mock auth (demo@discom.gov.in / wattsoff)
2. **Dashboard** — Summary cards, live chart, high-risk table, alert feed
3. **Consumption Analysis** — Actual vs. expected line chart per meter
4. **Alerts** — Full alert list with severity filtering
5. **Map** — Leaflet.js map with severity-colored markers
6. **Meter Detail** — Investigation view with risk gauge, why-flagged checklist, action buttons
7. **Officer Actions** — Send for Inspection / Mark as False Alarm (on Meter Detail page)

---

## Project Structure

```
wattsoff/
├── app.py              # Flask app (API + static serving)
├── db.py               # SQLite helpers
├── detection.py        # Anomaly detection engine
├── simulate.py         # Data generator (seed + live mode)
├── test_detection.py   # Assert-based tests
├── schema.sql          # Database DDL
├── requirements.txt    # flask, flask-cors
├── NOTES.md            # Detection engine trade-off explanation
├── README.md           # This file
├── wattsoff.db         # SQLite database (generated)
└── static/
    ├── style.css        # Dark dashboard theme
    ├── login.html
    ├── dashboard.html
    ├── meter_detail.html
    ├── alerts.html
    ├── analysis.html
    └── map.html
```

---

## Tests

```bash
python test_detection.py
```

Runs 4 assert-based tests against worked examples from the project brief:
- Time bucket mapping
- Deviation calculation (expected 2.5, actual 9.2 → 268%)
- Anomaly classification (spike, unusual time, repeated pattern, normal)
- Risk scoring (M027 scenario → ~95 CRITICAL)

---

## Stretch Goal

Swap `classify_anomaly()` and `score_risk()` internals for `sklearn.ensemble.IsolationForest` (unsupervised — no labeled data needed), keeping the same function signatures so nothing else changes. Only attempt after the rule-based version fully works.
