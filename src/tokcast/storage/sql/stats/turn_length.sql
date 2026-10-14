-- How turns get more expensive the longer a conversation runs.
SELECT
    CASE
        WHEN turn_index = 1   THEN '1'
        WHEN turn_index <= 5  THEN '2-5'
        WHEN turn_index <= 10 THEN '6-10'
        WHEN turn_index <= 20 THEN '11-20'
        ELSE '21+'
    END                                AS turn_number,
    count(*)                           AS turns,
    median(context_tokens_before)      AS median_context_before,
    median(n_requests)                 AS median_api_calls,
    median(total_tokens)               AS median_turn_tokens
FROM turns
WHERE ts >= $since AND n_requests > 0
GROUP BY turn_number
ORDER BY min(turn_index);
