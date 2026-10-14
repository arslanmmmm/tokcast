-- Usage per calendar day in the session time zone (timestamps are stored in UTC).
SELECT
    CAST(timezone('UTC', ts) AS DATE)  AS day,
    count(*)                           AS turns,
    sum(n_requests)::BIGINT            AS api_calls,
    sum(output_tokens)::BIGINT         AS output_tokens,
    sum(total_tokens)::BIGINT          AS total_tokens
FROM turns
WHERE ts >= $since
GROUP BY day
ORDER BY day;
