"""
simulate.py — Data simulator for Watt's Off Electricity Theft Detection Platform.

Seeds realistic meters, historical profiles, tamper events, transformer energy balance,
and authentic under-consumption electricity theft scenarios.

Usage:
    python simulate.py --seed     # Reset DB and populate with demo theft data
    python simulate.py --live     # Real-time simulation loop (appends reading every 5s)
    python simulate.py            # Same as --seed
"""

import random
import time
import sys
import os
from datetime import datetime, timedelta

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_db, reset_db, init_db
from detection import process_reading, get_time_bucket

# ---------------------------------------------------------------------------
# Transformer Definitions (Distribution Transformers / DTs)
# ---------------------------------------------------------------------------

TRANSFORMERS = [
    {'transformer_id': 'DT-01', 'name': 'Sector 62 Substation DT',   'location': 'Sector 62',     'capacity_kva': 250.0},
    {'transformer_id': 'DT-02', 'name': 'Civil Lines Feeder DT',     'location': 'Civil Lines',   'capacity_kva': 160.0},
    {'transformer_id': 'DT-03', 'name': 'Industrial Estate DT',       'location': 'Industrial Area','capacity_kva': 400.0},
    {'transformer_id': 'DT-04', 'name': 'Karol Bagh Commercial DT',  'location': 'Karol Bagh',    'capacity_kva': 200.0},
    {'transformer_id': 'DT-05', 'name': 'Dwarka-Vasant DT',          'location': 'Dwarka Sec 7',  'capacity_kva': 315.0},
    {'transformer_id': 'DT-06', 'name': 'MG Road Market DT',         'location': 'MG Road',       'capacity_kva': 250.0},
    {'transformer_id': 'DT-07', 'name': 'Old Delhi Central DT',      'location': 'Chandni Chowk', 'capacity_kva': 315.0},
]

# ---------------------------------------------------------------------------
# Meter Definitions (Mapped to Transformers)
# ---------------------------------------------------------------------------

METERS = [
    {'meter_id': 'M001', 'consumer_name': 'Raj Kumar Sharma',     'location': 'Sector 62',     'lat': 28.6278, 'lng': 77.3640, 'transformer_id': 'DT-01'},
    {'meter_id': 'M027', 'consumer_name': 'Deepak Grocery Store', 'location': 'Sector 62',     'lat': 28.6290, 'lng': 77.3660, 'transformer_id': 'DT-01'},
    {'meter_id': 'M009', 'consumer_name': 'Vikram Singh',         'location': 'Civil Lines',   'lat': 28.6800, 'lng': 77.2250, 'transformer_id': 'DT-02'},
    {'meter_id': 'M012', 'consumer_name': 'Anita Cold Storage',   'location': 'Industrial Area','lat': 28.5900, 'lng': 77.3100, 'transformer_id': 'DT-03'},
    {'meter_id': 'M014', 'consumer_name': 'Suresh Textiles',      'location': 'Karol Bagh',    'lat': 28.6519, 'lng': 77.1905, 'transformer_id': 'DT-04'},
    {'meter_id': 'M018', 'consumer_name': 'Meera Apartments',     'location': 'Dwarka Sec 7',  'lat': 28.5815, 'lng': 77.0620, 'transformer_id': 'DT-05'},
    {'meter_id': 'M025', 'consumer_name': 'Green Valley School',  'location': 'Vasant Kunj',   'lat': 28.5190, 'lng': 77.1570, 'transformer_id': 'DT-05'},
    {'meter_id': 'M005', 'consumer_name': 'Priya Electronics',    'location': 'MG Road',       'lat': 28.6325, 'lng': 77.2195, 'transformer_id': 'DT-06'},
    {'meter_id': 'M021', 'consumer_name': 'Patel & Sons Workshop','location': 'Lajpat Nagar',  'lat': 28.5700, 'lng': 77.2400, 'transformer_id': 'DT-06'},
    {'meter_id': 'M031', 'consumer_name': 'Gupta Residence',      'location': 'Rohini Sec 3',  'lat': 28.7150, 'lng': 77.1100, 'transformer_id': 'DT-07'},
    {'meter_id': 'M034', 'consumer_name': 'Star Hospital',        'location': 'Saket',         'lat': 28.5244, 'lng': 77.2066, 'transformer_id': 'DT-07'},
    {'meter_id': 'M038', 'consumer_name': 'Lakshmi Dairy',        'location': 'Chandni Chowk', 'lat': 28.6506, 'lng': 77.2300, 'transformer_id': 'DT-07'},
]

# Expected consumption baselines (kWh) by time bucket — near-constant 24x7 consumption
CONSUMPTION_PROFILES = {
    'M001': {'morning': 2.3, 'afternoon': 2.2, 'evening': 2.5, 'night': 2.1},   # residential normal (~2.3 kWh steady 24x7)
    'M005': {'morning': 4.7, 'afternoon': 4.8, 'evening': 4.6, 'night': 4.4},   # electronics shop (~4.6 kWh steady)
    'M009': {'morning': 9.8, 'afternoon': 10.2, 'evening': 10.0, 'night': 9.6},  # commercial heavy load (~10.0 kWh steady 24x7)
    'M012': {'morning': 8.9, 'afternoon': 9.1, 'evening': 9.0, 'night': 8.8},   # cold storage 24/7 (~9.0 kWh steady)
    'M014': {'morning': 3.9, 'afternoon': 4.1, 'evening': 4.0, 'night': 3.8},   # textiles factory (~4.0 kWh steady)
    'M018': {'morning': 3.7, 'afternoon': 3.6, 'evening': 4.0, 'night': 3.5},   # apartments (~3.7 kWh steady)
    'M021': {'morning': 3.3, 'afternoon': 3.5, 'evening': 3.2, 'night': 3.0},   # workshop (~3.2 kWh steady)
    'M025': {'morning': 3.9, 'afternoon': 3.8, 'evening': 3.6, 'night': 3.5},   # school (~3.7 kWh steady)
    'M027': {'morning': 8.3, 'afternoon': 8.6, 'evening': 8.4, 'night': 8.1},   # grocery with cooling 24/7 (~8.4 kWh steady)
    'M031': {'morning': 2.3, 'afternoon': 2.2, 'evening': 2.5, 'night': 2.1},   # residential (~2.3 kWh steady)
    'M034': {'morning': 8.4, 'afternoon': 8.6, 'evening': 8.5, 'night': 8.2},   # hospital 24/7 (~8.4 kWh steady)
    'M038': {'morning': 3.5, 'afternoon': 3.7, 'evening': 3.6, 'night': 3.3},   # dairy 24/7 (~3.5 kWh steady)
}

NOISE_FACTOR = 0.08
BACKFILL_DAYS = 5


def add_noise(base_kwh):
    """Add realistic ±8% noise to normal consumption."""
    noise = random.uniform(-NOISE_FACTOR, NOISE_FACTOR)
    return max(0.1, round(base_kwh * (1 + noise), 2))


def get_season_from_date(dt):
    month = dt.month
    if month in (6, 7, 8, 9):
        return 'monsoon'
    elif month in (11, 12, 1, 2):
        return 'winter'
    return 'summer'


# ---------------------------------------------------------------------------
# Seeding Logic
# ---------------------------------------------------------------------------

def seed_transformers(db):
    """Insert distribution transformers."""
    for dt in TRANSFORMERS:
        db.execute(
            """INSERT OR REPLACE INTO transformers (transformer_id, name, location, capacity_kva, input_kwh)
               VALUES (?, ?, ?, ?, ?)""",
            (dt['transformer_id'], dt['name'], dt['location'], dt['capacity_kva'], 0.0)
        )
    db.commit()
    print(f"[simulate] Inserted {len(TRANSFORMERS)} distribution transformers")


def seed_meters(db):
    """Insert meters with transformer mapping."""
    for m in METERS:
        db.execute(
            """INSERT OR REPLACE INTO meters (meter_id, consumer_name, location, lat, lng, transformer_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (m['meter_id'], m['consumer_name'], m['location'], m['lat'], m['lng'], m['transformer_id'])
        )
    db.commit()
    print(f"[simulate] Inserted {len(METERS)} smart meters")


def seed_historical_readings(db):
    """
    Backfill 5 days of readings per meter (hourly telemetry).
    - Normal meters: consumption stays near constant 24x7 (people use electricity 24x7).
    - Theft / Risk meters (M009, M027, M014): recent window shows active tampering where
      actual metered reading drops significantly below expected baseline.
    """
    now = datetime.now()
    start = now - timedelta(days=BACKFILL_DAYS)
    count = 0

    theft_start_m009 = now - timedelta(hours=36)
    theft_start_m027 = now - timedelta(hours=30)
    theft_start_m014 = now - timedelta(hours=36)
    surge_start_m005 = now - timedelta(hours=14)

    for meter in METERS:
        mid = meter['meter_id']
        profile = CONSUMPTION_PROFILES[mid]
        current = start

        while current < now - timedelta(hours=3):
            hour = current.hour
            bucket = get_time_bucket(hour)
            base_kwh = profile[bucket]
            season = get_season_from_date(current)
            reverse_flow = 0

            if mid == 'M009' and current >= theft_start_m009:
                # High Theft: Rotor slowed / bypassed with Neodymium magnet, actual is ~3.0 kWh (Expected is ~10.0 kWh)
                reading_kwh = round(base_kwh * random.uniform(0.28, 0.33), 2)
            elif mid == 'M027' and current >= theft_start_m027:
                # High Theft: Reverse flow / terminal bypass jumper, actual is ~1.8 kWh (Expected is ~8.5 kWh)
                reading_kwh = round(base_kwh * random.uniform(0.20, 0.25), 2)
                reverse_flow = 1
            elif mid == 'M014' and current >= theft_start_m014:
                # Suspicious under-consumption: actual is ~2.8 kWh (Expected is ~4.0 kWh)
                reading_kwh = round(base_kwh * random.uniform(0.68, 0.74), 2)
            elif mid == 'M005' and current >= surge_start_m005:
                # Commercial over-consumption surge: actual is ~13.5 kWh (Expected is ~4.7 kWh)
                reading_kwh = round(base_kwh * random.uniform(2.7, 3.1), 2)
            else:
                # Normal 24x7 consumption: stays near constant around base
                reading_kwh = add_noise(base_kwh)

            db.execute(
                """INSERT INTO readings (meter_id, timestamp, consumption_kwh, hour, season, voltage_v, current_a, reverse_flow)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (mid, current.isoformat(), reading_kwh, hour, season, 230.0 + random.uniform(-3, 3), round(reading_kwh * 4.3, 2), reverse_flow)
            )
            current += timedelta(hours=1)
            count += 1

    db.commit()
    print(f"[simulate] Inserted {count} historical readings")


def compute_baselines(db):
    """
    Precompute baselines table representing the true expected 24x7 consumption
    for each meter based on its connected load and verified baseline profile.
    """
    buckets = ['morning', 'afternoon', 'evening', 'night']
    count = 0
    for meter in METERS:
        mid = meter['meter_id']
        for bucket in buckets:
            expected_val = CONSUMPTION_PROFILES[mid][bucket]
            db.execute(
                "INSERT OR REPLACE INTO baselines (meter_id, time_bucket, avg_kwh) VALUES (?, ?, ?)",
                (mid, bucket, round(expected_val, 2))
            )
            count += 1
    db.commit()
    print(f"[simulate] Computed {count} baseline values")


def seed_tamper_events(db):
    """Seed hardware tamper events for theft detection correlation."""
    now = datetime.now()
    events = [
        {
            'meter_id': 'M009',
            'event_type': 'MAGNETIC_TAMPER',
            'severity': 'CRITICAL',
            'description': 'Strong external neodymium magnetic field (>0.5 Tesla) detected near current transformer; rotor slowed by 70%.',
            'timestamp': (now - timedelta(hours=2, minutes=15)).isoformat()
        },
        {
            'meter_id': 'M027',
            'event_type': 'COVER_OPEN',
            'severity': 'CRITICAL',
            'description': 'Optical tamper switch triggered. Terminal cover opened; physical bypass jumper wire detected across Line and Load.',
            'timestamp': (now - timedelta(hours=1, minutes=45)).isoformat()
        },
        {
            'meter_id': 'M027',
            'event_type': 'NEUTRAL_BYPASS',
            'severity': 'HIGH',
            'description': 'Neutral return disconnect detected. Meter operating on single active wire with earth return.',
            'timestamp': (now - timedelta(hours=1, minutes=10)).isoformat()
        },
        {
            'meter_id': 'M014',
            'event_type': 'VOLTAGE_IMBALANCE',
            'severity': 'MEDIUM',
            'description': 'Phase-to-neutral voltage dropped below nominal with unmetered load draw.',
            'timestamp': (now - timedelta(hours=3, minutes=30)).isoformat()
        }
    ]

    for ev in events:
        db.execute(
            """INSERT INTO tamper_events (meter_id, event_type, severity, description, timestamp)
               VALUES (?, ?, ?, ?, ?)""",
            (ev['meter_id'], ev['event_type'], ev['severity'], ev['description'], ev['timestamp'])
        )
    db.commit()
    print(f"[simulate] Inserted {len(events)} physical tamper events")


def inject_theft_scenarios(db):
    """
    Inject authentic electricity theft (under-consumption) and over-consumption scenarios.

    SCENARIO 1: M009 (Civil Lines) — Severe Theft Case from prompt:
      - Expected baseline: ~10.2 kWh
      - Actual reading: 3.1 kWh
      - Deviation: -69.6%
      - Hardware tamper: Neodymium Magnet logged
      - Result: HIGH THEFT RISK (~91/100)

    SCENARIO 2: M027 (Sector 62) — Severe Commercial Bypass:
      - Expected baseline: ~8.5 kWh
      - Actual reading: 1.8 kWh
      - Deviation: -78.8%
      - Hardware tamper: Cover Open + Neutral Bypass
      - Result: HIGH THEFT RISK (~94/100)

    SCENARIO 3: M014 (Karol Bagh) — Suspicious Under-reporting:
      - Expected baseline: ~4.0 kWh
      - Actual reading: 2.8 kWh
      - Deviation: -30.0%
      - Result: SUSPICIOUS (~55/100)

    SCENARIO 4: M005 (MG Road) — Commercial Over-Consumption:
      - Expected baseline: ~5.0 kWh
      - Actual reading: 14.0 kWh
      - Deviation: +180%
      - Result: OVER-CONSUMPTION (Theft Risk = 0; NOT THEFT!)

    SCENARIO 5: All other meters — Normal consumption within ±10%.
    """
    now = datetime.now()
    season = get_season_from_date(now)
    hour = 14  # Afternoon baseline test reference

    print("[simulate] Injecting theft and non-theft telemetry scenarios...")

    # --- Scenario 1: M009 (Civil Lines) — HIGH THEFT RISK ---
    # 1. Prior reading in active theft window (sustained under-consumption)
    db.execute(
        "INSERT INTO readings (meter_id, timestamp, consumption_kwh, hour, season) VALUES (?, ?, ?, ?, ?)",
        ('M009', (now - timedelta(minutes=45)).isoformat(), 3.0, hour, season)
    )
    db.commit()

    # 2. Latest theft reading: 3.1 kWh (tamper active)
    ts_m009 = (now - timedelta(minutes=11)).isoformat()
    cur = db.execute(
        "INSERT INTO readings (meter_id, timestamp, consumption_kwh, hour, season, voltage_v, current_a, reverse_flow) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ('M009', ts_m009, 3.1, hour, season, 228.0, 13.5, 0)
    )
    r_id = cur.lastrowid
    db.commit()

    res_m009 = process_reading({
        'meter_id': 'M009',
        'consumption_kwh': 3.1,
        'hour': hour,
        'timestamp': ts_m009,
        'reading_id': r_id
    }, db)
    print(f"  -> M009 (Civil Lines): status={res_m009['theft_status']}, risk={res_m009['theft_risk_score']}/100, dev={res_m009['deviation_pct']}%")

    # --- Scenario 2: M027 (Sector 62) — HIGH THEFT RISK ---
    # Prior reading in active theft window
    db.execute(
        "INSERT INTO readings (meter_id, timestamp, consumption_kwh, hour, season) VALUES (?, ?, ?, ?, ?)",
        ('M027', (now - timedelta(minutes=50)).isoformat(), 1.9, hour, season)
    )
    db.commit()

    ts_m027 = (now - timedelta(minutes=18)).isoformat()
    cur = db.execute(
        "INSERT INTO readings (meter_id, timestamp, consumption_kwh, hour, season, voltage_v, current_a, reverse_flow) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ('M027', ts_m027, 1.8, hour, season, 219.0, 7.8, 1)  # reverse flow / bypass
    )
    r_id27 = cur.lastrowid
    db.commit()

    res_m027 = process_reading({
        'meter_id': 'M027',
        'consumption_kwh': 1.8,
        'hour': hour,
        'timestamp': ts_m027,
        'reading_id': r_id27,
        'reverse_flow': 1
    }, db)
    print(f"  -> M027 (Sector 62): status={res_m027['theft_status']}, risk={res_m027['theft_risk_score']}/100, dev={res_m027['deviation_pct']}%")

    # --- Scenario 3: M014 (Karol Bagh) — SUSPICIOUS ---
    ts_m014 = (now - timedelta(minutes=25)).isoformat()
    cur = db.execute(
        "INSERT INTO readings (meter_id, timestamp, consumption_kwh, hour, season) VALUES (?, ?, ?, ?, ?)",
        ('M014', ts_m014, 3.2, hour, season)
    )
    r_id14 = cur.lastrowid
    db.commit()

    res_m014 = process_reading({
        'meter_id': 'M014',
        'consumption_kwh': 3.2,
        'hour': hour,
        'timestamp': ts_m014,
        'reading_id': r_id14
    }, db)
    print(f"  -> M014 (Karol Bagh): status={res_m014['theft_status']}, risk={res_m014['theft_risk_score']}/100, dev={res_m014['deviation_pct']}%")

    # --- Scenario 4: M005 (MG Road) — OVER-CONSUMPTION (NOT THEFT) ---
    ts_m005 = (now - timedelta(minutes=8)).isoformat()
    cur = db.execute(
        "INSERT INTO readings (meter_id, timestamp, consumption_kwh, hour, season) VALUES (?, ?, ?, ?, ?)",
        ('M005', ts_m005, 14.0, hour, season)
    )
    r_id05 = cur.lastrowid
    db.commit()

    res_m005 = process_reading({
        'meter_id': 'M005',
        'consumption_kwh': 14.0,
        'hour': hour,
        'timestamp': ts_m005,
        'reading_id': r_id05
    }, db)
    print(f"  -> M005 (MG Road): status={res_m005['theft_status']}, risk={res_m005['theft_risk_score']}/100 (NOT THEFT), dev={res_m005['deviation_pct']}%")

    # --- Normal readings for remaining meters ---
    normal_meters = ['M001', 'M012', 'M018', 'M021', 'M025', 'M031', 'M034', 'M038']
    for mid in normal_meters:
        base = CONSUMPTION_PROFILES[mid]['afternoon']
        kwh = add_noise(base)
        ts_norm = (now - timedelta(minutes=random.randint(5, 30))).isoformat()
        cur = db.execute(
            "INSERT INTO readings (meter_id, timestamp, consumption_kwh, hour, season) VALUES (?, ?, ?, ?, ?)",
            (mid, ts_norm, kwh, hour, season)
        )
        norm_id = cur.lastrowid
        db.commit()
        process_reading({
            'meter_id': mid,
            'consumption_kwh': kwh,
            'hour': hour,
            'timestamp': ts_norm,
            'reading_id': norm_id
        }, db)


def update_transformer_energy_balance(db):
    """
    Computes and updates transformer energy input to showcase grid energy balance.
    Total Input = Sum of true load consumed + Technical loss (5.5%).
    Because M009 and M027 are stealing electricity, their metered sum is lower than
    the actual energy delivered through the transformer, creating an Unaccounted Energy gap!
    """
    for dt in TRANSFORMERS:
        tid = dt['transformer_id']
        cursor = db.execute(
            """SELECT SUM(r.consumption_kwh) as billed_sum
               FROM meters m
               JOIN readings r ON r.meter_id = m.meter_id
               WHERE m.transformer_id = ?
               AND r.id IN (SELECT MAX(id) FROM readings GROUP BY meter_id)""",
            (tid,)
        )
        row = cursor.fetchone()
        billed_sum = row['billed_sum'] or 5.0

        # If this transformer powers a theft meter, inject realistic unaccounted loss
        if tid == 'DT-02':  # Powers M009 (Civil Lines): true load is ~10.5 kWh, billed is 3.1 kWh
            input_kwh = 11.2
        elif tid == 'DT-01': # Powers M027 (Sector 62): true load is ~10.4 kWh, billed is 1.8 + 1.8 = 3.6 kWh
            input_kwh = 12.0
        elif tid == 'DT-04': # Powers M014 (Karol Bagh): true load ~4.2 kWh, billed 2.8 kWh
            input_kwh = 4.6
        else: # Normal transformer: input = billed / (1 - 0.055) (pure technical loss)
            input_kwh = round(billed_sum / 0.945, 2)

        db.execute(
            "UPDATE transformers SET input_kwh = ? WHERE transformer_id = ?",
            (round(input_kwh, 2), tid)
        )
    db.commit()
# Alias for plan compliance
def seed_complaints(db):
    """Seed sample citizen vigilance complaints with evidence and tracking stages."""
    now = datetime.now()
    complaints = [
        {
            'ticket_id': 'CIT-2026-8942',
            'complainant_name': 'Ramesh Verma',
            'complainant_phone': '+91 98112 45892',
            'is_anonymous': 0,
            'location': 'Karol Bagh Market Road, Block 4',
            'landmark': 'Near DT-04 Transformer, pole #14',
            'theft_type': 'Direct Hooking (Katia Wire)',
            'description': 'Multiple unmetered cables hooked onto low-tension overhead line feeding 3 commercial garment shops at night.',
            'photo_filename': 'katia_hooking.svg',
            'status': 'UNDER_INVESTIGATION',
            'stage': 3,
            'assigned_team': 'DISCOM Vigilance Squad #4 - Central Zone',
            'remarks': 'Correlated with DT-04 Karol Bagh telemetry showing 23.9% unaccounted loss. Inspection team en route.',
            'created_at': (now - timedelta(hours=3, minutes=20)).isoformat(),
            'updated_at': (now - timedelta(minutes=15)).isoformat()
        },
        {
            'ticket_id': 'CIT-2026-7731',
            'complainant_name': 'Anonymous Citizen',
            'complainant_phone': '+91 98765 00000',
            'is_anonymous': 1,
            'location': 'Civil Lines, Near Metro Pillar 82',
            'landmark': 'Adjacent to Vikram Singh residence (Meter M009)',
            'theft_type': 'Meter Bypass / Shunt Wire',
            'description': 'Observed heavy jumper cable bridging input and output terminal blocks. Meter running unnaturally slow.',
            'photo_filename': 'meter_bypass.svg',
            'status': 'DISPATCHED',
            'stage': 4,
            'assigned_team': 'North-West Enforcement Wing',
            'remarks': 'Smart meter M009 telemetry confirmed -69.5% under-consumption drop and neodymium magnet alert. Field squad dispatched for on-site audit.',
            'created_at': (now - timedelta(hours=5, minutes=45)).isoformat(),
            'updated_at': (now - timedelta(minutes=30)).isoformat()
        },
        {
            'ticket_id': 'CIT-2026-6105',
            'complainant_name': 'Sunita Sharma',
            'complainant_phone': '+91 98450 11223',
            'is_anonymous': 0,
            'location': 'Sector 62, Block C Market',
            'landmark': 'Near Deepak Grocery Store (Meter M027)',
            'theft_type': 'Meter Seal Broken / Cover Tampered',
            'description': 'DISCOM lead seal was cut and meter casing opened. High-power cold storage units running without meter registering proper load.',
            'photo_filename': 'broken_seal.svg',
            'status': 'RESOLVED',
            'stage': 5,
            'assigned_team': 'Sector 62 Substation Squad',
            'remarks': 'Raid conducted. Reverse flow and physical tamper confirmed. Assessment penalty of ₹84,200 levied under Sec 135 Electricity Act.',
            'created_at': (now - timedelta(days=1, hours=2)).isoformat(),
            'updated_at': (now - timedelta(hours=1)).isoformat()
        },
        {
            'ticket_id': 'CIT-2026-5120',
            'complainant_name': 'Alok Sengupta',
            'complainant_phone': '+91 98711 34990',
            'is_anonymous': 0,
            'location': 'Karol Bagh Commercial Hub, Main Ajmal Khan Rd',
            'landmark': 'Feeder DT-04 Junction Pole #22',
            'theft_type': 'Direct Hooking (Katia Wire)',
            'description': 'Heavy gauge tapping hooked directly onto low-voltage line powering commercial banquet lights.',
            'photo_filename': 'katia_hooking.svg',
            'status': 'RESOLVED',
            'stage': 5,
            'assigned_team': 'DISCOM Flying Squad #1 - Central',
            'remarks': 'Raid finalized. Illicit 18kW hook dismantled. ₹18,200 citizen bounty disbursed via NEFT under DISCOM Whistleblower Scheme.',
            'created_at': (now - timedelta(days=2, hours=4)).isoformat(),
            'updated_at': (now - timedelta(hours=6)).isoformat()
        },
        {
            'ticket_id': 'CIT-2026-4412',
            'complainant_name': 'Anonymous Whistleblower #4092',
            'complainant_phone': '+91 98100 00000',
            'is_anonymous': 1,
            'location': 'Okhla Industrial Area Phase 2, Shed 14',
            'landmark': 'Opposite Substation Feeder 7',
            'theft_type': 'Meter Bypass / Shunt Wire',
            'description': 'Underground heavy 35kW tap bypassing high-tension commercial meter for industrial molding machinery.',
            'photo_filename': 'meter_bypass.svg',
            'status': 'RESOLVED',
            'stage': 5,
            'assigned_team': 'Special Vigilance Anti-Power Theft Police',
            'remarks': 'Major industrial theft busted. Recovery assessment of ₹4,20,000 served. ₹42,500 disbursed to verified informant UPI.',
            'created_at': (now - timedelta(days=3, hours=8)).isoformat(),
            'updated_at': (now - timedelta(days=1)).isoformat()
        },
        {
            'ticket_id': 'CIT-2026-7674',
            'complainant_name': 'Citizen Informant',
            'complainant_phone': '+91 98734 51290',
            'is_anonymous': 0,
            'location': 'Karol Bagh Market Road, Block 3',
            'landmark': 'Near DT-04 Distribution Transformer',
            'theft_type': 'Direct Hooking (Katia Wire)',
            'description': 'Commercial unmetered tap observed overhead. Night load spiking on local feeder.',
            'photo_filename': 'katia_hooking.svg',
            'status': 'UNDER_INVESTIGATION',
            'stage': 3,
            'assigned_team': 'DISCOM Vigilance Squad #4 - Central Zone',
            'remarks': 'AI Alert: Correlated with DT-04 (Karol Bagh) telemetry showing 23.9% unaccounted loss. Inspection team en route.',
            'created_at': (now - timedelta(hours=1, minutes=30)).isoformat(),
            'updated_at': (now - timedelta(minutes=20)).isoformat()
        }
    ]

    for c in complaints:
        google_email = 'whistleblower.delhi@gmail.com' if not c['is_anonymous'] else 'anonymous.informant@gmail.com'
        db.execute(
            """INSERT OR REPLACE INTO complaints (
                ticket_id, complainant_name, complainant_phone, google_email, is_anonymous,
                location, landmark, theft_type, description, photo_filename,
                status, stage, assigned_team, remarks, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                c['ticket_id'], c['complainant_name'], c['complainant_phone'], google_email, c['is_anonymous'],
                c['location'], c['landmark'], c['theft_type'], c['description'], c['photo_filename'],
                c['status'], c['stage'], c['assigned_team'], c['remarks'], c['created_at'], c['updated_at']
            )
        )
    db.commit()
    print(f"[simulate] Inserted {len(complaints)} citizen complaints with evidence photos & Google verification")


def seed_database():
    """Full database reset and seed."""
    print("\n⚡ Watt's Off — Electricity Theft Platform Database Seeding\n" + "=" * 55)
    reset_db()
    db = get_db()

    seed_transformers(db)
    seed_meters(db)
    seed_historical_readings(db)
    compute_baselines(db)
    seed_tamper_events(db)
    inject_theft_scenarios(db)
    update_transformer_energy_balance(db)
    seed_complaints(db)

    # Summary
    m_cnt = db.execute("SELECT COUNT(*) as cnt FROM meters").fetchone()['cnt']
    r_cnt = db.execute("SELECT COUNT(*) as cnt FROM readings").fetchone()['cnt']
    a_cnt = db.execute("SELECT COUNT(*) as cnt FROM anomalies").fetchone()['cnt']
    al_cnt = db.execute("SELECT COUNT(*) as cnt FROM alerts").fetchone()['cnt']
    t_cnt = db.execute("SELECT COUNT(*) as cnt FROM tamper_events").fetchone()['cnt']
    c_cnt = db.execute("SELECT COUNT(*) as cnt FROM complaints").fetchone()['cnt']

    print(f"\n📊 Seeding Complete:")
    print(f"  Meters:         {m_cnt}")
    print(f"  Readings:       {r_cnt}")
    print(f"  Anomalies:      {a_cnt}")
    print(f"  Alerts:         {al_cnt}")
    print(f"  Tamper Events:  {t_cnt}")
    print(f"  Complaints:     {c_cnt}")


    db.close()
    print("\n✅ Database seeded with under-consumption theft detection dataset!\n")


# ---------------------------------------------------------------------------
# Real-Time Live Simulation Loop
# ---------------------------------------------------------------------------

def live_simulation():
    """Continuous simulation loop appending telemetry readings every 5 seconds."""
    print("\n⚡ Watt's Off — Live Electricity Theft Simulation")
    print("=" * 55)
    print("Generating real-time telemetry every 5 seconds...")
    print("Press Ctrl+C to terminate.\n")

    init_db()
    db = get_db()

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
            base = profile[bucket]

            # Maintain scenario consistency: normal meters stay near constant 24x7
            reverse_flow = 0
            if meter_id == 'M009':
                # High Theft: Rotor slowed / Neodymium magnetic tamper (< -30%)
                consumption = round(base * random.uniform(0.28, 0.33), 2)
            elif meter_id == 'M027':
                # High Theft: Reverse flow / terminal bypass jumper (< -30%)
                consumption = round(base * random.uniform(0.20, 0.25), 2)
                reverse_flow = 1
            elif meter_id == 'M014':
                # Suspicious under-consumption (-10% to -30%)
                consumption = round(base * random.uniform(0.68, 0.74), 2)
            elif meter_id == 'M005':
                # Commercial over-consumption surge (NOT theft, +100% to +180%)
                consumption = round(base * random.uniform(2.7, 3.1), 2)
            else:
                # Normal 24x7 consumption: people use electricity 24x7, stays near constant
                consumption = add_noise(base)

            cursor = db.execute(
                """INSERT INTO readings (meter_id, timestamp, consumption_kwh, hour, season, voltage_v, current_a, reverse_flow)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (meter_id, now.isoformat(), consumption, hour, season, 230.0 + random.uniform(-2, 2), round(consumption * 4.3, 2), 0)
            )
            reading_id = cursor.lastrowid
            db.commit()

            result = process_reading({
                'meter_id': meter_id,
                'consumption_kwh': consumption,
                'hour': hour,
                'timestamp': now.isoformat(),
                'reading_id': reading_id
            }, db)

            # Icon representation
            icon = '🔴' if result['theft_status'] == 'HIGH_THEFT_RISK' else \
                   '🟡' if result['theft_status'] == 'SUSPICIOUS' else \
                   '🟣' if result['theft_status'] == 'OVER_CONSUMPTION' else '🟢'

            theft_str = f"THEFT_RISK: {result['theft_risk_score']}/100" if result['theft_status'] != 'OVER_CONSUMPTION' else "OVER-CONSUMPTION (NOT THEFT)"
            print(f"  [{iteration:04d}] {icon} {meter_id:4s} | Act: {consumption:5.2f} kWh (Exp: {result['expected_kwh']:5.2f}) | "
                  f"Dev: {result['deviation_pct']:+6.1f}% | {result['theft_status']:16s} | {theft_str}")

            time.sleep(5)

    except KeyboardInterrupt:
        print("\n\n🛑 Live simulation stopped.")
        db.close()


if __name__ == '__main__':
    if '--live' in sys.argv:
        live_simulation()
    else:
        seed_database()
