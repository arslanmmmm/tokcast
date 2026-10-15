-- Derived views. Recomputed on every query, so they are always consistent with the
-- base tables and need no refresh step.

-- Token totals per API call, plus the turn each call belongs to.
-- "Tokens processed" counts everything the model read or wrote; this is the
-- definition tokcast predicts and reports everywhere.
--
-- Most calls were linked to their turn by the parser. Subagent calls live in a separate
-- file, so they are linked here instead: an ASOF JOIN picks the latest prompt in the
-- same session at or before the call's timestamp.
CREATE OR REPLACE VIEW v_requests AS
SELECT
    r.*,
    coalesce(r.prompt_id, p.prompt_id) AS turn_id,
    r.input_tokens + r.cache_read_tokens + r.cache_creation_tokens AS context_tokens,
    r.input_tokens + r.cache_read_tokens + r.cache_creation_tokens + r.output_tokens
        AS total_tokens,
    regexp_extract(r.model, '(opus|sonnet|haiku|fable)', 1) AS model_family,
    -- "Cost units": tokens weighted by their API price ratios (input 1, cache write 1.25
    -- for 5 minutes or 2 for 1 hour, cache read 0.1, output 5). Usage limits are assumed
    -- to weigh tokens the same way; `tokcast calibrate` learns the scale from real readings.
    -- Cast to DOUBLE: 1.25 * an integer is an exact DECIMAL in DuckDB, which arrives in
    -- Python as decimal.Decimal and breaks arithmetic with floats.
    CAST(r.input_tokens
        + 1.25 * r.cache_creation_5m_tokens
        + 2.0 * r.cache_creation_1h_tokens
        + 1.25 * greatest(r.cache_creation_tokens - r.cache_creation_5m_tokens
                          - r.cache_creation_1h_tokens, 0)
        + 0.1 * r.cache_read_tokens
        + 5.0 * r.output_tokens AS DOUBLE) AS weighted_tokens,
    -- Usage values that can't be right. Some Claude Code versions logged placeholder
    -- or incomplete counts; flagged calls are reported by `stats` and kept out of training.
    CASE
        WHEN r.thinking_tokens > r.output_tokens THEN 'thinking_exceeds_output'
        WHEN r.output_tokens = 0 THEN 'zero_output'
        WHEN r.input_tokens + r.cache_read_tokens + r.cache_creation_tokens = 0 THEN 'zero_input'
    END AS quality_flag
FROM requests r
ASOF LEFT JOIN prompts p
    ON r.session_id = p.session_id AND r.ts >= p.ts;

-- One row per turn: a human prompt plus every API call it triggered (the tool loop),
-- including calls made by subagents. This is the unit tokcast predicts.
CREATE OR REPLACE VIEW turns AS
WITH per_turn AS (
    SELECT
        turn_id,
        count(*)                         AS n_requests,
        -- SUM over BIGINT returns HUGEINT (int128) in DuckDB; cast back so pandas gets int64.
        sum(n_tool_calls)::BIGINT        AS n_tool_calls,
        sum(output_tokens)::BIGINT       AS output_tokens,
        sum(thinking_tokens)::BIGINT     AS thinking_tokens,
        sum(context_tokens)::BIGINT      AS input_processed_tokens,
        sum(total_tokens)::BIGINT        AS total_tokens,
        sum(weighted_tokens)             AS weighted_tokens,
        count(*) FILTER (WHERE agent_id IS NOT NULL)                        AS n_subagent_requests,
        count(quality_flag)              AS n_flagged_requests,
        coalesce(sum(total_tokens) FILTER (WHERE agent_id IS NOT NULL), 0)::BIGINT
                                         AS subagent_tokens,
        -- The main agent's first call shows how big the conversation already was, and
        -- which model and effort the user picked. (Subagent line numbers come from
        -- another file, so they are left out of these.)
        arg_min(context_tokens, line_no) FILTER (WHERE agent_id IS NULL) AS context_tokens_before,
        arg_min(model, line_no)          FILTER (WHERE agent_id IS NULL) AS model,
        arg_min(model_family, line_no)   FILTER (WHERE agent_id IS NULL) AS model_family,
        arg_min(effort, line_no)         FILTER (WHERE agent_id IS NULL) AS effort
    FROM v_requests
    WHERE turn_id IS NOT NULL
    GROUP BY turn_id
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
    coalesce(t.n_subagent_requests, 0)     AS n_subagent_requests,
    coalesce(t.n_flagged_requests, 0)      AS n_flagged_requests,
    t.context_tokens_before,
    coalesce(t.output_tokens, 0)           AS output_tokens,
    coalesce(t.thinking_tokens, 0)         AS thinking_tokens,
    coalesce(t.input_processed_tokens, 0)  AS input_processed_tokens,
    coalesce(t.subagent_tokens, 0)         AS subagent_tokens,
    coalesce(t.total_tokens, 0)            AS total_tokens,
    coalesce(t.weighted_tokens, 0)         AS weighted_tokens
FROM prompts p
LEFT JOIN per_turn t ON t.turn_id = p.prompt_id
LEFT JOIN sessions s USING (session_id);
