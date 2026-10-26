from django.db import migrations


def forwards(apps, schema_editor):
    StudentProfile = apps.get_model('tracker', 'StudentProfile')
    ProfileSkill = apps.get_model('tracker', 'ProfileSkill')
    for profile in StudentProfile.objects.all():
        for skill in profile.known_skills.all():
            ProfileSkill.objects.get_or_create(profile=profile, skill=skill, defaults={'level': 'junior'})


def backwards(apps, schema_editor):
    StudentProfile = apps.get_model('tracker', 'StudentProfile')
    ProfileSkill = apps.get_model('tracker', 'ProfileSkill')
    for item in ProfileSkill.objects.select_related('profile', 'skill'):
        item.profile.known_skills.add(item.skill)


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0008_profileskill'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
