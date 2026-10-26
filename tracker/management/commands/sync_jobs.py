from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from tracker.services import JOB_CATEGORIES, sync_all_categories


class Command(BaseCommand):
    help = "Стягує вакансії з Jobicy API (JSON) у каталог; з --username додає їх і в заявки користувача."

    def add_arguments(self, parser):
        parser.add_argument('--username', help='Додатково додати вакансії в заявки цього користувача')
        parser.add_argument('--tag', action='append', help='Тема пошуку (можна кілька); за замовчуванням усі')
        parser.add_argument('--count', type=int, default=15)

    def handle(self, *args, **options):
        user = None
        if options['username']:
            try:
                user = get_user_model().objects.get(username=options['username'])
            except get_user_model().DoesNotExist:
                raise CommandError('Користувача не знайдено')
        known = dict(JOB_CATEGORIES)
        categories = [(tag, known.get(tag, tag)) for tag in options['tag']] if options['tag'] else None
        created, updated, failed = sync_all_categories(user, options['count'], categories)
        if failed and len(failed) == len(categories or JOB_CATEGORIES):
            raise CommandError("Не вдалося отримати дані: " + ", ".join(failed))
        for title in failed:
            self.stderr.write(f"Не вдалося завантажити: {title}")
        self.stdout.write(self.style.SUCCESS(f"Нових: {created}, оновлено: {updated}"))
