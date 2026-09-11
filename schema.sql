-- Watt's Off — Electricity Theft Detection SQLite Schema
-- Dedicated schema for under-consumption theft detection, tamper tracking, and energy balance

CREATE TABLE IF NOT EXISTS transformers (
    transformer_id TEXT PRIMARY KEY,        -- e.g. "DT-01"
    name TEXT NOT NULL,                     -- e.g. "Sector 62 Main DT"
    location TEXT NOT NULL,                 -- e.g. "Sector 62"
    capacity_kva REAL NOT NULL DEFAULT 250.0,
    input_kwh REAL NOT NULL DEFAULT 0.0     -- Feeder-level metered energy input
);

CREATE TABLE IF NOT EXISTS meters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meter_id TEXT UNIQUE NOT NULL,          -- e.g. "M027"
    consumer_name TEXT NOT NULL,
    location TEXT NOT NULL,                  -- e.g. "Sector 62"
    lat REAL NOT NULL,
    lng REAL NOT NULL,
    transformer_id TEXT NOT NULL DEFAULT 'DT-01',
    FOREIGN KEY (transformer_id) REFERENCES transformers(transformer_id)
);

CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meter_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,                 -- ISO 8601
    consumption_kwh REAL NOT NULL,
    hour INTEGER NOT NULL,                   -- 0-23
    season TEXT NOT NULL DEFAULT 'summer',   -- summer/winter/monsoon
    voltage_v REAL DEFAULT 230.0,            -- Line voltage
    current_a REAL DEFAULT 5.0,              -- Line current
    reverse_flow INTEGER DEFAULT 0,          -- 1 if reverse energy flow detected
    FOREIGN KEY (meter_id) REFERENCES meters(meter_id)
);

CREATE TABLE IF NOT EXISTS baselines (
    meter_id TEXT NOT NULL,
    time_bucket TEXT NOT NULL,               -- morning/afternoon/evening/night
    avg_kwh REAL NOT NULL,
    PRIMARY KEY (meter_id, time_bucket),
    FOREIGN KEY (meter_id) REFERENCES meters(meter_id)
);

CREATE TABLE IF NOT EXISTS tamper_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meter_id TEXT NOT NULL,
    event_type TEXT NOT NULL,                -- MAGNETIC_TAMPER, COVER_OPEN, NEUTRAL_BYPASS, REVERSE_CURRENT
    description TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'HIGH',   -- MEDIUM / HIGH / CRITICAL
    timestamp TEXT NOT NULL,                 -- ISO 8601
    FOREIGN KEY (meter_id) REFERENCES meters(meter_id)
);

CREATE TABLE IF NOT EXISTS anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meter_id TEXT NOT NULL,
    reading_id INTEGER NOT NULL,
    anomaly_type TEXT NOT NULL,              -- under_consumption / sudden_drop / tamper / over_consumption
    expected_kwh REAL NOT NULL,
    actual_kwh REAL NOT NULL,
    deviation_pct REAL NOT NULL,             -- ((actual - expected) / expected) * 100
    risk_score INTEGER NOT NULL,             -- 0-100 (Theft Risk Score)
    theft_status TEXT NOT NULL DEFAULT 'NORMAL', -- NORMAL / SUSPICIOUS / HIGH_THEFT_RISK / OVER_CONSUMPTION
    theft_risk_score INTEGER NOT NULL DEFAULT 0, -- 0-100 (0 for OVER_CONSUMPTION and NORMAL)
    theft_signals TEXT DEFAULT '',           -- comma-separated signals: e.g. "under_consumption,sudden_drop,tamper_event"
    status TEXT NOT NULL DEFAULT 'flagged',  -- flagged / inspection_assigned / false_alarm
    created_at TEXT NOT NULL,                -- ISO 8601
    FOREIGN KEY (meter_id) REFERENCES meters(meter_id),
    FOREIGN KEY (reading_id) REFERENCES readings(id)
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anomaly_id INTEGER NOT NULL,
    meter_id TEXT NOT NULL,
    location TEXT NOT NULL,
    risk_score INTEGER NOT NULL,
    severity TEXT NOT NULL,                  -- NORMAL / SUSPICIOUS / HIGH_THEFT_RISK / OVER_CONSUMPTION
    alert_category TEXT NOT NULL DEFAULT 'THEFT', -- THEFT / OVER_CONSUMPTION
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,                -- ISO 8601
    FOREIGN KEY (anomaly_id) REFERENCES anomalies(id),
    FOREIGN KEY (meter_id) REFERENCES meters(meter_id)
);

-- Indexes for lightning-fast queries
CREATE INDEX IF NOT EXISTS idx_readings_meter ON readings(meter_id);
CREATE INDEX IF NOT EXISTS idx_readings_timestamp ON readings(timestamp);
CREATE INDEX IF NOT EXISTS idx_anomalies_meter ON anomalies(meter_id);
CREATE INDEX IF NOT EXISTS idx_anomalies_theft_status ON anomalies(theft_status);
CREATE INDEX IF NOT EXISTS idx_anomalies_theft_risk ON anomalies(theft_risk_score DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
CREATE INDEX IF NOT EXISTS idx_alerts_risk ON alerts(risk_score DESC);
CREATE INDEX IF NOT EXISTS idx_tamper_meter ON tamper_events(meter_id);

-- Citizen Vigilance & Public Power Theft Complaints
CREATE TABLE IF NOT EXISTS complaints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id TEXT UNIQUE NOT NULL,
    complainant_name TEXT DEFAULT 'Anonymous Citizen',
    complainant_phone TEXT,
    google_email TEXT,
    is_anonymous INTEGER DEFAULT 0,
    location TEXT NOT NULL,
    landmark TEXT,
    theft_type TEXT NOT NULL,
    description TEXT,
    photo_filename TEXT,
    status TEXT NOT NULL DEFAULT 'UNDER_INVESTIGATION', -- SUBMITTED, UNDER_INVESTIGATION, DISPATCHED, RESOLVED
    stage INTEGER DEFAULT 2,                           -- 1: Lodged, 2: AI Correlated, 3: Dispatched, 4: Inspected, 5: Resolved
    assigned_team TEXT DEFAULT 'Vigilance Enforcement Squad #2',
    remarks TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_complaints_ticket ON complaints(ticket_id);
CREATE INDEX IF NOT EXISTS idx_complaints_status ON complaints(status);

