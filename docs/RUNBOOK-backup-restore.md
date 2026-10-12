# Runbook — Backup & Restore (GAP-017)

**Scope:** PostgreSQL backups created by `app/services/backup_service.py`, scheduled
via pg_cron (`migrations/versions/20261012_backup_schedule.py`), monitored through
`/admin` backup routes and `model_monitoring_alerts`.

---

## 1. RPO / RTO Targets

| Metric | Target | How it is met |
|---|---|---|
| **RPO** (max data loss) | ≤ 24 h | Daily full backup at 02:00 (pg_cron `daily-backup`) + Render PITR on the managed instance as the second layer |
| **RTO** (max restore time) | ≤ 1 h | Single `pg_restore` to a fresh instance + `DATABASE_URL` repoint + smoke check (Section 4) |

If a >24 h backup gap is ever acceptable for a given data class, document it here —
do not silently widen the target.

---

## 2. Automated Schedule (as it exists today)

pg_cron jobs defined in `migrations/versions/20261012_backup_schedule.py`
(skipped gracefully with a NOTICE when pg_cron is unavailable — then enqueue
the same jobs from an external scheduler):

| pg_cron job | Schedule (server time) | Enqueued job | Handler |
|---|---|---|---|
| `daily-backup` | `0 2 * * *` (daily 02:00) | `create_backup` with `backup_name = daily_YYYYMMDD` | `_create_backup_handler` → `create_backup()` (backup_service.py:723-728) |
| `weekly-backup-verify` | `0 3 * * 0` (Sundays 03:00) | `verify_latest_backup` | `_verify_backup_handler` → `verify_latest_backup()` (backup_service.py:730-731) |
| `backup-retention` | `0 4 * * *` (daily 04:00) | `cleanup_old_backups` with `retention_days: 30` | `_cleanup_backups_handler` → `cleanup_old_backups()` (backup_service.py:733-734) |

Handlers are registered with `JobQueueService` at import time
(backup_service.py:720-741); jobs sit in the `job_queue` table until an
in-app or external worker processes them.

**Failure alerting:** `create_backup()` calls `_alert_backup_failure()`
(backup_service.py:35, fired at :343 and :399 on failure), which routes through
`_maybe_create_backup_failure_alert()` (monitoring_service.py:295) into
`model_monitoring_alerts` with `severity='critical'` (dedup-aware) and the
optional external notifier. A failed daily backup therefore surfaces as a
critical alert — check `/ai/monitoring/alerts` or the admin notification center.

**Verification cadence:** `verify_latest_backup()` (backup_service.py:664-699)
decrypts the newest backup, re-computes its SHA-256 checksum and compares it to
the stored checksum. It raises `ValueError` on missing file / missing key id /
checksum mismatch so the job queue records the failure. Retention
(`cleanup_old_backups()`, backup_service.py:702-717) soft-deletes backup
records older than 30 days.

---

## 3. Key Rotation — ⚠️ THE CRITICAL CONSTRAINT

**Read this before rotating any key.**

- The master key is `BACKUP_ENCRYPTION_KEY` from config, falling back to
  `SECRET_KEY` (`_get_master_key()`, backup_service.py:196-214).
- Each backup is encrypted with a key derived via **PBKDF2 (SHA-256, 100k
  iterations) using the backup's `key_id` as the salt, from the CURRENT master
  key** (`_derive_key(key_id)`, backup_service.py:217-227).
- There is **no key-version history**: decryption always re-derives from the
  *current* master key. **Rotating `BACKUP_ENCRYPTION_KEY` (or `SECRET_KEY`,
  if no dedicated backup key is set) makes every existing backup PERMANENTLY
  UNDECRYPTABLE** — checksum verification and restore both fail with
  decryption errors, silently defeating the entire backup program.

### Rotation procedure (choose ONE)

**Option A — archive old master keys (simplest, recommended):**
1. Generate the new key; store it in the secret manager.
2. Before switching, record the retiring master key alongside the `key_id`
   range it covers (e.g. `keys-archive.md` in the secret manager: key value,
   valid-from date, list of `encryption_key_id` values in `system_backups`
   created under it).
3. Switch the env var. Old backups stay decryptable only if the application
   is later taught to consult the archive — until then, treat archived-key
   backups as "restorable via manual `_derive_key` with the archived key".

**Option B — re-encrypt surviving backups under the new key (no archive needed):**
1. Decrypt every backup you intend to keep using the OLD master key
   (manual `_decrypt_file` with `_derive_key(key_id)` under the old key).
2. Re-encrypt under the NEW master key (new `key_id` per backup), update the
   `system_backups` rows (`encrypted`, `encryption_key_id`, checksum).
3. Only then retire the old key.
4. Run `verify_latest_backup()` (and spot-verify one older backup) before
   deleting the old key material.

**Rotation code is out of scope** — neither option is automated today. Until
one is implemented, the operational rule is: **do not rotate
`BACKUP_ENCRYPTION_KEY`/`SECRET_KEY` without executing Option A or B first.**
If `SECRET_KEY` is the effective master key (no dedicated backup key set),
this constraint also applies to routine `SECRET_KEY` rotation — set a dedicated
`BACKUP_ENCRYPTION_KEY` to decouple the two.

---

## 4. Restore Steps

1. **Verify the backup first** — run the weekly job's handler or trigger
   verification from the admin backup UI. `verify_latest_backup()` must report
   checksum OK (backup_service.py:664-699). Never restore from an unverified
   backup if a verified one exists.
2. **Provision a fresh PostgreSQL instance** (Render new instance or local
   container). Do not restore over the live database.
3. **Decrypt** the backup file if `encrypted = true` — requires the master key
   covering that backup's `encryption_key_id` (see Section 3).
4. **Restore:**
   ```bash
   pg_restore --no-owner --no-privileges -d <target-connection-string> <backup.sql>
   ```
   (Matches the flags used by the service's own restore path,
   backup_service.py:186-193.)
5. **Repoint `DATABASE_URL`** on the app service to the fresh instance and
   restart. Keep the old URL until the smoke check passes (rollback = repoint
   back).
6. **Smoke check:**
   - `GET /api/health` → 200 with `"database": "connected"`
   - Log in with a known account (e.g. `admin/Admin@123` in dev) → dashboard renders
   - Spot-check row counts: `SELECT COUNT(*) FROM products;` vs. expectation
7. **Close the incident:** note restore duration (RTO measurement), any data
   gap between last backup and failure time (RPO measurement), and file both
   in the quarterly drill log (Section 5).

---

## 5. Quarterly Drill Calendar

| Quarter | Drill | Owner | Evidence artifact |
|---|---|---|---|
| Q1 | Full restore to a fresh instance from the latest verified backup (Section 4, timed) | Backend lead | Restore log + smoke-check screenshot + RTO/RPO actuals in incident doc |
| Q2 | Verify-only: run `verify_latest_backup()` on prod + confirm pg_cron jobs fired in the last 90 days (`job_queue` history) | On-call engineer | Job-queue export + verification result |
| Q3 | Key-rotation tabletop: walk Option A/B from Section 3 against the current `system_backups` inventory; confirm archive/re-encrypt steps are executable | Backend lead + ops | Tabletop notes + updated key archive |
| Q4 | Partial-failure drill: restore from a 7-day-old backup (simulate corrupted latest), measure data gap vs. RPO | On-call engineer | Restore log + gap analysis |

Drill findings that change this runbook must update it in the same PR as the
drill's evidence commit.
