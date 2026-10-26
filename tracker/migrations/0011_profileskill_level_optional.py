from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0010_studentprofile_known_skills_through'),
    ]

    operations = [
        migrations.AlterField(
            model_name='profileskill',
            name='level',
            field=models.CharField(
                blank=True, default='', max_length=10,
                choices=[('beginner', 'Beginner'), ('junior', 'Junior'), ('middle', 'Middle'), ('senior', 'Senior')],
                verbose_name='Рівень володіння'),
        ),
    ]
