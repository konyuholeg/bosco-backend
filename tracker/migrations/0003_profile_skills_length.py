
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0002_internship_api_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="studentprofile",
            name="skills",
            field=models.CharField(
                default="Python, SQL, REST",
                max_length=500,
                verbose_name="Навички (через кому)",
            ),
        ),
    ]
