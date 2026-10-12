# "Upazila / Area" becomes "Thana": the model, table, column and the named constraints, index and
# trigger are renamed in place (no data is copied or lost). The new government list itself is
# applied by 0007.
from django.db import migrations, models

RENAMES = [
    ("ALTER TABLE thanas RENAME CONSTRAINT upazila_district_name_uniq TO thana_district_name_uniq;",
     "ALTER TABLE thanas RENAME CONSTRAINT thana_district_name_uniq TO upazila_district_name_uniq;"),
    ("ALTER TABLE thanas RENAME CONSTRAINT upazila_id_district_uniq TO thana_id_district_uniq;",
     "ALTER TABLE thanas RENAME CONSTRAINT thana_id_district_uniq TO upazila_id_district_uniq;"),
    ("ALTER TRIGGER upazilas_no_delete ON thanas RENAME TO thanas_no_delete;",
     "ALTER TRIGGER thanas_no_delete ON thanas RENAME TO upazilas_no_delete;"),
]


class Migration(migrations.Migration):
    # After every older migration that still names the upazilas table (registration.0002 adds the
    # composite FK in SQL), so a fresh install builds the old schema first and then renames it.
    dependencies = [("reference", "0005_school_area_optional"), ("registration", "0008_banner_leaflet_label")]

    operations = [
        migrations.RenameModel("Upazila", "Thana"),
        migrations.AlterModelTable("thana", "thanas"),
        migrations.RenameField("school", "upazila", "thana"),
        migrations.AlterField(
            "thana", "district",
            models.ForeignKey(on_delete=models.PROTECT, related_name="thanas", to="reference.district")),
        # Postgres indexes follow the column rename; only the name and the state's field list change.
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(
                "ALTER INDEX school_upz_status_idx RENAME TO school_thana_status_idx;",
                "ALTER INDEX school_thana_status_idx RENAME TO school_upz_status_idx;")],
            state_operations=[
                migrations.RemoveIndex("school", "school_upz_status_idx"),
                migrations.AddIndex("school", models.Index(fields=["thana", "verification_status"],
                                                           name="school_thana_status_idx")),
            ],
        ),
        # The unique constraints back the composite FK students(thana_id, district_id), so they are
        # renamed in SQL rather than dropped and re-added.
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(fwd, rev) for fwd, rev in RENAMES],
            state_operations=[
                migrations.RemoveConstraint("thana", "upazila_district_name_uniq"),
                migrations.RemoveConstraint("thana", "upazila_id_district_uniq"),
                migrations.AddConstraint("thana", models.UniqueConstraint(
                    fields=["district", "name"], name="thana_district_name_uniq")),
                migrations.AddConstraint("thana", models.UniqueConstraint(
                    fields=["id", "district"], name="thana_id_district_uniq")),
            ],
        ),
    ]
