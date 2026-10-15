-- tokcast storage schema.
-- Data tables are append-only: rows are upserted by id and never deleted when they
-- vanish from a log file (Claude Code rewrites and expires its logs). `source_file`
-- records where a row was first seen. Every ingest is idempotent: running it twice
-- gives the same result as running it once.

-- Bookkeeping: which files have been loaded, and in what state (size + mtime).
-- A file whose size and mtime are unchanged is skipped on the next run.
CREATE TABLE IF NOT EXISTS ingested_files (
    path          VARCHAR PRIMARY KEY,
    source        VARCHAR NOT NULL,
    size_bytes    BIGINT NOT NULL,
    mtime_ns      BIGINT NOT NULL,
    n_lines       INTEGER NOT NULL,
    n_errors      INTEGER NOT NULL,
    ingested_at   TIMESTAMP NOT NULL
);

-- Lines that could not be parsed. Kept so problems are visible, never fatal.
CREATE TABLE IF NOT EXISTS ingest_errors (
    source_file   VARCHAR NOT NULL,
    line_no       INTEGER NOT NULL,
    error         VARCHAR NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    session_id    VARCHAR PRIMARY KEY,
    source        VARCHAR NOT NULL,
    source_file   VARCHAR NOT NULL,
    project       VARCHAR,             -- last folder name of cwd
    cwd           VARCHAR,
    git_branch    VARCHAR,
    tool_version  VARCHAR
);

-- One row per human prompt. A prompt starts a turn.
CREATE TABLE IF NOT EXISTS prompts (
    prompt_id     VARCHAR PRIMARY KEY,
    session_id    VARCHAR NOT NULL,
    source_file   VARCHAR NOT NULL,
    line_no       INTEGER NOT NULL,
    ts            TIMESTAMP,           -- UTC
    kind          VARCHAR NOT NULL,    -- 'text', 'image', or a leading tag like 'bash-input'
    text          VARCHAR,             -- NULL when ingested with --no-text
    text_chars    INTEGER NOT NULL,
    text_sha256   VARCHAR NOT NULL,
    has_image     BOOLEAN NOT NULL
);

-- One row per API call, deduplicated by request id.
CREATE TABLE IF NOT EXISTS requests (
    request_id                VARCHAR PRIMARY KEY,
    session_id                VARCHAR NOT NULL,
    prompt_id                 VARCHAR,     -- the turn; NULL if it couldn't be linked
    source_file               VARCHAR NOT NULL,
    line_no                   INTEGER NOT NULL,
    ts                        TIMESTAMP,   -- UTC
    model                     VARCHAR,
    effort                    VARCHAR,
    stop_reason               VARCHAR,
    input_tokens              BIGINT NOT NULL,
    output_tokens             BIGINT NOT NULL,   -- includes thinking tokens
    cache_read_tokens         BIGINT NOT NULL,
    cache_creation_tokens     BIGINT NOT NULL,
    cache_creation_5m_tokens  BIGINT NOT NULL,
    cache_creation_1h_tokens  BIGINT NOT NULL,
    thinking_tokens           BIGINT NOT NULL,
    web_search_requests       INTEGER NOT NULL,
    web_fetch_requests        INTEGER NOT NULL,
    tool_names                VARCHAR[] NOT NULL,
    n_tool_calls              INTEGER NOT NULL,
    is_sidechain              BOOLEAN NOT NULL,
    agent_id                  VARCHAR      -- set for calls made by a subagent
);

-- Usage-limit readings: "X% of the 5-hour (or 7-day) limit used" at a moment in time,
-- captured by `tokcast statusline` or entered with `tokcast calibrate --used`.
-- The same reading seen again keeps its earliest time (when that % was first reached).
CREATE TABLE IF NOT EXISTS usage_snapshots (
    "window"      VARCHAR NOT NULL,    -- '5h' or '7d'
    resets_at     TIMESTAMP NOT NULL,  -- UTC; the window started 5 hours / 7 days earlier
    used_pct      DOUBLE NOT NULL,     -- 0..100
    ts            TIMESTAMP NOT NULL,  -- UTC, when this reading was taken
    source        VARCHAR NOT NULL,    -- 'statusline' or 'manual'
    session_id    VARCHAR,
    PRIMARY KEY ("window", resets_at, used_pct)
);

-- Migrations for databases created by older tokcast versions. Each is idempotent.
ALTER TABLE requests ADD COLUMN IF NOT EXISTS agent_id VARCHAR;
