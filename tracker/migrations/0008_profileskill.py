from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0007_copy_internships_to_new_models'),
    ]

    operations = [
        migrations.CreateModel(
            name='ProfileSkill',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('level', models.CharField(
                    choices=[('beginner', 'Beginner'), ('junior', 'Junior'), ('middle', 'Middle'), ('senior', 'Senior')],
                    default='junior', max_length=10, verbose_name='Рівень володіння')),
                ('profile', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name='skill_levels',
                    to='tracker.studentprofile', verbose_name='Профіль')),
                ('skill', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name='profile_levels',
                    to='tracker.skill', verbose_name='Навичка')),
            ],
            options={
                'verbose_name': 'Навичка профілю',
                'verbose_name_plural': 'Навички профілю',
                'ordering': ['skill__category', 'skill__title'],
            },
        ),
        migrations.AddConstraint(
            model_name='profileskill',
            constraint=models.UniqueConstraint(fields=('profile', 'skill'), name='uniq_profileskill_profile_skill'),
        ),
    ]
