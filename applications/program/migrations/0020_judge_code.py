from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("program", "0019_judge_evaluationcriterion_evaluation"),
    ]

    operations = [
        migrations.AddField(
            model_name="judge",
            name="code",
            # Must mirror models.Judge.code exactly. Uniqueness of the code
            # per madrasa is validated in the judges/edit_judge views —
            # MySQL has no conditional unique index support, so this is
            # deliberately NOT enforced with a DB constraint.
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
    ]
