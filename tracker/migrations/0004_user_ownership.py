
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0003_profile_skills_length"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="internship",
            name="user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="internships",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Власник",
            ),
        ),
        migrations.AddField(
            model_name="studentprofile",
            name="user",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="student_profile",
                to=settings.AUTH_USER_MODEL,
                verbose_name="Користувач",
            ),
        ),
        migrations.AlterField(
            model_name="internship",
            name="external_id",
            field=models.CharField(
                blank=True,
                max_length=50,
                null=True,
                verbose_name="ID у зовнішньому API",
            ),
        ),
        migrations.AddConstraint(
            model_name="internship",
            constraint=models.UniqueConstraint(
                fields=("user", "external_id"), name="uniq_user_external_id"
            ),
        ),
    ]
