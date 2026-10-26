import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import tracker.validators


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


def copy_legacy_data(apps, schema_editor):
    """
    Переносить у нові моделі те, що користувач встиг створити в Internship після міграції 0007
    (повторний запуск безпечний), і навички з текстового StudentProfile.skills у ProfileSkill.
    """
    Internship = apps.get_model('tracker', 'Internship')
    Company = apps.get_model('tracker', 'Company')
    Skill = apps.get_model('tracker', 'Skill')
    Vacancy = apps.get_model('tracker', 'Vacancy')
    Application = apps.get_model('tracker', 'Application')
    Reminder = apps.get_model('tracker', 'Reminder')
    ProfileSkill = apps.get_model('tracker', 'ProfileSkill')
    StudentProfile = apps.get_model('tracker', 'StudentProfile')
    cache = {}

    for item in Internship.objects.exclude(user__isnull=True).order_by('id'):
        company, _ = Company.objects.get_or_create(name=(item.company or 'Без назви')[:100])
        source = item.source or 'manual'
        if item.external_id:
            vacancy = Vacancy.objects.filter(source=source, external_id=item.external_id).first()
        else:
            vacancy = Vacancy.objects.filter(
                source=source, external_id__isnull=True, company=company, position=item.position,
            ).first()
        if vacancy is None:
            raw = item.raw_json if isinstance(item.raw_json, dict) else {}
            vacancy = Vacancy.objects.create(
                company=company, position=item.position, url=item.url, location=item.location,
                is_remote=source == 'jobicy', salary=item.salary,
                salary_min=to_int(raw.get('salaryMin')), salary_max=to_int(raw.get('salaryMax')),
                description=item.description, source=source, external_id=item.external_id or None,
                raw_json=item.raw_json, created_by=item.user,
            )
            vacancy.skills.add(*[get_skill(Skill, n, cache) for n in split_skills(item.required_skills)])
        notes = item.reminder_text if item.reminder_text and not item.reminder_date else ''
        application, created = Application.objects.get_or_create(
            user_id=item.user_id, vacancy=vacancy,
            defaults={'status': item.status, 'notes': notes, 'is_hidden': item.is_hidden},
        )
        if created:
            Application.objects.filter(pk=application.pk).update(created_at=item.created_at)
        elif item.is_hidden and not application.is_hidden:
            Application.objects.filter(pk=application.pk).update(is_hidden=True)
        if item.reminder_date:
            Reminder.objects.get_or_create(
                application=application, remind_at=item.reminder_date,
                defaults={'text': item.reminder_text or 'Нагадування'},
            )

    for profile in StudentProfile.objects.exclude(user__isnull=True):
        for name in split_skills(profile.skills):
            ProfileSkill.objects.get_or_create(profile=profile, skill=get_skill(Skill, name, cache))
    StudentProfile.objects.filter(user__isnull=True).delete()


def drop_internship_content_type(apps, schema_editor):
    """Видаляє застарілий тип вмісту Internship разом із його правами (право sync_vacancies тепер у Vacancy)."""
    ContentType = apps.get_model('contenttypes', 'ContentType')
    ContentType.objects.filter(app_label='tracker', model='internship').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0016_internship_is_hidden'),
        ('contenttypes', '0002_remove_content_type_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='application',
            name='is_hidden',
            field=models.BooleanField(default=False, verbose_name='Нецікаво (приховано зі списку)'),
        ),
        migrations.AlterModelOptions(
            name='vacancy',
            options={
                'ordering': ['-created_at', '-id'],
                'permissions': [('sync_vacancies', 'Може завантажувати вакансії з API')],
                'verbose_name': 'Вакансія', 'verbose_name_plural': 'Вакансії',
            },
        ),
        migrations.RunPython(copy_legacy_data, migrations.RunPython.noop),
        migrations.RemoveField(model_name='studentprofile', name='skills'),
        migrations.AlterField(
            model_name='studentprofile',
            name='user',
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE, related_name='student_profile',
                to=settings.AUTH_USER_MODEL, verbose_name='Користувач',
            ),
        ),
        migrations.AlterField(
            model_name='application',
            name='applied_at',
            field=models.DateField(
                blank=True, null=True, validators=[tracker.validators.validate_not_future],
                verbose_name='Дата подачі заявки',
            ),
        ),
        migrations.DeleteModel(name='Internship'),
        migrations.RunPython(drop_internship_content_type, migrations.RunPython.noop),
    ]
