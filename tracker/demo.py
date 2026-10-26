from django.utils import timezone

from tracker.models import Application, Company, ProfileSkill, Reminder, Skill, StudentProfile, Vacancy
from tracker.services import ensure_skill_catalog

DEMO_SOURCE = 'demo'

DEMO_VACANCIES = [
    ("SoftServe", "Python Internship", ['python', 'sql', 'rest'], "Київ", 400, 600, "https://career.softserveinc.com"),
    ("EPAM", "QA Trainee", ['qa', 'sql', 'postman'], "Львів", 300, 450, "https://training.epam.ua"),
    ("Genesis", "Backend Trainee", ['python', 'sql', 'rest', 'docker'], "Київ", 500, 700, "https://gen.tech"),
    ("Ajax Systems", "Junior QA / Python Engineer", ['python', 'linux', 'pytest'], "Київ", 700, 900, "https://ajax.systems"),
    ("GlobalLogic", "Python BaseCamp", ['python', 'git', 'linux'], "Віддалено", None, None, "https://globallogic.com"),
    ("Luxoft", "Java Intern", ['java', 'spring', 'sql'], "Дніпро", 350, 500, "https://career.luxoft.com"),
    ("Intellias", "Frontend Trainee", ['javascript', 'html', 'css', 'react'], "Львів", 300, 480, "https://intellias.com"),
    ("Grammarly", "Data Science Intern", ['python', 'pandas', 'machine learning'], "Віддалено", 800, 1100, "https://grammarly.com"),
]

DEMO_APPLICATIONS = [
    (0, 'applied', 2, [(2, "Технічна співбесіда з техлідом (MS Teams)", False)]),
    (1, 'applied', 14, [(-3, "Очікую результатів вступного тесту з англійської", False)]),
    (2, 'applied', 4, [(1, "HR-скринінг дзвінок на 30 хвилин", False)]),
    (3, 'offer', 22, [(5, "Уточнити в рекрутера деталі та наступні кроки", False)]),
    (4, 'found', 45, [(12, "Дедлайн подачі анкети", False)]),
    (5, 'rejected', 30, [(-10, "Відповідь від рекрутера", True)]),
]


def fill_demo_data(user, full_name="Олександр Коваленко"):
    """Створює демонстраційний каталог, профіль, заявки та нагадування для переданого користувача."""
    ensure_skill_catalog()
    now = timezone.now()
    today = timezone.localdate()

    profile = StudentProfile.get_profile(user)
    profile.full_name = full_name
    profile.save()
    profile.skill_levels.all().delete()
    for name in ('python', 'sql', 'rest'):
        ProfileSkill.objects.create(profile=profile, skill=Skill.objects.get(name=name))

    vacancies = []
    for number, (company_name, position, skills, location, low, high, url) in enumerate(DEMO_VACANCIES, start=1):
        company, _ = Company.objects.get_or_create(name=company_name)
        vacancy, _ = Vacancy.objects.update_or_create(
            source=DEMO_SOURCE, external_id=f'demo-{number}',
            defaults={
                'company': company, 'position': position, 'url': url, 'location': location,
                'is_remote': location == "Віддалено", 'salary_min': low, 'salary_max': high,
                'salary': f"{low}-{high} USD" if low else '',
                'description': f"Демонстраційна вакансія: {position} у компанії {company_name}.",
            },
        )
        vacancy.skills.set(Skill.objects.filter(name__in=skills))
        vacancies.append(vacancy)

    Application.objects.filter(user=user).delete()
    for index, status, days_ago, reminders in DEMO_APPLICATIONS:
        application = Application.objects.create(
            user=user, vacancy=vacancies[index], status=status,
            applied_at=None if status == 'found' else today - timezone.timedelta(days=days_ago),
        )
        Application.objects.filter(pk=application.pk).update(created_at=now - timezone.timedelta(days=days_ago))
        for offset, text, done in reminders:
            Reminder.objects.create(
                application=application, remind_at=today + timezone.timedelta(days=offset), text=text, is_done=done,
            )
