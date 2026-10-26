
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0015_remove_interview_statuses'),
    ]

    operations = [
        migrations.AddField(
            model_name='internship',
            name='is_hidden',
            field=models.BooleanField(default=False, verbose_name='Нецікаво (приховано зі списку)'),
        ),
    ]
