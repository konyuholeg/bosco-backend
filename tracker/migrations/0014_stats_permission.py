
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("tracker", "0013_status_offer_label_interested"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="application",
            options={
                "ordering": ["-created_at", "-id"],
                "permissions": [("view_stats", "Може переглядати статистику")],
                "verbose_name": "Заявка",
                "verbose_name_plural": "Заявки",
            },
        ),
    ]
