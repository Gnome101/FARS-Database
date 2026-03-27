#!/usr/bin/env python3
"""
load_fars.py — Reads FARS 2023 CSV files and generates fars_complete.sql
containing DDL, INSERT statements, and example queries.
"""

import csv
import os
import sys

CSV_DIR = os.path.join(os.path.dirname(__file__),
                       "FARS2023NationalCSV", "FARS2023NationalCSV")
OUTPUT = os.path.join(os.path.dirname(__file__), "fars_complete.sql")
BATCH = 500  # rows per multi-value INSERT

PLACEHOLDER_VINS = {'999999999999', '888888888888', '000000000000'}
SENTINEL_COORDS = {'77.7777', '99.9999', '88.8888',
                    '77.77770000', '99.99990000', '88.88880000'}


def is_sentinel(lat_str):
    """Check if a latitude string is a sentinel / unknown value."""
    try:
        v = abs(float(lat_str))
    except (ValueError, TypeError):
        return True
    return any(abs(v - float(s)) < 0.001 for s in ('77.7777', '99.9999', '88.8888'))


def resolve_vin(vin, st_case, veh_no):
    if vin in PLACEHOLDER_VINS:
        return f"UNK{st_case}V{veh_no}"
    return vin


def synth_per_no(veh_no, per_no):
    return int(veh_no) * 100 + int(per_no)


def sql_int(val):
    """Return an integer literal or NULL."""
    if val is None or val == '':
        return 'NULL'
    try:
        return str(int(val))
    except ValueError:
        return 'NULL'


def sql_num(val):
    """Return a numeric literal or NULL."""
    if val is None or val == '':
        return 'NULL'
    try:
        return str(float(val))
    except ValueError:
        return 'NULL'


def sql_str(val):
    """Return a quoted string literal or NULL."""
    if val is None or val == '':
        return 'NULL'
    return "'" + val.replace("'", "''") + "'"


def write_inserts(f, table, columns, rows, val_fn):
    """Write multi-row INSERT statements in batches."""
    if not rows:
        return
    cols = ', '.join(columns)
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i + BATCH]
        f.write(f"INSERT INTO {table} ({cols}) VALUES\n")
        lines = []
        for row in batch:
            vals = ', '.join(val_fn(row))
            lines.append(f"  ({vals})")
        f.write(',\n'.join(lines))
        f.write(';\n\n')


# ---------------------------------------------------------------------------
# Read CSVs
# ---------------------------------------------------------------------------

def read_accidents():
    """Returns (location_rows, crash_rows)."""
    locations = {}   # (lat, lon) -> row dict
    crashes = []

    with open(os.path.join(CSV_DIR, "accident.csv"), newline='') as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            lat = r['LATITUDE']
            lon = r['LONGITUD']
            sentinel = is_sentinel(lat)

            if not sentinel:
                key = (lat, lon)
                if key not in locations:
                    locations[key] = {
                        'LATITUDE': lat, 'LONGITUDE': lon,
                        'COUNTY': r['COUNTY'], 'CITY': r['CITY'],
                        'STATE': r['STATE'], 'TYP_INT': r['TYP_INT'],
                        'REL_ROAD': r['REL_ROAD'], 'ROUTE': r['ROUTE'],
                    }

            crashes.append({
                'ST_CASE': r['ST_CASE'],
                'PEDS': r['PEDS'], 'PERSONS': r['PERSONS'],
                'DAY': r['DAY'], 'MONTH': r['MONTH'], 'YEAR': r['YEAR'],
                'NOT_HOUR': r['NOT_HOUR'], 'ARR_HOUR': r['ARR_HOUR'],
                'VE_TOTAL': r['VE_TOTAL'], 'ARR_MIN': r['ARR_MIN'],
                'MAN_COLL': r['MAN_COLL'], 'NOT_MIN': r['NOT_MIN'],
                'FATALS': r['FATALS'],
                'LATITUDE': None if sentinel else lat,
                'LONGITUDE': None if sentinel else lon,
                'WEATHER': r['WEATHER'], 'LGT_COND': r['LGT_COND'],
                'WRK_ZONE': r['WRK_ZONE'],
            })

    print(f"  Locations:  {len(locations)}")
    print(f"  Crashes:    {len(crashes)}")
    return list(locations.values()), crashes


def read_vehicles():
    """Returns (vehicle_rows, involves_rows, vin_map)."""
    vin_map = {}       # (ST_CASE, VEH_NO) -> resolved VIN
    vehicles = {}      # VIN -> first-seen row
    involves = []
    seen_involves = set()

    with open(os.path.join(CSV_DIR, "vehicle.csv"), newline='') as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            st = r['ST_CASE']
            vno = r['VEH_NO']
            raw_vin = r['VIN']
            vin = resolve_vin(raw_vin, st, vno)

            vin_map[(st, vno)] = vin

            if vin not in vehicles:
                vehicles[vin] = {
                    'VIN': vin, 'VEH_NO': vno,
                    'MOD_YEAR': r['MOD_YEAR'], 'MAKE': r['MAKE'],
                    'BODY_TYP': r['BODY_TYP'], 'UNITTYPE': r['UNITTYPE'],
                }

            inv_key = (st, vin)
            if inv_key not in seen_involves:
                seen_involves.add(inv_key)
                involves.append({
                    'ST_CASE': st, 'VIN': vin,
                    'NUMOCCS': r['NUMOCCS'], 'ROLLOVER': r['ROLLOVER'],
                    'TRAV_SP': r['TRAV_SP'], 'IMPACT1': r['IMPACT1'],
                    'HIT_RUN': r['HIT_RUN'], 'FIRE_EXP': r['FIRE_EXP'],
                    'TOWED': r['TOWED'], 'DEFORMED': r['DEFORMED'],
                    'VSPD_LIM': r['VSPD_LIM'],
                })

    print(f"  Vehicles:   {len(vehicles)}")
    print(f"  Involves:   {len(involves)}")
    return list(vehicles.values()), involves, vin_map


def read_persons(vin_map):
    """Returns (persons, pedestrians, car_persons, passengers, drivers, rides_in)."""
    persons = []
    pedestrians = []
    car_persons = []
    passengers = []
    drivers = []
    rides_in = []

    with open(os.path.join(CSV_DIR, "person.csv"), newline='') as fh:
        reader = csv.DictReader(fh)
        for r in reader:
            st = r['ST_CASE']
            vno = r['VEH_NO']
            per_type = r['PER_TYP']
            spn = synth_per_no(vno, r['PER_NO'])

            persons.append({
                'ST_CASE': st, 'PER_NO': spn,
                'AGE': r['AGE'], 'SEX': r['SEX'],
                'INJ_SEV': r['INJ_SEV'], 'HOSPITAL': r['HOSPITAL'],
                'DOA': r['DOA'],
            })

            if per_type in ('1', '2'):
                # Car person (driver or passenger)
                car_persons.append({
                    'PER_NO': spn, 'ST_CASE': st,
                    'EJECTION': r['EJECTION'], 'SEAT_POS': r['SEAT_POS'],
                    'REST_USE': r['REST_USE'],
                })
                # Resolve VIN for Rides_In
                vin = vin_map.get((st, vno))
                if vin:
                    rides_in.append({
                        'PER_NO': spn, 'ST_CASE': st, 'VIN': vin,
                    })

                if per_type == '1':
                    drivers.append({
                        'PER_NO': spn, 'ST_CASE': st,
                        'DRINKING': r['DRINKING'], 'DRUGS': r['DRUGS'],
                    })
                else:
                    passengers.append({
                        'PER_NO': spn, 'ST_CASE': st,
                    })

            elif per_type in ('5', '6'):
                pedestrians.append({
                    'PER_NO': spn, 'ST_CASE': st,
                })

    print(f"  Persons:    {len(persons)}")
    print(f"  Pedestrians:{len(pedestrians)}")
    print(f"  CarPersons: {len(car_persons)}")
    print(f"  Passengers: {len(passengers)}")
    print(f"  Drivers:    {len(drivers)}")
    print(f"  Rides_In:   {len(rides_in)}")
    return persons, pedestrians, car_persons, passengers, drivers, rides_in


# ---------------------------------------------------------------------------
# Write SQL
# ---------------------------------------------------------------------------

DDL = r"""
-- ============================================================
-- PART 1: DDL — CREATE TABLE statements
-- ============================================================

DROP TABLE IF EXISTS Involves CASCADE;
DROP TABLE IF EXISTS Rides_In CASCADE;
DROP TABLE IF EXISTS Driver CASCADE;
DROP TABLE IF EXISTS Passenger CASCADE;
DROP TABLE IF EXISTS CarPerson CASCADE;
DROP TABLE IF EXISTS Pedestrian CASCADE;
DROP TABLE IF EXISTS Person CASCADE;
DROP TABLE IF EXISTS Vehicle CASCADE;
DROP TABLE IF EXISTS Crash CASCADE;
DROP TABLE IF EXISTS Location CASCADE;

CREATE TABLE Location (
    LATITUDE    NUMERIC NOT NULL,
    LONGITUDE   NUMERIC NOT NULL,
    COUNTY      INT,
    CITY        INT,
    STATE       INT,
    TYP_INT     INT,
    REL_ROAD    INT,
    ROUTE       INT,
    PRIMARY KEY (LATITUDE, LONGITUDE)
);

CREATE TABLE Crash (
    ST_CASE     INT PRIMARY KEY,
    PEDS        INT,
    PERSONS     INT,
    DAY         INT,
    MONTH       INT,
    YEAR        INT,
    NOT_HOUR    INT,
    ARR_HOUR    INT,
    VE_TOTAL    INT,
    ARR_MIN     INT,
    MAN_COLL    INT,
    NOT_MIN     INT,
    FATALS      INT,
    LATITUDE    NUMERIC,
    LONGITUDE   NUMERIC,
    WEATHER     INT,
    LGT_COND    INT,
    WRK_ZONE    INT,
    FOREIGN KEY (LATITUDE, LONGITUDE) REFERENCES Location(LATITUDE, LONGITUDE)
);

CREATE TABLE Vehicle (
    VIN         VARCHAR(17) PRIMARY KEY,
    VEH_NO      INT,
    MOD_YEAR    INT,
    MAKE        INT,
    BODY_TYP    INT,
    UNITTYPE    INT
);

CREATE TABLE Person (
    ST_CASE     INT NOT NULL,
    PER_NO      INT NOT NULL,
    AGE         INT,
    SEX         INT,
    INJ_SEV     INT,
    HOSPITAL    INT,
    DOA         INT,
    PRIMARY KEY (PER_NO, ST_CASE),
    FOREIGN KEY (ST_CASE) REFERENCES Crash(ST_CASE) ON DELETE CASCADE
);

CREATE TABLE Pedestrian (
    PER_NO      INT NOT NULL,
    ST_CASE     INT NOT NULL,
    PRIMARY KEY (PER_NO, ST_CASE),
    FOREIGN KEY (PER_NO, ST_CASE) REFERENCES Person(PER_NO, ST_CASE) ON DELETE CASCADE
);

CREATE TABLE CarPerson (
    PER_NO      INT NOT NULL,
    ST_CASE     INT NOT NULL,
    EJECTION    INT,
    SEAT_POS    INT,
    REST_USE    INT,
    PRIMARY KEY (PER_NO, ST_CASE),
    FOREIGN KEY (PER_NO, ST_CASE) REFERENCES Person(PER_NO, ST_CASE) ON DELETE CASCADE
);

CREATE TABLE Passenger (
    PER_NO      INT NOT NULL,
    ST_CASE     INT NOT NULL,
    PRIMARY KEY (PER_NO, ST_CASE),
    FOREIGN KEY (PER_NO, ST_CASE) REFERENCES CarPerson(PER_NO, ST_CASE) ON DELETE CASCADE
);

CREATE TABLE Driver (
    PER_NO      INT NOT NULL,
    ST_CASE     INT NOT NULL,
    DRINKING    INT,
    DRUGS       INT,
    PRIMARY KEY (PER_NO, ST_CASE),
    FOREIGN KEY (PER_NO, ST_CASE) REFERENCES CarPerson(PER_NO, ST_CASE) ON DELETE CASCADE
);

CREATE TABLE Rides_In (
    PER_NO      INT NOT NULL,
    ST_CASE     INT NOT NULL,
    VIN         VARCHAR(17),
    PRIMARY KEY (PER_NO, ST_CASE),
    FOREIGN KEY (PER_NO, ST_CASE) REFERENCES Person(PER_NO, ST_CASE) ON DELETE CASCADE,
    FOREIGN KEY (VIN) REFERENCES Vehicle(VIN)
);

CREATE TABLE Involves (
    ST_CASE     INT NOT NULL,
    VIN         VARCHAR(17) NOT NULL,
    NUMOCCS     INT,
    ROLLOVER    INT,
    TRAV_SP     INT,
    IMPACT1     INT,
    HIT_RUN     INT,
    FIRE_EXP    INT,
    TOWED       INT,
    DEFORMED    INT,
    VSPD_LIM    INT,
    PRIMARY KEY (ST_CASE, VIN),
    FOREIGN KEY (ST_CASE) REFERENCES Crash(ST_CASE),
    FOREIGN KEY (VIN) REFERENCES Vehicle(VIN)
);
"""

QUERIES = r"""
-- ============================================================
-- PART 3: Example SQL Queries
-- ============================================================

-- Q1: Simple SELECT — Crashes in January 2023 with more than 3 fatalities
SELECT ST_CASE, DAY, FATALS
FROM Crash
WHERE MONTH = 1 AND FATALS > 3;

-- Q2: GROUP BY — Total fatalities per month
SELECT MONTH, SUM(FATALS) AS total_fatalities
FROM Crash
GROUP BY MONTH
ORDER BY MONTH;

-- Q3: JOIN — Drivers involved in hit-and-run crashes
SELECT d.PER_NO, d.ST_CASE, p.AGE, p.SEX
FROM Driver d
JOIN Person p ON d.PER_NO = p.PER_NO AND d.ST_CASE = p.ST_CASE
JOIN Rides_In ri ON d.PER_NO = ri.PER_NO AND d.ST_CASE = ri.ST_CASE
JOIN Involves i ON ri.VIN = i.VIN AND d.ST_CASE = i.ST_CASE
WHERE i.HIT_RUN = 1;

-- Q4: GROUP BY + HAVING — States with more than 1000 fatal crashes
SELECT l.STATE, COUNT(DISTINCT c.ST_CASE) AS crash_count
FROM Crash c
JOIN Location l ON c.LATITUDE = l.LATITUDE AND c.LONGITUDE = l.LONGITUDE
GROUP BY l.STATE
HAVING COUNT(DISTINCT c.ST_CASE) > 1000;

-- Q5: Nested subquery — Crash with the most persons involved
SELECT ST_CASE, PERSONS, FATALS
FROM Crash
WHERE PERSONS = (SELECT MAX(PERSONS) FROM Crash);

-- Q6: Multi-table JOIN — Vehicle makes involved in rollovers
SELECT DISTINCT v.VIN, v.MAKE, v.MOD_YEAR
FROM Vehicle v
JOIN Involves i ON v.VIN = i.VIN
WHERE i.ROLLOVER > 0;

-- Q7: EXISTS — Crashes where at least one driver was drinking
SELECT c.ST_CASE, c.FATALS
FROM Crash c
WHERE EXISTS (
    SELECT 1 FROM Driver d
    WHERE d.ST_CASE = c.ST_CASE AND d.DRINKING = 1
);

-- Q8: Aggregate + JOIN — Average age of fatally injured pedestrians
SELECT AVG(p.AGE) AS avg_age
FROM Person p
JOIN Pedestrian ped ON p.PER_NO = ped.PER_NO AND p.ST_CASE = ped.ST_CASE
WHERE p.INJ_SEV = 4 AND p.AGE < 998;

-- Q9: Complex — Drunk-driving crash count and total fatalities by state
SELECT l.STATE,
       COUNT(DISTINCT c.ST_CASE) AS drunk_crashes,
       SUM(c.FATALS) AS total_fatalities
FROM Crash c
JOIN Location l ON c.LATITUDE = l.LATITUDE AND c.LONGITUDE = l.LONGITUDE
WHERE c.ST_CASE IN (SELECT ST_CASE FROM Driver WHERE DRINKING = 1)
GROUP BY l.STATE
ORDER BY drunk_crashes DESC;

-- Q10: Division (EXCEPT) — Vehicles involved in crashes in every month of 2023
SELECT v.VIN
FROM Vehicle v
WHERE NOT EXISTS (
    SELECT DISTINCT MONTH FROM Crash
    EXCEPT
    SELECT c.MONTH FROM Crash c
    JOIN Involves i ON c.ST_CASE = i.ST_CASE
    WHERE i.VIN = v.VIN
);

-- Q11: Window function — Rank states by total fatality count
SELECT l.STATE,
       SUM(c.FATALS) AS total_fatals,
       RANK() OVER (ORDER BY SUM(c.FATALS) DESC) AS fatality_rank
FROM Crash c
JOIN Location l ON c.LATITUDE = l.LATITUDE AND c.LONGITUDE = l.LONGITUDE
GROUP BY l.STATE;

-- Q12: UPDATE demo — Mark unknown sex values as NULL
UPDATE Person SET SEX = NULL WHERE SEX IN (8, 9);

-- ============================================================
-- Verification: Row counts
-- ============================================================
SELECT 'Location' AS tbl, COUNT(*) AS cnt FROM Location
UNION ALL SELECT 'Crash', COUNT(*) FROM Crash
UNION ALL SELECT 'Vehicle', COUNT(*) FROM Vehicle
UNION ALL SELECT 'Person', COUNT(*) FROM Person
UNION ALL SELECT 'Pedestrian', COUNT(*) FROM Pedestrian
UNION ALL SELECT 'CarPerson', COUNT(*) FROM CarPerson
UNION ALL SELECT 'Passenger', COUNT(*) FROM Passenger
UNION ALL SELECT 'Driver', COUNT(*) FROM Driver
UNION ALL SELECT 'Rides_In', COUNT(*) FROM Rides_In
UNION ALL SELECT 'Involves', COUNT(*) FROM Involves;
"""


def main():
    print("Reading CSVs...")
    locations, crashes = read_accidents()
    vehicles, involves, vin_map = read_vehicles()
    persons, pedestrians, car_persons, passengers, drivers, rides_in = read_persons(vin_map)

    print(f"\nWriting {OUTPUT} ...")
    with open(OUTPUT, 'w') as f:
        # ----- DDL -----
        f.write(DDL)

        # ----- Data -----
        f.write("\n-- ============================================================\n")
        f.write("-- PART 2: Data Loading — INSERT statements\n")
        f.write("-- ============================================================\n\n")
        f.write("BEGIN;\n\n")

        # Location
        write_inserts(f, 'Location',
            ['LATITUDE', 'LONGITUDE', 'COUNTY', 'CITY', 'STATE', 'TYP_INT', 'REL_ROAD', 'ROUTE'],
            locations,
            lambda r: [sql_num(r['LATITUDE']), sql_num(r['LONGITUDE']),
                        sql_int(r['COUNTY']), sql_int(r['CITY']),
                        sql_int(r['STATE']), sql_int(r['TYP_INT']),
                        sql_int(r['REL_ROAD']), sql_int(r['ROUTE'])])

        # Crash
        write_inserts(f, 'Crash',
            ['ST_CASE', 'PEDS', 'PERSONS', 'DAY', 'MONTH', 'YEAR',
             'NOT_HOUR', 'ARR_HOUR', 'VE_TOTAL', 'ARR_MIN', 'MAN_COLL',
             'NOT_MIN', 'FATALS', 'LATITUDE', 'LONGITUDE', 'WEATHER',
             'LGT_COND', 'WRK_ZONE'],
            crashes,
            lambda r: [sql_int(r['ST_CASE']), sql_int(r['PEDS']),
                        sql_int(r['PERSONS']), sql_int(r['DAY']),
                        sql_int(r['MONTH']), sql_int(r['YEAR']),
                        sql_int(r['NOT_HOUR']), sql_int(r['ARR_HOUR']),
                        sql_int(r['VE_TOTAL']), sql_int(r['ARR_MIN']),
                        sql_int(r['MAN_COLL']), sql_int(r['NOT_MIN']),
                        sql_int(r['FATALS']),
                        sql_num(r['LATITUDE']), sql_num(r['LONGITUDE']),
                        sql_int(r['WEATHER']), sql_int(r['LGT_COND']),
                        sql_int(r['WRK_ZONE'])])

        # Vehicle
        write_inserts(f, 'Vehicle',
            ['VIN', 'VEH_NO', 'MOD_YEAR', 'MAKE', 'BODY_TYP', 'UNITTYPE'],
            vehicles,
            lambda r: [sql_str(r['VIN']), sql_int(r['VEH_NO']),
                        sql_int(r['MOD_YEAR']), sql_int(r['MAKE']),
                        sql_int(r['BODY_TYP']), sql_int(r['UNITTYPE'])])

        # Person
        write_inserts(f, 'Person',
            ['ST_CASE', 'PER_NO', 'AGE', 'SEX', 'INJ_SEV', 'HOSPITAL', 'DOA'],
            persons,
            lambda r: [sql_int(r['ST_CASE']), sql_int(r['PER_NO']),
                        sql_int(r['AGE']), sql_int(r['SEX']),
                        sql_int(r['INJ_SEV']), sql_int(r['HOSPITAL']),
                        sql_int(r['DOA'])])

        # Pedestrian
        write_inserts(f, 'Pedestrian',
            ['PER_NO', 'ST_CASE'],
            pedestrians,
            lambda r: [sql_int(r['PER_NO']), sql_int(r['ST_CASE'])])

        # CarPerson
        write_inserts(f, 'CarPerson',
            ['PER_NO', 'ST_CASE', 'EJECTION', 'SEAT_POS', 'REST_USE'],
            car_persons,
            lambda r: [sql_int(r['PER_NO']), sql_int(r['ST_CASE']),
                        sql_int(r['EJECTION']), sql_int(r['SEAT_POS']),
                        sql_int(r['REST_USE'])])

        # Passenger
        write_inserts(f, 'Passenger',
            ['PER_NO', 'ST_CASE'],
            passengers,
            lambda r: [sql_int(r['PER_NO']), sql_int(r['ST_CASE'])])

        # Driver
        write_inserts(f, 'Driver',
            ['PER_NO', 'ST_CASE', 'DRINKING', 'DRUGS'],
            drivers,
            lambda r: [sql_int(r['PER_NO']), sql_int(r['ST_CASE']),
                        sql_int(r['DRINKING']), sql_int(r['DRUGS'])])

        # Rides_In
        write_inserts(f, 'Rides_In',
            ['PER_NO', 'ST_CASE', 'VIN'],
            rides_in,
            lambda r: [sql_int(r['PER_NO']), sql_int(r['ST_CASE']),
                        sql_str(r['VIN'])])

        # Involves
        write_inserts(f, 'Involves',
            ['ST_CASE', 'VIN', 'NUMOCCS', 'ROLLOVER', 'TRAV_SP',
             'IMPACT1', 'HIT_RUN', 'FIRE_EXP', 'TOWED', 'DEFORMED', 'VSPD_LIM'],
            involves,
            lambda r: [sql_int(r['ST_CASE']), sql_str(r['VIN']),
                        sql_int(r['NUMOCCS']), sql_int(r['ROLLOVER']),
                        sql_int(r['TRAV_SP']), sql_int(r['IMPACT1']),
                        sql_int(r['HIT_RUN']), sql_int(r['FIRE_EXP']),
                        sql_int(r['TOWED']), sql_int(r['DEFORMED']),
                        sql_int(r['VSPD_LIM'])])

        f.write("COMMIT;\n")

        # ----- Queries -----
        f.write(QUERIES)

    size_mb = os.path.getsize(OUTPUT) / (1024 * 1024)
    print(f"\nDone! Generated {OUTPUT} ({size_mb:.1f} MB)")
    print(f"Load into PostgreSQL:  psql -d <dbname> -f {OUTPUT}")


if __name__ == '__main__':
    main()
