
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracker', '0012_cefr_levels_and_sync_permission'),
    ]

    operations = [
        migrations.AlterField(
            model_name='application',
            name='status',
            field=models.CharField(choices=[('found', 'Знайдено'), ('applied', 'Подано заявку'), ('interview', "Інтерв'ю"), ('tech_interview', 'Технічна співбесіда'), ('offer', 'Зацікавило'), ('rejected', 'Відмова')], default='found', max_length=20, verbose_name='Статус'),
        ),
        migrations.AlterField(
            model_name='internship',
            name='status',
            field=models.CharField(choices=[('found', 'Знайдено'), ('applied', 'Подано заявку'), ('interview', "Інтерв'ю"), ('tech_interview', 'Технічна співбесіда'), ('offer', 'Зацікавило'), ('rejected', 'Відмова')], default='found', max_length=20, verbose_name='Статус'),
        ),
    ]
