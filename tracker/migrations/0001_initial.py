
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Internship',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('company', models.CharField(max_length=100, verbose_name='Компанія (напр. EPAM, SoftServe)')),
                ('position', models.CharField(max_length=100, verbose_name='Позиція (напр. QA Trainee, Python Internship)')),
                ('status', models.CharField(choices=[('found', 'Знайдено'), ('applied', 'Подано заявку'), ('interview', "Інтерв'ю"), ('tech_interview', 'Технічна співбесіда'), ('offer', 'Оффер'), ('rejected', 'Відмова')], default='found', max_length=20, verbose_name='Статус')),
                ('required_skills', models.CharField(blank=True, max_length=255, verbose_name='Вимоги / Навички (через кому, напр. Python, SQL, REST)')),
                ('reminder_date', models.DateField(blank=True, null=True, verbose_name='Дата нагадування / співбесіди')),
                ('reminder_text', models.CharField(blank=True, max_length=200, verbose_name='Текст нагадування')),
                ('url', models.URLField(blank=True, verbose_name='Посилання на вакансію')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['-id'],
            },
        ),
        migrations.CreateModel(
            name='StudentProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('full_name', models.CharField(default='Олександр Коваленко', max_length=100, verbose_name="Ім'я студента")),
                ('skills', models.CharField(default='Python, SQL, REST', max_length=255, verbose_name='Навички (через кому)')),
            ],
        ),
    ]
