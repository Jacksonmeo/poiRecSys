-- Data quality checks for the database-backed user trajectory flow.

SELECT COUNT(*) AS checkins_without_user
FROM checkins c
LEFT JOIN users u
    ON c.user_id = u.user_id
WHERE u.user_id IS NULL;

SELECT COUNT(*) AS checkins_without_poi
FROM checkins c
LEFT JOIN pois p
    ON c.venue_id = p.venue_id
WHERE p.venue_id IS NULL;

SELECT COUNT(*) AS checkins_without_timestamp
FROM checkins
WHERE utc_timestamp IS NULL;

SELECT s.session_id, s.checkin_count, COUNT(c.id) AS actual_checkin_count
FROM sessions s
LEFT JOIN checkins c
    ON c.session_id = s.session_id
GROUP BY s.session_id, s.checkin_count
HAVING s.checkin_count <> COUNT(c.id);
