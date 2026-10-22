CREATE TABLE IF NOT EXISTS planning_history (
    id uuid PRIMARY KEY,
    status text NOT NULL CHECK (status IN ('completed', 'failed')),
    product_card_id integer NOT NULL,
    quantity integer NOT NULL,
    created_at timestamptz NOT NULL,
    started_at timestamptz,
    finished_at timestamptz NOT NULL,
    calculation_seconds double precision,
    memory_start_bytes bigint,
    peak_rss_bytes bigint,
    memory_growth_bytes bigint,
    department_count integer NOT NULL,
    operation_count integer NOT NULL,
    plan_makespan_seconds integer,
    plan_work_seconds bigint,
    selected_department text,
    job_json jsonb NOT NULL,
    request_json jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS planning_history_finished_idx ON planning_history (finished_at DESC, id);
CREATE INDEX IF NOT EXISTS planning_history_status_finished_idx ON planning_history (status, finished_at DESC);
