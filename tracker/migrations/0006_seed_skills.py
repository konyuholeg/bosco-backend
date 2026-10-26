from django.db import migrations

SKILLS = [
    ('lang', [('python', 'Python'), ('java', 'Java'), ('javascript', 'JavaScript'),
              ('typescript', 'TypeScript'), ('c#', 'C#'), ('c++', 'C++'), ('php', 'PHP')]),
    ('framework', [('django', 'Django'), ('flask', 'Flask'), ('fastapi', 'FastAPI'), ('spring', 'Spring'),
                   ('react', 'React'), ('vue', 'Vue'), ('angular', 'Angular'), ('node.js', 'Node.js'),
                   ('laravel', 'Laravel'), ('.net', '.NET')]),
    ('db', [('sql', 'SQL'), ('postgresql', 'PostgreSQL'), ('mysql', 'MySQL'), ('rest', 'REST')]),
    ('testing', [('qa', 'QA'), ('selenium', 'Selenium'), ('postman', 'Postman'), ('pytest', 'Pytest')]),
    ('devops', [('git', 'Git'), ('docker', 'Docker'), ('kubernetes', 'Kubernetes'), ('linux', 'Linux'),
                ('aws', 'AWS'), ('azure', 'Azure'), ('ci/cd', 'CI/CD')]),
    ('web', [('html', 'HTML'), ('css', 'CSS'), ('pandas', 'Pandas'), ('machine learning', 'Machine Learning')]),
    ('spoken', [('english', 'English')]),
]


def seed_skills(apps, schema_editor):
    Skill = apps.get_model('tracker', 'Skill')
    for category, items in SKILLS:
        for name, title in items:
            Skill.objects.get_or_create(name=name, defaults={'title': title, 'category': category})


def unseed_skills(apps, schema_editor):
    Skill = apps.get_model('tracker', 'Skill')
    names = [name for _, items in SKILLS for name, _ in items]
    Skill.objects.filter(name__in=names, vacancies__isnull=True, profiles__isnull=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0005_company_skill_vacancy_application_reminder'),
    ]

    operations = [
        migrations.RunPython(seed_skills, unseed_skills),
    ]
