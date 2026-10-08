import psycopg2

conn = psycopg2.connect('postgresql://postgres:UM*25ans12er@localhost:5432/inventory_db')
cur = conn.cursor()

# System Backups soft delete procedures
cur.execute("""
CREATE OR REPLACE FUNCTION sp_system_backup_list(
    p_limit INT DEFAULT 100,
    p_offset INT DEFAULT 0,
    p_include_deleted BOOLEAN DEFAULT FALSE
) RETURNS TABLE (
    id INT, backup_name VARCHAR, backup_type VARCHAR, file_path VARCHAR,
    size BIGINT, status VARCHAR, created_at TIMESTAMP, created_by INT,
    deleted_at TIMESTAMP, encrypted BOOLEAN, encryption_key_id VARCHAR, checksum VARCHAR,
    total_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    WITH filtered AS (
        SELECT *
        FROM system_backups
        WHERE (p_include_deleted = TRUE OR deleted_at IS NULL)
        ORDER BY created_at DESC
    )
    SELECT f.*, (SELECT COUNT(*) FROM filtered) AS total_count
    FROM filtered f
    LIMIT p_limit OFFSET p_offset;
END;
$$ LANGUAGE plpgsql;
""")

cur.execute("""
CREATE OR REPLACE FUNCTION sp_system_backup_find(p_id INT)
RETURNS SETOF system_backups AS $$
BEGIN
    RETURN QUERY SELECT * FROM system_backups WHERE id = p_id AND deleted_at IS NULL;
END;
$$ LANGUAGE plpgsql;
""")

cur.execute("""
CREATE OR REPLACE FUNCTION sp_system_backup_delete(p_id INT)
RETURNS VOID AS $$
BEGIN
    UPDATE system_backups SET deleted_at = NOW() WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;
""")

# System Config Overrides soft delete procedures
cur.execute("""
CREATE OR REPLACE FUNCTION sp_system_config_override_list(
    p_limit INT DEFAULT 100,
    p_offset INT DEFAULT 0,
    p_include_deleted BOOLEAN DEFAULT FALSE
) RETURNS TABLE (
    id INT, key VARCHAR, value TEXT, description TEXT, is_sensitive BOOLEAN,
    updated_at TIMESTAMP, updated_by INT, deleted_at TIMESTAMP,
    total_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    WITH filtered AS (
        SELECT *
        FROM system_config_overrides
        WHERE (p_include_deleted = TRUE OR deleted_at IS NULL)
        ORDER BY updated_at DESC
    )
    SELECT f.*, (SELECT COUNT(*) FROM filtered) AS total_count
    FROM filtered f
    LIMIT p_limit OFFSET p_offset;
END;
$$ LANGUAGE plpgsql;
""")

cur.execute("""
CREATE OR REPLACE FUNCTION sp_system_config_override_find(p_id INT)
RETURNS SETOF system_config_overrides AS $$
BEGIN
    RETURN QUERY SELECT * FROM system_config_overrides WHERE id = p_id AND deleted_at IS NULL;
END;
$$ LANGUAGE plpgsql;
""")

cur.execute("""
CREATE OR REPLACE FUNCTION sp_system_config_override_delete(p_id INT)
RETURNS VOID AS $$
BEGIN
    UPDATE system_config_overrides SET deleted_at = NOW() WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;
""")

# Scheduled Audit Reports soft delete procedures
cur.execute("""
CREATE OR REPLACE FUNCTION sp_scheduled_audit_report_list(
    p_limit INT DEFAULT 100,
    p_offset INT DEFAULT 0,
    p_active_only BOOLEAN DEFAULT FALSE,
    p_include_deleted BOOLEAN DEFAULT FALSE
) RETURNS TABLE (
    id INT, name VARCHAR, description TEXT, format VARCHAR, frequency VARCHAR,
    parameters JSON, next_run_time TIMESTAMP, last_run_time TIMESTAMP,
    is_active BOOLEAN, created_at TIMESTAMP, updated_at TIMESTAMP,
    created_by INT, updated_by INT, deleted_at TIMESTAMP,
    total_count BIGINT
) AS $$
BEGIN
    RETURN QUERY
    WITH filtered AS (
        SELECT *
        FROM scheduled_audit_reports
        WHERE (p_include_deleted = TRUE OR deleted_at IS NULL)
          AND (p_active_only = FALSE OR is_active = TRUE)
        ORDER BY created_at DESC
    )
    SELECT f.*, (SELECT COUNT(*) FROM filtered) AS total_count
    FROM filtered f
    LIMIT p_limit OFFSET p_offset;
END;
$$ LANGUAGE plpgsql;
""")

cur.execute("""
CREATE OR REPLACE FUNCTION sp_scheduled_audit_report_find(p_id INT)
RETURNS SETOF scheduled_audit_reports AS $$
BEGIN
    RETURN QUERY SELECT * FROM scheduled_audit_reports WHERE id = p_id AND deleted_at IS NULL;
END;
$$ LANGUAGE plpgsql;
""")

cur.execute("""
CREATE OR REPLACE FUNCTION sp_scheduled_audit_report_delete(p_id INT)
RETURNS VOID AS $$
BEGIN
    UPDATE scheduled_audit_reports SET deleted_at = NOW() WHERE id = p_id;
END;
$$ LANGUAGE plpgsql;
""")

conn.commit()
print('Stored procedures applied successfully')
cur.close()
conn.close()