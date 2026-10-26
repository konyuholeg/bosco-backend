import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import connections

from tracker.models import STATUS_CHOICES, Application, Company, Skill, Vacancy

logger = logging.getLogger(__name__)

JOBICY_URL = 'https://jobicy.com/api/v2/remote-jobs'
JOBICY_TIMEOUT = 10
SOURCE_NAME = 'jobicy'

JOB_CATEGORIES = [
    ('Python', 'Python'),
    ('QA Engineer', 'QA'),
    ('JavaScript', 'JavaScript / Frontend'),
    ('Java', 'Java'),
    ('DevOps', 'DevOps'),
    ('Data Science', 'Data Science'),
    ('.NET', '.NET / C#'),
    ('PHP', 'PHP'),
    ('C++', 'C++'),
]

GROUP_CATEGORIES = {
    'Мови програмування': 'lang', 'Фреймворки': 'framework', 'Бази даних та API': 'db',
    'Тестування': 'testing', 'Інструменти та DevOps': 'devops', 'Веб та дані': 'web', 'Мови': 'spoken',
}

SKILL_GROUPS = [
    ('Мови програмування', [
        ('python', 'Python'), ('java', 'Java'), ('javascript', 'JavaScript'),
        ('typescript', 'TypeScript'), ('c#', 'C#'), ('c++', 'C++'), ('php', 'PHP'),
    ]),
    ('Фреймворки', [
        ('django', 'Django'), ('flask', 'Flask'), ('fastapi', 'FastAPI'), ('spring', 'Spring'),
        ('react', 'React'), ('vue', 'Vue'), ('angular', 'Angular'), ('node.js', 'Node.js'),
        ('laravel', 'Laravel'), ('.net', '.NET'),
    ]),
    ('Бази даних та API', [
        ('sql', 'SQL'), ('postgresql', 'PostgreSQL'), ('mysql', 'MySQL'), ('rest', 'REST'),
    ]),
    ('Тестування', [
        ('qa', 'QA'), ('selenium', 'Selenium'), ('postman', 'Postman'), ('pytest', 'Pytest'),
    ]),
    ('Інструменти та DevOps', [
        ('git', 'Git'), ('docker', 'Docker'), ('kubernetes', 'Kubernetes'), ('linux', 'Linux'),
        ('aws', 'AWS'), ('azure', 'Azure'), ('ci/cd', 'CI/CD'),
    ]),
    ('Веб та дані', [
        ('html', 'HTML'), ('css', 'CSS'), ('pandas', 'Pandas'), ('machine learning', 'Machine Learning'),
    ]),
    ('Мови', [('english', 'English')]),
]

LEVELED_GROUPS = ('Мови програмування', 'Мови')
LEVELED_SKILLS = {value for group, items in SKILL_GROUPS if group in LEVELED_GROUPS for value, _ in items}

SKILL_KEYWORDS = [value for _, items in SKILL_GROUPS for value, _ in items]


def strip_html(text):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', text or '')).strip()


def extract_skill_names(text):
    """Ключі навичок із довідника, що згадуються в тексті вакансії."""
    low = text.lower()
    return [
        kw for kw in SKILL_KEYWORDS
        if re.search(r'(?<![a-z0-9])' + re.escape(kw) + r'(?![a-z0-9])', low)
    ]


def salary_text(raw):
    low, high = raw.get('salaryMin'), raw.get('salaryMax')
    if not (low or high):
        return ''
    cur = raw.get('salaryCurrency') or ''
    period = raw.get('salaryPeriod') or ''
    return f"{low or ''}-{high or ''} {cur} {period}".strip()


def _to_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def ensure_skill_catalog():
    """Гарантує, що всі навички зі словника SKILL_GROUPS є в довіднику Skill."""
    existing = set(Skill.objects.filter(name__in=SKILL_KEYWORDS).values_list('name', flat=True))
    for group, items in SKILL_GROUPS:
        for value, label in items:
            if value not in existing:
                Skill.objects.create(name=value, title=label, category=GROUP_CATEGORIES.get(group, 'other'))


def fetch_jobicy(tag, count=15):
    """HTTP GET до Jobicy API (параметри в query string, відповідь JSON)."""
    response = requests.get(
        JOBICY_URL,
        params={'count': count, 'tag': tag},
        headers={'Accept': 'application/json', 'User-Agent': 'InternshipTracker/1.0'},
        timeout=JOBICY_TIMEOUT,
    )
    response.raise_for_status()
    return response, response.json().get('jobs', [])


def level_from_jobicy(value):
    """Поле jobLevel Jobicy (Senior, Midweight, Entry-Level, Junior, Director, Any) -> junior/middle/senior або ''."""
    text = str(value or '').lower()
    if 'junior' in text or 'entry' in text:
        return 'junior'
    if 'mid' in text:
        return 'middle'
    if 'senior' in text or 'director' in text or 'lead' in text:
        return 'senior'
    return ''


def save_jobs(raw_jobs, category=''):
    """
    Зберігає вакансії з відповіді API (разом із сирим JSON) у спільний каталог Vacancy.
    Повторний запуск не створює дублікатів: ключ (source, external_id).
    category — тег Jobicy, з якого завантажено вакансії (зберігається, якщо у вакансії ще немає категорії).
    Повертає (список вакансій, створено, оновлено).
    """
    ensure_skill_catalog()
    vacancies, created, updated = [], 0, 0
    for raw in raw_jobs:
        ext_id = str(raw.get('id') or '')
        if not ext_id:
            continue
        description = strip_html(raw.get('jobDescription') or raw.get('jobExcerpt'))
        title = raw.get('jobTitle', '')
        company, _ = Company.objects.get_or_create(name=(raw.get('companyName') or 'Без назви')[:100])
        vacancy, was_created = Vacancy.objects.update_or_create(
            source=SOURCE_NAME, external_id=ext_id,
            defaults={
                'company': company,
                'position': title[:100],
                'url': (raw.get('url') or '')[:500],
                'location': str(raw.get('jobGeo') or '')[:100],
                'is_remote': True,
                'salary': salary_text(raw)[:100],
                'salary_min': _to_int(raw.get('salaryMin')),
                'salary_max': _to_int(raw.get('salaryMax')),
                'description': description[:2000],
                'raw_json': raw,
                'level': level_from_jobicy(raw.get('jobLevel')),
            },
        )
        if category and not vacancy.category:
            vacancy.category = category[:30]
            vacancy.save(update_fields=['category'])
        if was_created:
            vacancy.skills.set(Skill.objects.filter(name__in=extract_skill_names(f"{title} {description}")))
            created += 1
        else:
            updated += 1
        vacancies.append(vacancy)
    return vacancies, created, updated


def track_found(user, vacancies):
    """
    Додає вакансії до заявок користувача зі статусом «Знайдено» (get_or_create).
    Наявні заявки, зокрема приховані кнопкою «Нецікаво», не змінюються. Повертає кількість нових.
    """
    existing = set(
        Application.objects.filter(user=user, vacancy__in=vacancies).values_list('vacancy_id', flat=True)
    )
    new = [Application(user=user, vacancy=v, status=STATUS_CHOICES[0][0]) for v in vacancies if v.pk not in existing]
    Application.objects.bulk_create(new, ignore_conflicts=True)
    return len(new)


def sync_jobicy(tag, count=15, user=None):
    """Завантажує одну категорію Jobicy в каталог (і в заявки користувача, якщо він указаний)."""
    _, raw_jobs = fetch_jobicy(tag, count)
    vacancies, created, updated = save_jobs(raw_jobs, tag)
    if user is not None:
        track_found(user, vacancies)
    return created, updated


def sync_all_categories(user=None, count=15, categories=None):
    """
    Паралельно завантажує категорії Jobicy (мережеві запити в потоках, запис у БД в основному потоці).
    Помилка однієї категорії не блокує решту. Вакансії потрапляють у каталог, а для user ще й
    у його заявки зі статусом «Знайдено».
    Повертає (створено, оновлено, назви_категорій_з_помилкою).
    """
    categories = categories or JOB_CATEGORIES
    created = updated = 0
    failed = []
    with ThreadPoolExecutor(max_workers=len(categories)) as pool:
        futures = [(title, pool.submit(fetch_jobicy, tag, count)) for tag, title in categories]
        for (tag, title), (_, future) in zip(categories, futures):
            try:
                _, raw_jobs = future.result()
            except (requests.RequestException, ValueError):
                failed.append(title)
                continue
            vacancies, c, u = save_jobs(raw_jobs, tag)
            if user is not None:
                track_found(user, vacancies)
            created += c
            updated += u
    return created, updated, failed


SYNC_LOCK_KEY = 'tracker:catalog-sync'
SYNC_RETRY_SECONDS = 300


def _run_background_sync():
    try:
        _, _, failed = sync_all_categories()
        if failed:
            logger.warning('Не вдалося завантажити категорії: %s', ', '.join(failed))
            cache.set(SYNC_LOCK_KEY, 1, SYNC_RETRY_SECONDS)
    finally:
        connections.close_all()


def start_background_sync():
    """
    Запускає завантаження каталогу у фоновому потоці, не частіше ніж раз на інтервал.
    Користувач тим часом вводить логін, а каталог наповнюється. Повертає True, якщо потік запущено.
    """
    if not settings.CATALOG_AUTO_SYNC:
        return False
    if not cache.add(SYNC_LOCK_KEY, 1, settings.CATALOG_SYNC_INTERVAL_MINUTES * 60):
        return False
    threading.Thread(target=_run_background_sync, name='catalog-sync', daemon=True).start()
    return True
