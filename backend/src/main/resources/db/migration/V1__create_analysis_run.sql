-- One row per analysis the backend has asked the analysis service to perform.
--
-- The constraints at the bottom make impossible states unrepresentable: the
-- database itself refuses a row that says "succeeded" without a result, or
-- "running" with a finish time. Application code can have bugs; these cannot be
-- bypassed by any of them.

CREATE TABLE analysis_run (
    id            uuid        PRIMARY KEY,
    base_commit   text        NOT NULL,
    head_commit   text        NOT NULL,
    base_snapshot text        NOT NULL,
    head_snapshot text        NOT NULL,
    status        text        NOT NULL,
    complete      boolean,
    file_count    integer,
    symbol_count  integer,
    result        jsonb,
    error_code    text,
    error_detail  text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,

    CONSTRAINT analysis_run_status_known
        CHECK (status IN ('running', 'succeeded', 'failed')),
    CONSTRAINT analysis_run_commits_are_hashes
        CHECK (base_commit ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'
           AND head_commit ~ '^[0-9a-f]{40}([0-9a-f]{24})?$'),
    CONSTRAINT analysis_run_succeeded_has_result
        CHECK ((status = 'succeeded') = (result IS NOT NULL)),
    CONSTRAINT analysis_run_succeeded_has_summary
        CHECK ((status = 'succeeded') = (complete IS NOT NULL
                                         AND file_count IS NOT NULL
                                         AND symbol_count IS NOT NULL)),
    CONSTRAINT analysis_run_failed_has_error
        CHECK ((status = 'failed') = (error_code IS NOT NULL)),
    CONSTRAINT analysis_run_finished_when_done
        CHECK ((status = 'running') = (finished_at IS NULL))
);

-- The dashboard lists the most recent runs first.
CREATE INDEX analysis_run_created_at_idx ON analysis_run (created_at DESC);
