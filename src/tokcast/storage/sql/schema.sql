-- tokcast storage schema.
-- Each data table has a `source_file` column. Re-ingesting a changed file deletes that
-- file's rows and inserts them again in one transaction ("delete + insert by
-- partition"), which makes every ingest idempotent: running it twice gives the same
-- result as running it once.

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
    is_sidechain              BOOLEAN NOT NULL
);
