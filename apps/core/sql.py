"""SQL helpers for migrations: DB-level guarantees that survive any app bug."""


def forbid_delete(table):
    return (
        f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION ws_forbid_delete();",
        f"DROP TRIGGER IF EXISTS {table}_no_delete ON {table};",
    )


def append_only(table):
    return (
        f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION ws_append_only();",
        f"DROP TRIGGER IF EXISTS {table}_append_only ON {table};",
    )


def run(migrations, pairs):
    return [migrations.RunSQL(fwd, rev) for fwd, rev in pairs]
