-- Derived views. Recomputed on every query, so they are always consistent with the
-- base tables and need no refresh step.

-- Token totals per API call. "Tokens processed" counts everything the model read or
-- wrote; this is the definition tokcast predicts and reports everywhere.
CREATE OR REPLACE VIEW v_requests AS
SELECT
    *,
    input_tokens + cache_read_tokens + cache_creation_tokens AS context_tokens,
    input_tokens + cache_read_tokens + cache_creation_tokens + output_tokens AS total_tokens,
    regexp_extract(model, '(opus|sonnet|haiku|fable)', 1) AS model_family
FROM requests;

-- One row per turn: a human prompt plus every API call it triggered (the tool loop).
-- This is the unit tokcast predicts.
CREATE OR REPLACE VIEW turns AS
WITH per_turn AS (
    SELECT
        prompt_id,
        count(*)                         AS n_requests,
        -- SUM over BIGINT returns HUGEINT (int128) in DuckDB; cast back so pandas gets int64.
        sum(n_tool_calls)::BIGINT        AS n_tool_calls,
        sum(output_tokens)::BIGINT       AS output_tokens,
        sum(thinking_tokens)::BIGINT     AS thinking_tokens,
        sum(context_tokens)::BIGINT      AS input_processed_tokens,
        sum(total_tokens)::BIGINT        AS total_tokens,
        -- The first call of a turn shows how big the conversation already was.
        arg_min(context_tokens, line_no) AS context_tokens_before,
        arg_min(model, line_no)          AS model,
        arg_min(model_family, line_no)   AS model_family,
        arg_min(effort, line_no)         AS effort
    FROM v_requests
    WHERE prompt_id IS NOT NULL
    GROUP BY prompt_id
)
SELECT
    p.prompt_id                      AS turn_id,
    p.session_id,
    s.project,
    p.ts,
    row_number() OVER (PARTITION BY p.session_id ORDER BY p.line_no) AS turn_index,
    p.kind,
    p.text,
    p.text_chars,
    p.has_image,
    t.model,
    t.model_family,
    t.effort,
    coalesce(t.n_requests, 0)              AS n_requests,
    coalesce(t.n_tool_calls, 0)            AS n_tool_calls,
    t.context_tokens_before,
    coalesce(t.output_tokens, 0)           AS output_tokens,
    coalesce(t.thinking_tokens, 0)         AS thinking_tokens,
    coalesce(t.input_processed_tokens, 0)  AS input_processed_tokens,
    coalesce(t.total_tokens, 0)            AS total_tokens
FROM prompts p
LEFT JOIN per_turn t USING (prompt_id)
LEFT JOIN sessions s USING (session_id);
