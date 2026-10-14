-- Usage per project (the folder Claude Code was started in).
SELECT
    coalesce(project, 'unknown')       AS project,
    count(DISTINCT session_id)         AS sessions,
    count(*)                           AS turns,
    sum(total_tokens)::BIGINT          AS total_tokens,
    round(100 * sum(total_tokens) / sum(sum(total_tokens)) OVER (), 1) AS share_pct
FROM turns
WHERE ts >= $since
GROUP BY ALL
ORDER BY total_tokens DESC;
