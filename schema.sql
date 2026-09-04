-- Watt's Off — SQLite Schema
-- 5 tables: meters, readings, baselines, anomalies, alerts

CREATE TABLE IF NOT EXISTS meters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meter_id TEXT UNIQUE NOT NULL,          -- e.g. "M027"
    consumer_name TEXT NOT NULL,
    location TEXT NOT NULL,                  -- e.g. "Sector 62"
    lat REAL NOT NULL,
    lng REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meter_id TEXT NOT NULL,
    timestamp TEXT NOT NULL,                 -- ISO 8601
    consumption_kwh REAL NOT NULL,
    hour INTEGER NOT NULL,                   -- 0-23
    season TEXT NOT NULL DEFAULT 'summer',   -- summer/winter/monsoon
    FOREIGN KEY (meter_id) REFERENCES meters(meter_id)
);

CREATE TABLE IF NOT EXISTS baselines (
    meter_id TEXT NOT NULL,
    time_bucket TEXT NOT NULL,               -- morning/afternoon/evening/night
    avg_kwh REAL NOT NULL,
    PRIMARY KEY (meter_id, time_bucket),
    FOREIGN KEY (meter_id) REFERENCES meters(meter_id)
);

CREATE TABLE IF NOT EXISTS anomalies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meter_id TEXT NOT NULL,
    reading_id INTEGER NOT NULL,
    anomaly_type TEXT NOT NULL,              -- sudden_spike / unusual_time / repeated_pattern
    expected_kwh REAL NOT NULL,
    actual_kwh REAL NOT NULL,
    deviation_pct REAL NOT NULL,
    risk_score INTEGER NOT NULL,             -- 0-100
    status TEXT NOT NULL DEFAULT 'flagged',  -- normal/flagged/inspection_assigned/false_alarm
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
    severity TEXT NOT NULL,                  -- LOW / MEDIUM / HIGH / CRITICAL
    message TEXT NOT NULL,
    created_at TEXT NOT NULL,                -- ISO 8601
    FOREIGN KEY (anomaly_id) REFERENCES anomalies(id),
    FOREIGN KEY (meter_id) REFERENCES meters(meter_id)
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_readings_meter ON readings(meter_id);
CREATE INDEX IF NOT EXISTS idx_readings_timestamp ON readings(timestamp);
CREATE INDEX IF NOT EXISTS idx_anomalies_meter ON anomalies(meter_id);
CREATE INDEX IF NOT EXISTS idx_anomalies_status ON anomalies(status);
CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts(severity);
CREATE INDEX IF NOT EXISTS idx_alerts_risk ON alerts(risk_score DESC);
