-- Pending auth table for 2-round-trip authentication
CREATE TABLE IF NOT EXISTS auth_pending (
    nonce           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    username        TEXT NOT NULL,
    ip_address      TEXT,
    user_agent      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index for cleanup
CREATE INDEX IF NOT EXISTS idx_auth_pending_created ON auth_pending(created_at);
CREATE INDEX IF NOT EXISTS idx_auth_pending_user ON auth_pending(user_id);