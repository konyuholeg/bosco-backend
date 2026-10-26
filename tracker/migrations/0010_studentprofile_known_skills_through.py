from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0009_copy_known_skills_to_profileskill'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='studentprofile',
            name='known_skills',
        ),
        migrations.AddField(
            model_name='studentprofile',
            name='known_skills',
            field=models.ManyToManyField(
                blank=True, related_name='profiles', through='tracker.ProfileSkill',
                to='tracker.skill', verbose_name='Навички (довідник)'),
        ),
    ]
