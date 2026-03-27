-- ============================================================
-- Example SQL Queries
-- ============================================================

-- Q1 (SELECT): Total fatalities per month
SELECT MONTH, SUM(FATALS) AS total_fatalities
FROM Crash
GROUP BY MONTH
ORDER BY MONTH;

-- Q2 (SELECT + JOIN): Crashes where at least one driver was drinking, with age and sex
SELECT c.ST_CASE, c.FATALS, p.AGE, p.SEX
FROM Crash c
JOIN Driver d ON c.ST_CASE = d.ST_CASE
JOIN Person p ON d.PER_NO = p.PER_NO AND d.ST_CASE = p.ST_CASE
WHERE d.DRINKING = 1;

-- Q3 (INSERT): Add a new crash record
INSERT INTO Crash (ST_CASE, PEDS, PERSONS, DAY, MONTH, YEAR, NOT_HOUR, ARR_HOUR, VE_TOTAL, ARR_MIN, MAN_COLL, NOT_MIN, FATALS, WEATHER, LGT_COND, WRK_ZONE)
VALUES (999999, 0, 2, 15, 6, 2023, 14, 14, 1, 30, 0, 25, 1, 1, 1, 0);

-- Verify the insert
SELECT * FROM Crash WHERE ST_CASE = 999999;

-- Q4 (UPDATE): Mark unknown sex values as NULL
UPDATE Person SET SEX = NULL WHERE SEX IN (8, 9);

-- Verify the update
SELECT COUNT(*) AS null_sex_count FROM Person WHERE SEX IS NULL;

-- Q5 (DELETE): Remove the test crash we inserted
DELETE FROM Crash WHERE ST_CASE = 999999;

-- Verify the delete
SELECT COUNT(*) AS should_be_zero FROM Crash WHERE ST_CASE = 999999;
