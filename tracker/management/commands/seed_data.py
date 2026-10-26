from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from tracker.demo import fill_demo_data
from tracker.roles import ensure_guest_user


class Command(BaseCommand):
    help = "Заповнює базу даних мінімалістичними демонстраційними даними."

    def add_arguments(self, parser):
        parser.add_argument('--username', default='demo')

    def handle(self, *args, **kwargs):
        User = get_user_model()
        user, created = User.objects.get_or_create(username=kwargs['username'])
        if created:
            user.set_password('demo12345')
            user.save()

        fill_demo_data(user)
        ensure_guest_user()

        self.stdout.write(self.style.SUCCESS("[OK] Демо-дані створено: каталог вакансій, користувач demo, гість."))
