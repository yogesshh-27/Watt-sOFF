"""
simulate.py — Data simulator for Watt's Off.

Generates fake meter data, backfills historical readings, computes baselines,
and injects deliberate anomalies for demo purposes.

Usage:
    python simulate.py --seed     # Reset DB and populate with demo data
    python simulate.py --live     # Append one reading every 5 seconds (real-time loop)
    python simulate.py            # Same as --seed
"""

import random
import time
import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_db, reset_db, init_db
from detection import process_reading, get_time_bucket

# ---------------------------------------------------------------------------
# Meter definitions — 12 meters across named locations
# ---------------------------------------------------------------------------

METERS = [
    {'meter_id': 'M001', 'consumer_name': 'Raj Kumar Sharma',     'location': 'Sector 62',     'lat': 28.6278, 'lng': 77.3640},
    {'meter_id': 'M005', 'consumer_name': 'Priya Electronics',    'location': 'MG Road',       'lat': 28.6325, 'lng': 77.2195},
    {'meter_id': 'M009', 'consumer_name': 'Vikram Singh',         'location': 'Civil Lines',   'lat': 28.6800, 'lng': 77.2250},
    {'meter_id': 'M012', 'consumer_name': 'Anita Cold Storage',   'location': 'Industrial Area','lat': 28.5900, 'lng': 77.3100},
    {'meter_id': 'M014', 'consumer_name': 'Suresh Textiles',      'location': 'Karol Bagh',    'lat': 28.6519, 'lng': 77.1905},
    {'meter_id': 'M018', 'consumer_name': 'Meera Apartments',     'location': 'Dwarka Sec 7',  'lat': 28.5815, 'lng': 77.0620},
    {'meter_id': 'M021', 'consumer_name': 'Patel & Sons Workshop','location': 'Lajpat Nagar',  'lat': 28.5700, 'lng': 77.2400},
    {'meter_id': 'M025', 'consumer_name': 'Green Valley School',  'location': 'Vasant Kunj',   'lat': 28.5190, 'lng': 77.1570},
    {'meter_id': 'M027', 'consumer_name': 'Deepak Grocery Store', 'location': 'Sector 62',     'lat': 28.6290, 'lng': 77.3660},
    {'meter_id': 'M031', 'consumer_name': 'Gupta Residence',      'location': 'Rohini Sec 3',  'lat': 28.7150, 'lng': 77.1100},
    {'meter_id': 'M034', 'consumer_name': 'Star Hospital',        'location': 'Saket',         'lat': 28.5244, 'lng': 77.2066},
    {'meter_id': 'M038', 'consumer_name': 'Lakshmi Dairy',        'location': 'Chandni Chowk', 'lat': 28.6506, 'lng': 77.2300},
]

# Consumption profiles (kWh) — per-meter base patterns by time bucket
# Each meter gets a unique profile to avoid global-threshold problems.
CONSUMPTION_PROFILES = {
    'M001': {'morning': 2.0, 'afternoon': 1.8, 'evening': 3.0, 'night': 0.5},   # residential
    'M005': {'morning': 4.5, 'afternoon': 5.0, 'evening': 4.0, 'night': 0.8},   # electronics shop
    'M009': {'morning': 1.5, 'afternoon': 1.2, 'evening': 2.5, 'night': 0.3},   # residential
    'M012': {'morning': 8.0, 'afternoon': 9.0, 'evening': 7.0, 'night': 3.0},   # cold storage (24/7)
    'M014': {'morning': 3.5, 'afternoon': 4.0, 'evening': 2.0, 'night': 0.4},   # textiles factory
    'M018': {'morning': 3.0, 'afternoon': 2.5, 'evening': 4.5, 'night': 1.0},   # apartments
    'M021': {'morning': 2.5, 'afternoon': 3.5, 'evening': 2.0, 'night': 0.3},   # workshop
    'M025': {'morning': 5.0, 'afternoon': 4.0, 'evening': 1.5, 'night': 0.5},   # school
    'M027': {'morning': 2.5, 'afternoon': 2.8, 'evening': 3.2, 'night': 0.6},   # grocery store
    'M031': {'morning': 1.8, 'afternoon': 1.5, 'evening': 2.8, 'night': 0.4},   # residential
    'M034': {'morning': 7.0, 'afternoon': 8.5, 'evening': 7.5, 'night': 5.0},   # hospital (24/7)
    'M038': {'morning': 3.0, 'afternoon': 3.5, 'evening': 2.5, 'night': 0.3},   # dairy shop
}

# Noise factor — ±15% random variation for realistic readings
NOISE_FACTOR = 0.15

BACKFILL_DAYS = 5
READINGS_PER_DAY = 24  # one reading per hour


def add_noise(base_kwh):
    """Add realistic random noise (±15%) to a base consumption value."""
    noise = random.uniform(-NOISE_FACTOR, NOISE_FACTOR)
    return max(0.1, round(base_kwh * (1 + noise), 2))


def get_season_from_date(dt):
    """Determine season from date (Indian climate)."""
    month = dt.month
    if month in (6, 7, 8, 9):
        return 'monsoon'
    elif month in (11, 12, 1, 2):
        return 'winter'
    else:
        return 'summer'


# ---------------------------------------------------------------------------
# Seed functions
# ---------------------------------------------------------------------------

def seed_meters(db):
    """Insert all 12 meters into the database."""
    for m in METERS:
        db.execute(
            """INSERT OR IGNORE INTO meters (meter_id, consumer_name, location, lat, lng)
               VALUES (?, ?, ?, ?, ?)""",
            (m['meter_id'], m['consumer_name'], m['location'], m['lat'], m['lng'])
        )
    db.commit()
    print(f"[simulate] Inserted {len(METERS)} meters")


def seed_historical_readings(db):
    """
    Backfill 5 days of hourly normal readings per meter.
    Uses each meter's own consumption profile with noise.
    """
    now = datetime.now()
    start = now - timedelta(days=BACKFILL_DAYS)
    count = 0

    for meter in METERS:
        mid = meter['meter_id']
        profile = CONSUMPTION_PROFILES[mid]
        current = start

        while current < now - timedelta(hours=2):  # leave last 2 hours for anomaly injection
            hour = current.hour
            bucket = get_time_bucket(hour)
            base_kwh = profile[bucket]
            reading_kwh = add_noise(base_kwh)
            season = get_season_from_date(current)

            db.execute(
                """INSERT INTO readings (meter_id, timestamp, consumption_kwh, hour, season)
                   VALUES (?, ?, ?, ?, ?)""",
                (mid, current.isoformat(), reading_kwh, hour, season)
            )
            current += timedelta(hours=1)
            count += 1

    db.commit()
    print(f"[simulate] Inserted {count} historical readings ({BACKFILL_DAYS} days × {len(METERS)} meters)")


def compute_baselines(db):
    """
    Precompute per-meter, per-time-bucket average consumption from historical readings.
    This populates the baselines table that detection.py's compute_expected() uses.
    """
    buckets = {
        'morning':   (6, 11),
        'afternoon': (12, 16),
        'evening':   (17, 21),
    }
    count = 0

    for meter in METERS:
        mid = meter['meter_id']

        # Night is special: wraps around midnight (22-23, 0-5)
        cursor = db.execute(
            """SELECT AVG(consumption_kwh) as avg_kwh FROM readings
               WHERE meter_id = ? AND (hour >= 22 OR hour <= 5)""",
            (mid,)
        )
        row = cursor.fetchone()
        avg = row['avg_kwh'] if row and row['avg_kwh'] else CONSUMPTION_PROFILES[mid]['night']
        db.execute(
            "INSERT OR REPLACE INTO baselines (meter_id, time_bucket, avg_kwh) VALUES (?, ?, ?)",
            (mid, 'night', round(avg, 2))
        )
        count += 1

        # Other buckets
        for bucket_name, (h_start, h_end) in buckets.items():
            cursor = db.execute(
                """SELECT AVG(consumption_kwh) as avg_kwh FROM readings
                   WHERE meter_id = ? AND hour >= ? AND hour <= ?""",
                (mid, h_start, h_end)
            )
            row = cursor.fetchone()
            avg = row['avg_kwh'] if row and row['avg_kwh'] else CONSUMPTION_PROFILES[mid][bucket_name]
            db.execute(
                "INSERT OR REPLACE INTO baselines (meter_id, time_bucket, avg_kwh) VALUES (?, ?, ?)",
                (mid, bucket_name, round(avg, 2))
            )
            count += 1

    db.commit()
    print(f"[simulate] Computed {count} baseline values ({len(METERS)} meters × 4 buckets)")


def inject_anomalies(db):
    """
    Inject deliberate anomalies so the demo has visible flagged meters immediately.

    Scenarios:
    1. M027 (Sector 62) — The brief's worked example: builds up 3 prior anomalous
       readings (to trigger repeated_pattern), then a dramatic spike to 9.2 kWh
       → risk ~95, CRITICAL.
    2. M014 (Karol Bagh) — Unusual nighttime: 5.5 kWh at 2 AM → HIGH
    3. M009 (Civil Lines) — Repeated pattern: 4 anomalies in recent readings → HIGH/CRITICAL
    4. M005 (MG Road)    — Moderate spike for visual variety → MEDIUM
    """
    now = datetime.now()
    season = get_season_from_date(now)

    print("[simulate] Injecting deliberate anomalies...")

    # --- Anomaly 1: M027 — build repeated history THEN the dramatic spike ---
    # Insert 3 prior anomalous readings to build up the repeated_pattern flag
    for i in range(3):
        ts_prior = (now - timedelta(minutes=90 - i * 15)).isoformat()
        prior_kwh = random.uniform(6.5, 8.0)  # clearly anomalous vs ~2.5 expected
        cursor = db.execute(
            "INSERT INTO readings (meter_id, timestamp, consumption_kwh, hour, season) VALUES (?, ?, ?, ?, ?)",
            ('M027', ts_prior, prior_kwh, now.hour, season)
        )
        rid = cursor.lastrowid
        db.commit()
        process_reading({
            'meter_id': 'M027',
            'consumption_kwh': prior_kwh,
            'hour': now.hour,
            'timestamp': ts_prior,
            'reading_id': rid,
        }, db)

    # Now insert the normal reading just before the big spike
    ts_normal = (now - timedelta(minutes=30)).isoformat()
    db.execute(
        "INSERT INTO readings (meter_id, timestamp, consumption_kwh, hour, season) VALUES (?, ?, ?, ?, ?)",
        ('M027', ts_normal, 2.5, now.hour, season)
    )
    db.commit()

    # THE BIG SPIKE — 9.2 kWh, the brief's exact worked example
    ts_spike = (now - timedelta(minutes=15)).isoformat()
    cursor = db.execute(
        "INSERT INTO readings (meter_id, timestamp, consumption_kwh, hour, season) VALUES (?, ?, ?, ?, ?)",
        ('M027', ts_spike, 9.2, now.hour, season)
    )
    spike_reading_id = cursor.lastrowid
    db.commit()

    result = process_reading({
        'meter_id': 'M027',
        'consumption_kwh': 9.2,
        'hour': now.hour,
        'timestamp': ts_spike,
        'reading_id': spike_reading_id,
    }, db)
    print(f"  -> M027 spike: risk={result['risk_score']}, severity={result['severity']}, "
          f"types={result['anomaly_types']}")

    # --- Anomaly 2: M014 unusual nighttime usage ---
    ts_night = (now - timedelta(minutes=20)).isoformat()
    cursor = db.execute(
        "INSERT INTO readings (meter_id, timestamp, consumption_kwh, hour, season) VALUES (?, ?, ?, ?, ?)",
        ('M014', ts_night, 5.5, 2, season)  # 2 AM
    )
    night_reading_id = cursor.lastrowid
    db.commit()

    result = process_reading({
        'meter_id': 'M014',
        'consumption_kwh': 5.5,
        'hour': 2,
        'timestamp': ts_night,
        'reading_id': night_reading_id,
    }, db)
    print(f"  -> M014 night: risk={result['risk_score']}, severity={result['severity']}, "
          f"types={result['anomaly_types']}")

    # --- Anomaly 3: M009 repeated pattern (4 anomalies) ---
    for i in range(4):
        ts = (now - timedelta(minutes=60 - i * 10)).isoformat()
        high_kwh = random.uniform(5.0, 7.0)
        cursor = db.execute(
            "INSERT INTO readings (meter_id, timestamp, consumption_kwh, hour, season) VALUES (?, ?, ?, ?, ?)",
            ('M009', ts, high_kwh, 10, season)
        )
        rid = cursor.lastrowid
        db.commit()
        result = process_reading({
            'meter_id': 'M009',
            'consumption_kwh': high_kwh,
            'hour': 10,
            'timestamp': ts,
            'reading_id': rid,
        }, db)
        if i == 3:
            print(f"  -> M009 repeated: risk={result['risk_score']}, severity={result['severity']}, "
                  f"types={result['anomaly_types']}")

    # --- Anomaly 4: M005 moderate spike ---
    ts_mod = (now - timedelta(minutes=10)).isoformat()
    cursor = db.execute(
        "INSERT INTO readings (meter_id, timestamp, consumption_kwh, hour, season) VALUES (?, ?, ?, ?, ?)",
        ('M005', ts_mod, 12.0, 14, season)
    )
    mod_rid = cursor.lastrowid
    db.commit()
    result = process_reading({
        'meter_id': 'M005',
        'consumption_kwh': 12.0,
        'hour': 14,
        'timestamp': ts_mod,
        'reading_id': mod_rid,
    }, db)
    print(f"  -> M005 moderate: risk={result['risk_score']}, severity={result['severity']}, "
          f"types={result['anomaly_types']}")

    print("[simulate] Anomaly injection complete")


def seed_database():
    """Full database reset and seed — the --seed workflow."""
    print("\n⚡ Watt's Off — Database Seeding\n" + "=" * 40)
    reset_db()
    db = get_db()

    seed_meters(db)
    seed_historical_readings(db)
    compute_baselines(db)
    inject_anomalies(db)

    # Print summary
    cursor = db.execute("SELECT COUNT(*) as cnt FROM readings")
    print(f"\n📊 Summary:")
    print(f"  Meters:    {len(METERS)}")
    print(f"  Readings:  {cursor.fetchone()['cnt']}")
    cursor = db.execute("SELECT COUNT(*) as cnt FROM anomalies")
    print(f"  Anomalies: {cursor.fetchone()['cnt']}")
    cursor = db.execute("SELECT COUNT(*) as cnt FROM alerts")
    print(f"  Alerts:    {cursor.fetchone()['cnt']}")
    cursor = db.execute("SELECT COUNT(*) as cnt FROM baselines")
    print(f"  Baselines: {cursor.fetchone()['cnt']}")

    db.close()
    print("\n✅ Database seeded successfully!\n")


# ---------------------------------------------------------------------------
# Live mode — append readings every 5 seconds
# ---------------------------------------------------------------------------

def live_simulation():
    """
    Continuously generate new readings every 5 seconds.
    Occasionally injects an anomaly (~15% chance) to simulate ongoing theft detection.
    """
    print("\n⚡ Watt's Off — Live Simulation Mode")
    print("=" * 40)
    print("Generating a new reading every 5 seconds...")
    print("Press Ctrl+C to stop.\n")

    init_db()
    db = get_db()

    # Verify meters exist
    cursor = db.execute("SELECT COUNT(*) as cnt FROM meters")
    if cursor.fetchone()['cnt'] == 0:
        print("❌ No meters found. Run 'python simulate.py --seed' first.")
        return

    meter_ids = [m['meter_id'] for m in METERS]
    iteration = 0

    try:
        while True:
            iteration += 1
            meter_id = random.choice(meter_ids)
            now = datetime.now()
            hour = now.hour
            bucket = get_time_bucket(hour)
            profile = CONSUMPTION_PROFILES[meter_id]
            season = get_season_from_date(now)

            # Decide whether to inject an anomaly (~15% chance)
            is_anomalous = random.random() < 0.15
            if is_anomalous:
                # Generate an anomalous reading (2x–4x normal)
                base = profile[bucket]
                consumption = round(base * random.uniform(2.5, 4.5), 2)
            else:
                # Normal reading with noise
                consumption = add_noise(profile[bucket])

            # Insert reading
            cursor = db.execute(
                "INSERT INTO readings (meter_id, timestamp, consumption_kwh, hour, season) VALUES (?, ?, ?, ?, ?)",
                (meter_id, now.isoformat(), consumption, hour, season)
            )
            reading_id = cursor.lastrowid
            db.commit()

            # Run detection
            result = process_reading({
                'meter_id': meter_id,
                'consumption_kwh': consumption,
                'hour': hour,
                'timestamp': now.isoformat(),
                'reading_id': reading_id,
            }, db)

            # Log
            status_icon = '🔴' if result['severity'] == 'CRITICAL' else \
                          '🟠' if result['severity'] == 'HIGH' else \
                          '🟡' if result['severity'] == 'MEDIUM' else '🟢'
            anomaly_str = f"ANOMALY {result['anomaly_types']}" if result['is_anomaly'] else "normal"
            print(f"  [{iteration:04d}] {status_icon} {meter_id} | {consumption:.2f} kWh "
                  f"(expected {result['expected_kwh']:.2f}) | "
                  f"deviation {result['deviation_pct']:+.0f}% | "
                  f"risk {result['risk_score']} | {anomaly_str}")

            time.sleep(5)

    except KeyboardInterrupt:
        print("\n\n🛑 Live simulation stopped.")
        db.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    if '--live' in sys.argv:
        live_simulation()
    else:
        seed_database()
