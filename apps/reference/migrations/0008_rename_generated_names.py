# Finishes the "upazila" -> "thana" rename for the names Postgres and Django generated (the id
# sequence, primary key, Django's hashed index and foreign-key names), so `\d thanas` and
# docs/schema.sql no longer say upazila. Names only: nothing refers to them. Reverse: left as is.
from django.db import migrations

RENAME = r"""
DO $$
DECLARE r record;
BEGIN
  -- indexes (renaming a primary-key or unique index renames its constraint too) and sequences
  FOR r IN SELECT c.relname, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = current_schema() AND c.relkind IN ('i', 'S') AND c.relname LIKE '%upazila%'
  LOOP
    EXECUTE format('ALTER %s %I RENAME TO %I', CASE r.relkind WHEN 'S' THEN 'SEQUENCE' ELSE 'INDEX' END,
                   r.relname, replace(r.relname, 'upazila', 'thana'));
  END LOOP;
  -- constraints without an index of their own (foreign keys, checks)
  FOR r IN SELECT con.conname, cl.relname FROM pg_constraint con JOIN pg_class cl ON cl.oid = con.conrelid
           JOIN pg_namespace n ON n.oid = cl.relnamespace
           WHERE n.nspname = current_schema() AND con.conname LIKE '%upazila%'
  LOOP
    EXECUTE format('ALTER TABLE %I RENAME CONSTRAINT %I TO %I', r.relname, r.conname,
                   replace(r.conname, 'upazila', 'thana'));
  END LOOP;
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [("reference", "0007_government_thanas")]
    operations = [migrations.RunSQL(RENAME, migrations.RunSQL.noop)]
