-- One calibration point per usage reading: the % used, and the weighted tokens this
-- machine's logs show inside that window up to the moment of the reading.
-- Readings taken after the last ingested API call are skipped: their tokens aren't in the
-- database yet (they become usable after the next `tokcast ingest`).
WITH last_call AS (SELECT max(ts) AS ts FROM requests)
SELECT
    s."window",
    s.resets_at,
    s.used_pct,
    s.ts,
    s.source,
    (SELECT coalesce(sum(r.weighted_tokens), 0)
     FROM v_requests r
     WHERE r.ts >= s.resets_at - CASE s."window" WHEN '7d' THEN INTERVAL 7 DAY
                                                 ELSE INTERVAL 5 HOUR END
       AND r.ts <= s.ts)                         AS weighted_tokens
FROM usage_snapshots s, last_call
WHERE s."window" = $window
  AND s.ts <= last_call.ts + INTERVAL 1 MINUTE
ORDER BY s.ts;
