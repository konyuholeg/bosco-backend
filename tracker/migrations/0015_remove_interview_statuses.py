from django.db import migrations, models

STATUS_CHOICES = [
    ('found', 'Знайдено'),
    ('applied', 'Подано заявку'),
    ('offer', 'Зацікавило'),
    ('rejected', 'Відмова'),
]
REMOVED = ['interview', 'tech_interview']


def merge_removed_statuses(apps, schema_editor):
    """Записи зі статусами «Інтерв'ю» і «Технічна співбесіда» переходять у «Подано заявку»."""
    for model_name in ('Internship', 'Application'):
        apps.get_model('tracker', model_name).objects.filter(status__in=REMOVED).update(status='applied')


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0014_stats_permission'),
    ]

    operations = [
        migrations.RunPython(merge_removed_statuses, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='application',
            name='status',
            field=models.CharField(choices=STATUS_CHOICES, default='found', max_length=20, verbose_name='Статус'),
        ),
        migrations.AlterField(
            model_name='internship',
            name='status',
            field=models.CharField(choices=STATUS_CHOICES, default='found', max_length=20, verbose_name='Статус'),
        ),
    ]
