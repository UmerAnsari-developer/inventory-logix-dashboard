# Supabase + Render Deployment Guide

This app works with Supabase PostgreSQL as the database backend, hosted on Render.

## Quick Setup (5 minutes)

### 1. Create Supabase Project
1. Go to [supabase.com](https://supabase.com) → New Project
2. Name it, set password, choose region (prefer same region as Render: Oregon/us-west-2)
3. Wait ~2 minutes for provisioning

### 2. Get Database Connection String
In Supabase dashboard → **Settings → Database → Connection pooling** → **Transaction pooler** (port 6543):
```
postgresql://postgres:[YOUR_PASSWORD]@db.[PROJECT_REF].supabase.co:6543/postgres?sslmode=require
```
- Use the **Transaction pooler** (port 6543) for connection pooling via PgBouncer
- Replace `[YOUR_PASSWORD]` with your Supabase database password
- Replace `[PROJECT_REF]` with your project reference ID
- **Must use `sslmode=require`** (Supabase requires SSL)

### 3. Deploy to Render
**Option A: Blueprint (auto-wires Render Postgres, then override)**
1. Push to GitHub
2. Render Dashboard → New + → Blueprint → Connect repo
3. After deploy, go to service **Environment** → override `DATABASE_URL` with your Supabase pooler URL
4. Redeploy

**Option B: Manual service (cleaner for Supabase-only)**
1. Render Dashboard → New + → Web Service → Connect GitHub repo
2. Build Command: `pip install -r requirements.txt`
3. Start Command: `gunicorn run:app --workers 1 --threads 2 --timeout 120 --access-logfile -`
4. Health Check Path: `/api/health`
5. Environment Variables:
   ```
   FLASK_ENV=production
   DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@db.xxx.supabase.co:6543/postgres?sslmode=require
   SECRET_KEY=your-long-random-secret
   SENDGRID_API_KEY=SG.your-sendgrid-key
   MAIL_FROM=your-email@gmail.com
   MAIL_USE_TLS=true
   PASSWORD_RESET_TTL_MINUTES=30
   ```

### 4. Deploy & Verify
- Render auto-deploys on push
- First boot: schema created + demo data seeded (118 products, 36 suppliers, 8,400 movements)
- Login: `admin` / `Admin@123`

---

## Connection Pooling Notes

- Supabase uses **PgBouncer** (transaction pooler on port 6543)
- App uses `ThreadedConnectionPool` (1-20 connections) — works with PgBouncer
- Gunicorn: `--workers 1 --threads 2` → 1 process, 2 threads → pool handles concurrency
- If you see "connection pool exhausted", increase pool size in `app/database/connection.py` (`_POOL_SIZE = 20`)

### Troubleshooting

| Issue | Fix |
|-------|-----|
| `SSL SYSCALL error: EOF detected` | Use pooler port 6543 (not 5432) |
| `connection pool exhausted` | Reduce gunicorn workers to 1, or increase `_POOL_SIZE` |
| `password authentication failed` | Check password in connection string |
| `network is unreachable` | Verify Supabase allows connections from Render IPs (auto-allowed) |

---

## Why Supabase + Render?

| Feature | Supabase | Render Postgres |
|---------|----------|-----------------|
| Free tier | 500 MB | 1 GB |
| Connection pooling | Built-in PgBouncer | Manual |
| Auth/Storage/Realtime | Included | No |
| Dashboard | Modern | Basic |
| Regions | More options | Fewer |

---

## Environment Variables Summary

| Variable | Required | Example |
|----------|----------|---------|
| `DATABASE_URL` | Yes | `postgresql://postgres:pass@db.xxx.supabase.co:6543/postgres?sslmode=require` |
| `SENDGRID_API_KEY` | Yes (for emails) | `SG.xxxxx` |
| `SECRET_KEY` | Yes | `long-random-string` |
| `MAIL_FROM` | For emails | `you@gmail.com` |
| `MAIL_USE_TLS` | For emails | `true` |
| `SECRET_KEY` | Yes | `random-50-char-string` |
| `FLASK_ENV` | Yes | `production` |
| `PASSWORD_RESET_TTL_MINUTES` | Optional | `30` |

---

## First Boot Behavior

On first boot with a fresh Supabase DB:
1. `init_schema()` → creates all tables/indexes
2. `seed_database()` → inserts 3 users, 36 suppliers, 118 products, movements, POs
3. `etl_database()` → builds star schema (fact/dim tables)

Data is deterministic (same every time). No CSV needed — synthetic fallback used.

---

## Quick Test Locally (optional)

```bash
# Set local env to test against Supabase
export DATABASE_URL="postgresql://postgres:pass@db.xxx.supabase.co:6543/postgres?sslmode=require"
export SENDGRID_API_KEY=SG.xxx
export SECRET_KEY=test-secret
python run.py
```