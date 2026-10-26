from django.db import migrations


def clear_levels(apps, schema_editor):
    ProfileSkill = apps.get_model('tracker', 'ProfileSkill')
    ProfileSkill.objects.exclude(skill__category__in=['lang', 'spoken']).exclude(level='').update(level='')


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0019_vacancy_level'),
    ]

    operations = [
        migrations.RunPython(clear_levels, migrations.RunPython.noop),
    ]
