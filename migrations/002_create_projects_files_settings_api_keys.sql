CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    workspace_path TEXT NOT NULL DEFAULT '',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    archived_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT projects_name_not_blank CHECK (btrim(name) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS projects_user_name_unique
    ON projects (user_id, lower(name)) WHERE archived_at IS NULL;
CREATE INDEX IF NOT EXISTS projects_user_id_idx ON projects (user_id);
CREATE INDEX IF NOT EXISTS projects_updated_at_idx ON projects (updated_at DESC);

CREATE TABLE IF NOT EXISTS files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    chat_id UUID REFERENCES chats(id) ON DELETE SET NULL,
    original_name TEXT NOT NULL,
    storage_key TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    category TEXT NOT NULL DEFAULT 'document',
    size_bytes BIGINT NOT NULL DEFAULT 0 CHECK (size_bytes >= 0),
    checksum_sha256 TEXT,
    extraction_status TEXT NOT NULL DEFAULT 'pending'
        CHECK (extraction_status IN ('pending', 'processing', 'complete', 'failed', 'not_required')),
    extracted_text TEXT NOT NULL DEFAULT '',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT files_original_name_not_blank CHECK (btrim(original_name) <> ''),
    CONSTRAINT files_storage_key_not_blank CHECK (btrim(storage_key) <> '')
);

CREATE UNIQUE INDEX IF NOT EXISTS files_storage_key_unique ON files (storage_key);
CREATE INDEX IF NOT EXISTS files_user_id_idx ON files (user_id);
CREATE INDEX IF NOT EXISTS files_project_id_idx ON files (project_id);
CREATE INDEX IF NOT EXISTS files_chat_id_idx ON files (chat_id);
CREATE INDEX IF NOT EXISTS files_checksum_idx ON files (checksum_sha256)
    WHERE checksum_sha256 IS NOT NULL;

CREATE TABLE IF NOT EXISTS settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scope TEXT NOT NULL DEFAULT 'user',
    setting_key TEXT NOT NULL,
    setting_value JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT settings_scope_not_blank CHECK (btrim(scope) <> ''),
    CONSTRAINT settings_key_not_blank CHECK (btrim(setting_key) <> ''),
    CONSTRAINT settings_user_scope_key_unique UNIQUE (user_id, scope, setting_key)
);

CREATE INDEX IF NOT EXISTS settings_user_id_idx ON settings (user_id);

CREATE TABLE IF NOT EXISTS api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT 'default',
    encrypted_secret BYTEA NOT NULL,
    key_hint TEXT NOT NULL DEFAULT '',
    encryption_version SMALLINT NOT NULL DEFAULT 1 CHECK (encryption_version > 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT api_keys_provider_not_blank CHECK (btrim(provider) <> ''),
    CONSTRAINT api_keys_name_not_blank CHECK (btrim(name) <> ''),
    CONSTRAINT api_keys_user_provider_name_unique UNIQUE (user_id, provider, name)
);

CREATE INDEX IF NOT EXISTS api_keys_user_id_idx ON api_keys (user_id);
CREATE INDEX IF NOT EXISTS api_keys_provider_idx ON api_keys (provider);

DROP TRIGGER IF EXISTS projects_set_updated_at ON projects;
CREATE TRIGGER projects_set_updated_at
BEFORE UPDATE ON projects
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS files_set_updated_at ON files;
CREATE TRIGGER files_set_updated_at
BEFORE UPDATE ON files
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS settings_set_updated_at ON settings;
CREATE TRIGGER settings_set_updated_at
BEFORE UPDATE ON settings
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS api_keys_set_updated_at ON api_keys;
CREATE TRIGGER api_keys_set_updated_at
BEFORE UPDATE ON api_keys
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
