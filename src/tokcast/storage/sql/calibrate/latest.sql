-- The most recent reading of a window that hasn't reset yet.
SELECT used_pct, resets_at, ts, source
FROM usage_snapshots
WHERE "window" = $window AND resets_at > $now
ORDER BY ts DESC
LIMIT 1;
