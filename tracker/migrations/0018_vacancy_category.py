from django.db import migrations, models

CATEGORY_HINTS = [
    ('Python', ('python',)),
    ('QA Engineer', ('qa', 'selenium', 'postman', 'pytest')),
    ('JavaScript', ('javascript', 'typescript', 'react', 'vue', 'angular', 'node')),
    ('Java', ('java',)),
    ('DevOps', ('docker', 'kubernetes', 'aws', 'ci/cd')),
    ('Data Science', ('pandas', 'machine learning', 'data')),
    ('.NET', ('c#', '.net')),
    ('PHP', ('php',)),
    ('C++', ('c++',)),
]


def fill_category(apps, schema_editor):
    Vacancy = apps.get_model('tracker', 'Vacancy')
    for vacancy in Vacancy.objects.filter(category='').prefetch_related('skills'):
        names = {skill.name for skill in vacancy.skills.all()} | set(vacancy.position.lower().split())
        for tag, hints in CATEGORY_HINTS:
            if any(h in names for h in hints):
                vacancy.category = tag
                vacancy.save(update_fields=['category'])
                break


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0017_remove_internship'),
    ]

    operations = [
        migrations.AddField(
            model_name='vacancy',
            name='category',
            field=models.CharField(blank=True, max_length=30, verbose_name='Категорія (тег Jobicy)'),
        ),
        migrations.RunPython(fill_category, migrations.RunPython.noop),
    ]
