CREATE TABLE IF NOT EXISTS logs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    session_id UUID REFERENCES sessions(id) ON DELETE SET NULL,
    chat_id UUID REFERENCES chats(id) ON DELETE SET NULL,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    level TEXT NOT NULL DEFAULT 'info'
        CHECK (level IN ('debug', 'info', 'warning', 'error', 'critical')),
    event_name TEXT NOT NULL,
    message TEXT NOT NULL DEFAULT '',
    logger TEXT NOT NULL DEFAULT 'aios',
    request_id UUID,
    trace_id TEXT,
    source TEXT NOT NULL DEFAULT 'backend',
    duration_ms DOUBLE PRECISION CHECK (duration_ms IS NULL OR duration_ms >= 0),
    status_code INTEGER CHECK (status_code IS NULL OR status_code BETWEEN 100 AND 599),
    error_type TEXT,
    stack_trace TEXT,
    context JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT logs_event_name_not_blank CHECK (btrim(event_name) <> '')
);

CREATE INDEX IF NOT EXISTS logs_created_at_idx ON logs (created_at DESC);
CREATE INDEX IF NOT EXISTS logs_level_created_at_idx ON logs (level, created_at DESC);
CREATE INDEX IF NOT EXISTS logs_event_created_at_idx ON logs (event_name, created_at DESC);
CREATE INDEX IF NOT EXISTS logs_user_id_idx ON logs (user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS logs_session_id_idx ON logs (session_id) WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS logs_chat_id_idx ON logs (chat_id) WHERE chat_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS logs_request_id_idx ON logs (request_id) WHERE request_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS logs_trace_id_idx ON logs (trace_id) WHERE trace_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS logs_context_gin_idx ON logs USING GIN (context);

CREATE TABLE IF NOT EXISTS analytics (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    session_id UUID REFERENCES sessions(id) ON DELETE SET NULL,
    chat_id UUID REFERENCES chats(id) ON DELETE SET NULL,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    event_name TEXT NOT NULL,
    event_category TEXT NOT NULL DEFAULT 'product',
    anonymous_id TEXT,
    request_id UUID,
    provider TEXT,
    model TEXT,
    task_type TEXT,
    input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
    estimated_cost_usd NUMERIC(14, 8)
        CHECK (estimated_cost_usd IS NULL OR estimated_cost_usd >= 0),
    duration_ms DOUBLE PRECISION CHECK (duration_ms IS NULL OR duration_ms >= 0),
    success BOOLEAN,
    properties JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT analytics_event_name_not_blank CHECK (btrim(event_name) <> ''),
    CONSTRAINT analytics_category_not_blank CHECK (btrim(event_category) <> '')
);

CREATE INDEX IF NOT EXISTS analytics_occurred_at_idx ON analytics (occurred_at DESC);
CREATE INDEX IF NOT EXISTS analytics_event_time_idx ON analytics (event_name, occurred_at DESC);
CREATE INDEX IF NOT EXISTS analytics_category_time_idx ON analytics (event_category, occurred_at DESC);
CREATE INDEX IF NOT EXISTS analytics_user_id_idx ON analytics (user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS analytics_session_id_idx ON analytics (session_id) WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS analytics_provider_model_idx
    ON analytics (provider, model, occurred_at DESC) WHERE provider IS NOT NULL;
CREATE INDEX IF NOT EXISTS analytics_properties_gin_idx ON analytics USING GIN (properties);
