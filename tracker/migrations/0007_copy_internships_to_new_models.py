from django.db import migrations

def split_skills(text):
    return [x.strip().lower() for x in (text or '').split(',') if x.strip()]


def to_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def get_skill(Skill, name, cache):
    if name not in cache:
        cache[name], _ = Skill.objects.get_or_create(
            name=name[:50], defaults={'title': name[:60], 'category': 'other'},
        )
    return cache[name]


def forwards(apps, schema_editor):
    Company = apps.get_model('tracker', 'Company')
    Skill = apps.get_model('tracker', 'Skill')
    Vacancy = apps.get_model('tracker', 'Vacancy')
    Application = apps.get_model('tracker', 'Application')
    Reminder = apps.get_model('tracker', 'Reminder')
    Internship = apps.get_model('tracker', 'Internship')
    StudentProfile = apps.get_model('tracker', 'StudentProfile')

    cache = {}

    for item in Internship.objects.all().order_by('id'):
        company, _ = Company.objects.get_or_create(name=(item.company or 'Без назви')[:100])
        raw = item.raw_json if isinstance(item.raw_json, dict) else {}
        defaults = {
            'company': company,
            'position': item.position,
            'url': item.url,
            'location': item.location,
            'is_remote': item.source == 'jobicy',
            'salary': item.salary,
            'salary_min': to_int(raw.get('salaryMin')),
            'salary_max': to_int(raw.get('salaryMax')),
            'description': item.description,
            'raw_json': item.raw_json,
        }
        if item.external_id:
            vacancy, _ = Vacancy.objects.get_or_create(
                source=item.source or 'manual', external_id=item.external_id, defaults=defaults,
            )
        else:
            vacancy = Vacancy.objects.create(
                source=item.source or 'manual', created_by=item.user, **defaults,
            )
        vacancy.skills.add(*[get_skill(Skill, n, cache) for n in split_skills(item.required_skills)])
        Vacancy.objects.filter(pk=vacancy.pk, created_at__gt=item.created_at).update(created_at=item.created_at)

        if item.user_id is None:
            continue

        notes = ''
        if item.reminder_text and not item.reminder_date:
            notes = item.reminder_text
        application, created = Application.objects.get_or_create(
            user_id=item.user_id, vacancy=vacancy,
            defaults={'status': item.status, 'notes': notes},
        )
        if created:
            Application.objects.filter(pk=application.pk).update(created_at=item.created_at)
        if item.reminder_date:
            Reminder.objects.get_or_create(
                application=application, remind_at=item.reminder_date,
                defaults={'text': item.reminder_text or 'Нагадування'},
            )

    for profile in StudentProfile.objects.all():
        names = split_skills(profile.skills)
        if names:
            profile.known_skills.add(*[get_skill(Skill, n, cache) for n in names])


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0006_seed_skills'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
