
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="internship",
            name="description",
            field=models.TextField(blank=True, verbose_name="Опис"),
        ),
        migrations.AddField(
            model_name="internship",
            name="external_id",
            field=models.CharField(
                blank=True,
                max_length=50,
                null=True,
                unique=True,
                verbose_name="ID у зовнішньому API",
            ),
        ),
        migrations.AddField(
            model_name="internship",
            name="location",
            field=models.CharField(blank=True, max_length=100, verbose_name="Регіон"),
        ),
        migrations.AddField(
            model_name="internship",
            name="raw_json",
            field=models.JSONField(
                blank=True, null=True, verbose_name="Сира JSON-відповідь API"
            ),
        ),
        migrations.AddField(
            model_name="internship",
            name="salary",
            field=models.CharField(blank=True, max_length=100, verbose_name="Зарплата"),
        ),
        migrations.AddField(
            model_name="internship",
            name="source",
            field=models.CharField(
                blank=True, default="manual", max_length=30, verbose_name="Джерело"
            ),
        ),
        migrations.AlterField(
            model_name="internship",
            name="url",
            field=models.URLField(
                blank=True, max_length=500, verbose_name="Посилання на вакансію"
            ),
        ),
    ]
