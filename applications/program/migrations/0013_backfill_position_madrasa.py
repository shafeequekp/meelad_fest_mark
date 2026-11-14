from django.db import migrations


def backfill_madrasa(apps, schema_editor):
    """Assign existing global Position/Grade/GeneralPosition/GroupPosition rows
    to a madrasa so that old data remains usable after the per-madrasa scoping
    change.

    Legacy rows were created globally (``madrasa IS NULL``) and could contain
    duplicate names (e.g. two ``first`` Position rows saved by different
    madrasas before scoping existed). Because these models now enforce
    ``unique_together = (('madrasa', 'name'))``, duplicate names are spread
    across different madrasas (best-effort) and any extras that cannot be
    assigned are left with ``madrasa = NULL`` instead of being deleted, so
    existing ``Prize`` foreign-key references are always preserved.
    """
    Madrasa = apps.get_model('accounts', 'Madrasa')
    madrasas = list(Madrasa.objects.order_by('id'))
    if not madrasas:
        return  # no madrasas yet -> nothing to backfill

    for model_name in ('Position', 'Grade', 'GeneralPosition', 'GroupPosition'):
        Model = apps.get_model('program', model_name)
        rows = list(Model.objects.filter(madrasa__isnull=True).order_by('id'))

        for row in rows:
            # Find the first madrasa that does not already hold a row for this
            # name; skip it if a duplicate of the same name was already placed
            # there (either earlier in this backfill or by the new save_config).
            for madrasa in madrasas:
                already_taken = Model.objects.filter(
                    madrasa=madrasa, name=row.name
                ).exclude(pk=row.pk).exists()
                if not already_taken:
                    Model.objects.filter(pk=row.pk).update(madrasa=madrasa)
                    break
            # If every madrasa already has this name, leave the row NULL.


class Migration(migrations.Migration):

    dependencies = [
        ('program', '0012_alter_generalposition_options_alter_grade_options_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_madrasa, migrations.RunPython.noop),
    ]

