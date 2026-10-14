-- The most expensive sessions, with the first prompt as a reminder of what they were.
SELECT
    session_id,
    any_value(project)                 AS project,
    min(ts)                            AS started,
    count(*)                           AS turns,
    sum(n_requests)::BIGINT            AS api_calls,
    sum(total_tokens)::BIGINT          AS total_tokens,
    arg_min(text, turn_index)          AS first_prompt
FROM turns
WHERE ts >= $since
GROUP BY session_id
ORDER BY total_tokens DESC
LIMIT $top;
