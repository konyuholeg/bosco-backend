
from django.db import migrations, models


def clear_invalid_english_levels(apps, schema_editor):
    """Для англійської діє шкала CEFR, тож старі рівні Beginner-Senior очищаємо."""
    ProfileSkill = apps.get_model('tracker', 'ProfileSkill')
    ProfileSkill.objects.filter(
        skill__name='english', level__in=['beginner', 'junior', 'middle', 'senior'],
    ).update(level='')


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0011_profileskill_level_optional'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='internship',
            options={'ordering': ['-id'], 'permissions': [('sync_vacancies', 'Може шукати та завантажувати вакансії з API')]},
        ),
        migrations.AlterField(
            model_name='profileskill',
            name='level',
            field=models.CharField(blank=True, choices=[('beginner', 'Beginner'), ('junior', 'Junior'), ('middle', 'Middle'), ('senior', 'Senior'), ('a1', 'A1'), ('a2', 'A2'), ('b1', 'B1'), ('b2', 'B2'), ('c1', 'C1'), ('c2', 'C2')], default='', max_length=10, verbose_name='Рівень володіння'),
        ),
        migrations.RunPython(clear_invalid_english_levels, migrations.RunPython.noop),
    ]
