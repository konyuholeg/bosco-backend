from django.db import migrations, models


def level_from_jobicy(value):
    text = str(value or '').lower()
    if 'junior' in text or 'entry' in text:
        return 'junior'
    if 'mid' in text:
        return 'middle'
    if 'senior' in text or 'director' in text or 'lead' in text:
        return 'senior'
    return ''


def fill_level(apps, schema_editor):
    Vacancy = apps.get_model('tracker', 'Vacancy')
    for vacancy in Vacancy.objects.exclude(raw_json=None):
        raw = vacancy.raw_json if isinstance(vacancy.raw_json, dict) else {}
        level = level_from_jobicy(raw.get('jobLevel'))
        if level:
            vacancy.level = level
            vacancy.save(update_fields=['level'])


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0018_vacancy_category'),
    ]

    operations = [
        migrations.AddField(
            model_name='vacancy',
            name='level',
            field=models.CharField(
                blank=True, choices=[('junior', 'Junior'), ('middle', 'Middle'), ('senior', 'Senior')],
                max_length=10, verbose_name='Потрібний рівень',
            ),
        ),
        migrations.RunPython(fill_level, migrations.RunPython.noop),
    ]
