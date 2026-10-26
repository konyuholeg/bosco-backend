
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0004_user_ownership'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Company',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100, unique=True, verbose_name='Назва')),
                ('website', models.URLField(blank=True, max_length=300, verbose_name='Сайт')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Створено')),
            ],
            options={
                'verbose_name': 'Компанія',
                'verbose_name_plural': 'Компанії',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='Skill',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=50, unique=True, verbose_name='Ключ (нижній регістр)')),
                ('title', models.CharField(max_length=60, verbose_name='Назва')),
                ('category', models.CharField(choices=[('lang', 'Мови програмування'), ('framework', 'Фреймворки'), ('db', 'Бази даних та API'), ('testing', 'Тестування'), ('devops', 'Інструменти та DevOps'), ('web', 'Веб та дані'), ('spoken', 'Мови спілкування'), ('other', 'Інше')], default='other', max_length=20, verbose_name='Категорія')),
            ],
            options={
                'verbose_name': 'Навичка',
                'verbose_name_plural': 'Навички',
                'ordering': ['category', 'title'],
            },
        ),
        migrations.AlterModelOptions(
            name='studentprofile',
            options={'verbose_name': 'Профіль студента', 'verbose_name_plural': 'Профілі студентів'},
        ),
        migrations.CreateModel(
            name='Application',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('found', 'Знайдено'), ('applied', 'Подано заявку'), ('interview', "Інтерв'ю"), ('tech_interview', 'Технічна співбесіда'), ('offer', 'Оффер'), ('rejected', 'Відмова')], default='found', max_length=20, verbose_name='Статус')),
                ('applied_at', models.DateField(blank=True, null=True, verbose_name='Дата подачі заявки')),
                ('notes', models.TextField(blank=True, verbose_name='Нотатки')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Створено')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Оновлено')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='applications', to=settings.AUTH_USER_MODEL, verbose_name='Власник')),
            ],
            options={
                'verbose_name': 'Заявка',
                'verbose_name_plural': 'Заявки',
                'ordering': ['-created_at', '-id'],
            },
        ),
        migrations.CreateModel(
            name='Reminder',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('remind_at', models.DateField(verbose_name='Дата')),
                ('text', models.CharField(max_length=200, verbose_name='Текст нагадування')),
                ('is_done', models.BooleanField(default=False, verbose_name='Виконано')),
                ('application', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reminders', to='tracker.application', verbose_name='Заявка')),
            ],
            options={
                'verbose_name': 'Нагадування',
                'verbose_name_plural': 'Нагадування',
                'ordering': ['is_done', 'remind_at'],
            },
        ),
        migrations.AddField(
            model_name='studentprofile',
            name='known_skills',
            field=models.ManyToManyField(blank=True, related_name='profiles', to='tracker.skill', verbose_name='Навички (довідник)'),
        ),
        migrations.CreateModel(
            name='Vacancy',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('position', models.CharField(max_length=100, verbose_name='Позиція')),
                ('url', models.URLField(blank=True, max_length=500, verbose_name='Посилання на вакансію')),
                ('location', models.CharField(blank=True, max_length=100, verbose_name='Регіон')),
                ('is_remote', models.BooleanField(default=False, verbose_name='Віддалена робота')),
                ('salary', models.CharField(blank=True, max_length=100, verbose_name='Зарплата (текст)')),
                ('salary_min', models.PositiveIntegerField(blank=True, null=True, verbose_name='Зарплата від')),
                ('salary_max', models.PositiveIntegerField(blank=True, null=True, verbose_name='Зарплата до')),
                ('description', models.TextField(blank=True, verbose_name='Опис')),
                ('source', models.CharField(default='manual', max_length=30, verbose_name='Джерело')),
                ('external_id', models.CharField(blank=True, max_length=50, null=True, verbose_name='ID у зовнішньому API')),
                ('raw_json', models.JSONField(blank=True, null=True, verbose_name='Сира JSON-відповідь API')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Додано')),
                ('company', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='vacancies', to='tracker.company', verbose_name='Компанія')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='added_vacancies', to=settings.AUTH_USER_MODEL, verbose_name='Хто додав')),
                ('skills', models.ManyToManyField(blank=True, related_name='vacancies', to='tracker.skill', verbose_name='Вимоги (навички)')),
            ],
            options={
                'verbose_name': 'Вакансія',
                'verbose_name_plural': 'Вакансії',
                'ordering': ['-created_at', '-id'],
            },
        ),
        migrations.AddField(
            model_name='application',
            name='vacancy',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='applications', to='tracker.vacancy', verbose_name='Вакансія'),
        ),
        migrations.AddConstraint(
            model_name='vacancy',
            constraint=models.UniqueConstraint(fields=('source', 'external_id'), name='uniq_vacancy_source_external_id'),
        ),
        migrations.AddConstraint(
            model_name='application',
            constraint=models.UniqueConstraint(fields=('user', 'vacancy'), name='uniq_application_user_vacancy'),
        ),
    ]
