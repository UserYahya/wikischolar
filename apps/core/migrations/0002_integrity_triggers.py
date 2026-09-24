from django.db import migrations

from apps.core.sql import append_only, forbid_delete, run

FUNCTIONS = """
CREATE OR REPLACE FUNCTION ws_forbid_delete() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'Hard delete is disabled on table %. Use soft delete (is_deleted = true).', TG_TABLE_NAME
    USING ERRCODE = 'restrict_violation';
END; $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION ws_append_only() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'Table % is append-only (% not allowed).', TG_TABLE_NAME, TG_OP
    USING ERRCODE = 'restrict_violation';
END; $$ LANGUAGE plpgsql;
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [
        migrations.RunSQL(FUNCTIONS, "DROP FUNCTION IF EXISTS ws_forbid_delete(); DROP FUNCTION IF EXISTS ws_append_only();"),
        *run(migrations, [forbid_delete("admins"), append_only("audit_logs")]),
    ]
