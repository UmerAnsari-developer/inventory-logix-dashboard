"""One-off: enable RLS on all public tables in the live Supabase DB."""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()
dsn = os.environ["DATABASE_URL"]
conn = psycopg2.connect(dsn)
try:
    with conn.cursor() as cur:
        cur.execute("""
            DO $$
            DECLARE
                t TEXT;
            BEGIN
                FOR t IN
                    SELECT tablename FROM pg_tables
                    WHERE schemaname = 'public'
                      AND tablename NOT LIKE 'pg_%'
                      AND tablename NOT LIKE 'schema_%'
                LOOP
                    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
                END LOOP;
            END $$;
        """)
        cur.execute("""
            SELECT tablename, rowsecurity FROM pg_tables
            WHERE schemaname = 'public' ORDER BY tablename
        """)
        rows = cur.fetchall()
        print(f"RLS enabled on {sum(1 for _, r in rows if r)} / {len(rows)} tables:")
        for name, rls in rows:
            print(f"  {'OK ' if rls else 'OFF'} {name}")
    conn.commit()
finally:
    conn.close()
