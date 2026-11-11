-- Combined authentication flow in 2 round trips (instead of 7-8)
-- Call 1: sp_auth_start(username, ip, user_agent) -> returns user data + stored hash + nonce
-- Call 2: sp_auth_finish(nonce, success, plain_password) -> records login/session or failure

-- Step 1: Start auth - find user, create pending token (NO rate limit check)
CREATE OR REPLACE FUNCTION sp_auth_start(
    p_username TEXT,
    p_ip_address TEXT,
    p_user_agent TEXT
) RETURNS TABLE(
    success BOOLEAN,
    nonce UUID,
    user_id INT,
    username TEXT,
    email TEXT,
    role TEXT,
    is_active BOOLEAN,
    password_hash TEXT,
    locked BOOLEAN,
    lockout_minutes INT,
    error_msg TEXT
) AS $$
DECLARE
    v_user_id INT;
    v_username TEXT;
    v_email TEXT;
    v_role TEXT;
    v_is_active BOOLEAN;
    v_password_hash TEXT;
    v_nonce UUID := gen_random_uuid();
BEGIN
    -- Find user
    SELECT users.id, users.username, users.email, users.role, users.is_active, users.password_hash
    INTO v_user_id, v_username, v_email, v_role, v_is_active, v_password_hash
    FROM users
    WHERE users.username = p_username AND users.deleted_at IS NULL;

    IF NOT FOUND OR NOT v_is_active OR v_password_hash IS NULL THEN
        RETURN QUERY SELECT FALSE, NULL::uuid, NULL::int, NULL::text, NULL::text, NULL::text, FALSE, NULL::text, 
            FALSE, 0, 'Invalid credentials';
        RETURN;
    END IF;

    -- Create pending auth record
    INSERT INTO auth_pending (nonce, user_id, username, ip_address, user_agent, created_at)
    VALUES (gen_random_uuid(), v_user_id, v_username, p_ip_address, p_user_agent, NOW())
    RETURNING auth_pending.nonce INTO v_nonce;

    -- Return user data with stored hash for bcrypt verification
    RETURN QUERY SELECT TRUE, v_nonce, v_user_id, v_username, v_email, 
        v_role, v_is_active, v_password_hash, 
        FALSE, 0, NULL;
END;
$$ LANGUAGE plpgsql;

-- Step 2: Finish auth - verify bcrypt result, record login/session or failure
CREATE OR REPLACE FUNCTION sp_auth_finish(
    p_nonce UUID,
    p_success BOOLEAN,
    p_password TEXT  -- plain password for audit (optional)
) RETURNS TABLE(
    success BOOLEAN,
    user_id INT,
    username TEXT,
    email TEXT,
    role TEXT,
    session_token TEXT,
    locked BOOLEAN,
    lockout_minutes INT,
    error_msg TEXT
) AS $$
DECLARE
    v_pending_user_id INT;
    v_pending_username TEXT;
    v_pending_ip TEXT;
    v_pending_user_agent TEXT;
    v_user_id INT;
    v_username TEXT;
    v_email TEXT;
    v_role TEXT;
    v_is_active BOOLEAN;
    v_password_hash TEXT;
    v_key TEXT;
    v_token TEXT;
BEGIN
    -- Get pending auth
    SELECT auth_pending.user_id, auth_pending.username, auth_pending.ip_address, auth_pending.user_agent
    INTO v_pending_user_id, v_pending_username, v_pending_ip, v_pending_user_agent
    FROM auth_pending
    WHERE auth_pending.nonce = p_nonce AND auth_pending.created_at > NOW() - INTERVAL '5 minutes'
    FOR UPDATE;

    IF NOT FOUND THEN
        RETURN QUERY SELECT FALSE, NULL, NULL, NULL, NULL, NULL, FALSE, 0, 'Invalid or expired nonce';
        RETURN;
    END IF;

    IF p_success THEN
        -- Verify user still exists and is active
        SELECT users.id, users.username, users.email, users.role, users.is_active, users.password_hash
        INTO v_user_id, v_username, v_email, v_role, v_is_active, v_password_hash
        FROM users
        WHERE users.id = v_pending_user_id AND users.deleted_at IS NULL;

        IF NOT FOUND THEN
            DELETE FROM auth_pending WHERE nonce = p_nonce;
            RETURN QUERY SELECT FALSE, NULL, NULL, NULL, NULL, NULL, FALSE, 0, 'User no longer active';
            RETURN;
        END IF;

        -- Create session
        INSERT INTO user_sessions (user_id, session_token, ip_address, user_agent, created_at, is_active)
        VALUES (v_user_id, encode(gen_random_bytes(32), 'hex'), v_pending_ip, v_pending_user_agent, NOW(), TRUE)
        RETURNING user_sessions.session_token INTO v_token;

        -- Record login timestamp
        UPDATE users SET last_login = NOW() WHERE id = v_user_id;

        -- Clear rate limit
        DELETE FROM rate_limit_state WHERE key = 'login:' || lower(v_pending_username);

        -- Audit
        INSERT INTO audit_log (user_id, action, target_type, target_id, detail, ip_address, created_at)
        VALUES (v_user_id, 'user.login', 'user', v_user_id, 
            jsonb_build_object('nonce', p_nonce), v_pending_ip, NOW());

        RETURN QUERY SELECT TRUE, v_user_id, v_username, v_email, v_role, v_token, FALSE, 0, NULL;

    ELSE
        -- Record failed attempt
        INSERT INTO rate_limit_state (key, count, window_start, expires_at, updated_at)
        VALUES ('login:' || lower(v_pending_username), 1, NOW(), NOW() + INTERVAL '15 minutes', NOW())
        ON CONFLICT (key) DO UPDATE SET
            count = CASE 
                WHEN rate_limit_state.window_start < NOW() - INTERVAL '15 minutes' THEN 1 
                ELSE rate_limit_state.count + 1 
            END,
            expires_at = EXCLUDED.expires_at,
            updated_at = NOW();

        -- Audit failed attempt
        INSERT INTO audit_log (user_id, action, target_type, target_id, detail, ip_address, created_at)
        VALUES (v_pending_user_id, 'user.login_failed', 'user', v_pending_user_id,
            jsonb_build_object('nonce', p_nonce), v_pending_ip, NOW());

        DELETE FROM auth_pending WHERE nonce = p_nonce;
        RETURN QUERY SELECT FALSE, v_pending_user_id, v_pending_username, NULL, NULL, 
            NULL, FALSE, 0, 'Invalid credentials';
    END IF;

    DELETE FROM auth_pending WHERE nonce = p_nonce;
END;
$$ LANGUAGE plpgsql;

-- Check rate limit (for Python gate 2)
CREATE OR REPLACE FUNCTION sp_check_rate_limit(p_username TEXT)
RETURNS TABLE(
    locked BOOLEAN,
    lockout_minutes INT
) AS $$
DECLARE
    v_key TEXT := 'login:' || lower(p_username);
    v_count INT;
    v_expires_at TIMESTAMPTZ;
BEGIN
    SELECT count, expires_at INTO v_count, v_expires_at
    FROM rate_limit_state WHERE key = v_key;
    
    IF v_count IS NOT NULL AND v_count >= 5 AND v_expires_at > NOW() THEN
        RETURN QUERY SELECT TRUE, EXTRACT(EPOCH FROM (v_expires_at - NOW()))::INT / 60 + 1;
        RETURN;
    END IF;
    RETURN QUERY SELECT FALSE, 0;
END;
$$ LANGUAGE plpgsql;

-- Record failed attempt (for Python gate 2)
CREATE OR REPLACE FUNCTION sp_record_failed_attempt(p_username TEXT)
RETURNS INT AS $$
DECLARE
    v_key TEXT := 'login:' || lower(p_username);
    v_new_count INT;
BEGIN
    INSERT INTO rate_limit_state (key, count, window_start, expires_at, updated_at)
    VALUES ('login:' || lower(p_username), 1, NOW(), NOW() + INTERVAL '15 minutes', NOW())
    ON CONFLICT (key) DO UPDATE SET
        count = CASE 
            WHEN rate_limit_state.window_start < NOW() - INTERVAL '15 minutes' THEN 1 
            ELSE rate_limit_state.count + 1 
        END,
        expires_at = EXCLUDED.expires_at,
        updated_at = NOW()
    RETURNING count INTO v_new_count;
    RETURN v_new_count;
END;
$$ LANGUAGE plpgsql;

-- Clear rate limit on success
CREATE OR REPLACE FUNCTION sp_clear_rate_limit(p_username TEXT)
RETURNS VOID AS $$
BEGIN
    DELETE FROM rate_limit_state WHERE key = 'login:' || lower(p_username);
END;
$$ LANGUAGE plpgsql;

-- Audit lockout trigger
CREATE OR REPLACE FUNCTION sp_audit_lockout(p_user_id INT, p_username TEXT, p_ip TEXT)
RETURNS VOID AS $$
BEGIN
    INSERT INTO audit_log (user_id, action, target_type, target_id, detail, ip_address, created_at)
    VALUES (p_user_id, 'user.account_locked', 'user', p_user_id, 
        jsonb_build_object('username', p_username), p_ip, NOW());
END;
$$ LANGUAGE plpgsql;

-- Cleanup old pending auth records (call from cleanup job)
CREATE OR REPLACE FUNCTION sp_auth_cleanup_pending()
RETURNS INT AS $$
DECLARE
    v_deleted INT;
BEGIN
    DELETE FROM auth_pending WHERE created_at < NOW() - INTERVAL '1 hour';
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;