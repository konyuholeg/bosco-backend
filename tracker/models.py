from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from tracker.validators import validate_not_future


STATUS_CHOICES = [
    ('found', 'Знайдено'),
    ('applied', 'Подано заявку'),
    ('offer', 'Зацікавило'),
    ('rejected', 'Відмова'),
]


SETTABLE_STATUSES = [s for s in STATUS_CHOICES if s[0] != 'found']


class Company(models.Model):
    """Компанія-роботодавець (довідник)."""
    name = models.CharField(max_length=100, unique=True, verbose_name="Назва")
    website = models.URLField(max_length=300, blank=True, verbose_name="Сайт")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Створено")

    class Meta:
        ordering = ['name']
        verbose_name = "Компанія"
        verbose_name_plural = "Компанії"

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('tracker:company_detail', args=[self.pk])


class Skill(models.Model):
    """Навичка / технологія (довідник для вимог вакансій і профілю студента)."""
    CATEGORY_CHOICES = [
        ('lang', 'Мови програмування'),
        ('framework', 'Фреймворки'),
        ('db', 'Бази даних та API'),
        ('testing', 'Тестування'),
        ('devops', 'Інструменти та DevOps'),
        ('web', 'Веб та дані'),
        ('spoken', 'Мови спілкування'),
        ('other', 'Інше'),
    ]

    name = models.CharField(max_length=50, unique=True, verbose_name="Ключ (нижній регістр)")
    title = models.CharField(max_length=60, verbose_name="Назва")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='other', verbose_name="Категорія")

    class Meta:
        ordering = ['category', 'title']
        verbose_name = "Навичка"
        verbose_name_plural = "Навички"

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('tracker:skill_detail', args=[self.pk])


class StudentProfile(models.Model):
    """Профіль студента; навички зберігаються через ProfileSkill (M2M з рівнем)."""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='student_profile',
        verbose_name="Користувач",
    )
    full_name = models.CharField(max_length=100, default="Олександр Коваленко", verbose_name="Ім'я студента")
    known_skills = models.ManyToManyField(
        'Skill', through='ProfileSkill', related_name='profiles', blank=True,
        verbose_name="Навички (довідник)",
    )

    class Meta:
        verbose_name = "Профіль студента"
        verbose_name_plural = "Профілі студентів"

    def __str__(self):
        return f"{self.full_name} ({self.user})"

    def skill_level_map(self):
        """Словник {ключ навички: рівень володіння} (порожній рядок, якщо рівень не вказано)."""
        items = self.skill_levels.select_related('skill')
        return {
            item.skill.name: (item.level if item.skill.category in ('lang', 'spoken') else '')
            for item in items
        }

    def skill_names(self):
        """Множина ключів навичок студента (нижній регістр) для порівняння з вимогами вакансій."""
        return set(self.known_skills.values_list('name', flat=True))

    @classmethod
    def get_profile(cls, user):
        """Профіль користувача (створюється при першому зверненні)."""
        profile, _ = cls.objects.get_or_create(user=user)
        return profile


class ProfileSkill(models.Model):
    """Навичка студента з рівнем володіння (проміжна модель M2M)."""
    LEVEL_CHOICES = [
        ('beginner', 'Beginner'),
        ('junior', 'Junior'),
        ('middle', 'Middle'),
        ('senior', 'Senior'),
    ]
    LANGUAGE_LEVEL_CHOICES = [
        ('a1', 'A1'), ('a2', 'A2'), ('b1', 'B1'), ('b2', 'B2'), ('c1', 'C1'), ('c2', 'C2'),
    ]
    LANGUAGE_SKILLS = {'english'}

    @classmethod
    def choices_for(cls, skill_name):
        """Шкала рівнів для навички: CEFR для мов спілкування, інакше Beginner-Senior."""
        return cls.LANGUAGE_LEVEL_CHOICES if skill_name in cls.LANGUAGE_SKILLS else cls.LEVEL_CHOICES

    profile = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE, related_name='skill_levels', verbose_name="Профіль",
    )
    skill = models.ForeignKey(
        Skill, on_delete=models.CASCADE, related_name='profile_levels', verbose_name="Навичка",
    )
    level = models.CharField(
        max_length=10, choices=LEVEL_CHOICES + LANGUAGE_LEVEL_CHOICES, blank=True, default='',
        verbose_name="Рівень володіння",
    )

    class Meta:
        ordering = ['skill__category', 'skill__title']
        verbose_name = "Навичка профілю"
        verbose_name_plural = "Навички профілю"
        constraints = [
            models.UniqueConstraint(fields=['profile', 'skill'], name='uniq_profileskill_profile_skill'),
        ]

    def __str__(self):
        if self.level:
            return f"{self.skill} — {self.get_level_display()}"
        return str(self.skill)


LEVEL_RANK = {'beginner': 1, 'junior': 2, 'middle': 3, 'senior': 4}


class Vacancy(models.Model):
    """Вакансія в загальному каталозі (доступна для перегляду всім)."""
    company = models.ForeignKey(
        Company, on_delete=models.PROTECT, related_name='vacancies', verbose_name="Компанія",
    )
    position = models.CharField(max_length=100, verbose_name="Позиція")
    skills = models.ManyToManyField(
        Skill, related_name='vacancies', blank=True, verbose_name="Вимоги (навички)",
    )
    url = models.URLField(max_length=500, blank=True, verbose_name="Посилання на вакансію")
    location = models.CharField(max_length=100, blank=True, verbose_name="Регіон")
    is_remote = models.BooleanField(default=False, verbose_name="Віддалена робота")
    salary = models.CharField(max_length=100, blank=True, verbose_name="Зарплата (текст)")
    salary_min = models.PositiveIntegerField(null=True, blank=True, verbose_name="Зарплата від")
    salary_max = models.PositiveIntegerField(null=True, blank=True, verbose_name="Зарплата до")
    description = models.TextField(blank=True, verbose_name="Опис")
    source = models.CharField(max_length=30, default='manual', verbose_name="Джерело")
    external_id = models.CharField(max_length=50, null=True, blank=True, verbose_name="ID у зовнішньому API")
    raw_json = models.JSONField(null=True, blank=True, verbose_name="Сира JSON-відповідь API")
    category = models.CharField(max_length=30, blank=True, verbose_name="Категорія (тег Jobicy)")
    LEVEL_CHOICES = [('junior', 'Junior'), ('middle', 'Middle'), ('senior', 'Senior')]
    level = models.CharField(max_length=10, choices=LEVEL_CHOICES, blank=True, verbose_name="Потрібний рівень")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='added_vacancies', verbose_name="Хто додав",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Додано")

    class Meta:
        ordering = ['-created_at', '-id']
        verbose_name = "Вакансія"
        verbose_name_plural = "Вакансії"
        permissions = [('sync_vacancies', 'Може завантажувати вакансії з API')]
        constraints = [
            models.UniqueConstraint(fields=['source', 'external_id'], name='uniq_vacancy_source_external_id'),
        ]

    def __str__(self):
        return f"{self.company} — {self.position}"

    def get_absolute_url(self):
        return reverse('tracker:vacancy_detail', args=[self.pk])

    def ai_match(self, owned_names):
        """
        AI-аналіз: порівнює вимоги вакансії (Vacancy.skills) з навичками студента.
        owned_names — множина навичок або словник {навичка: рівень}. Якщо у вакансії вказано рівень,
        а студент володіє навичкою нижче за потрібний, навичка потрапляє в below і дає половину бала.
        Повертає % збігу, назви збіглих, нижчих за рівнем і відсутніх навичок.
        """
        required = list(self.skills.all())
        if not required:
            return {'score': 100, 'matched': [], 'below': [], 'missing': []}
        levels = owned_names if isinstance(owned_names, dict) else {}
        need = LEVEL_RANK.get(self.level, 0)
        matched, below, missing = [], [], []
        for skill in required:
            if skill.name not in owned_names:
                missing.append(skill.title)
                continue
            have = LEVEL_RANK.get(levels.get(skill.name, ''), 0)
            (below if need and have and have < need else matched).append(skill.title)
        score = int((len(matched) + 0.5 * len(below)) / len(required) * 100)
        return {'score': score, 'matched': matched, 'below': below, 'missing': missing}


class Application(models.Model):
    """Запис користувача про відбір на вакансію (статус воронки)."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='applications', verbose_name="Власник",
    )
    vacancy = models.ForeignKey(
        Vacancy, on_delete=models.PROTECT, related_name='applications', verbose_name="Вакансія",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='found', verbose_name="Статус")
    applied_at = models.DateField(
        null=True, blank=True, validators=[validate_not_future], verbose_name="Дата подачі заявки",
    )
    notes = models.TextField(blank=True, verbose_name="Нотатки")
    is_hidden = models.BooleanField(default=False, verbose_name="Нецікаво (приховано зі списку)")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Створено")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Оновлено")

    class Meta:
        ordering = ['-created_at', '-id']
        permissions = [('view_stats', 'Може переглядати статистику')]
        verbose_name = "Заявка"
        verbose_name_plural = "Заявки"
        constraints = [
            models.UniqueConstraint(fields=['user', 'vacancy'], name='uniq_application_user_vacancy'),
        ]

    def __str__(self):
        return f"{self.vacancy} [{self.get_status_display()}]"

    def get_absolute_url(self):
        return reverse('tracker:application_detail', args=[self.pk])

    def ai_match(self, owned_names):
        return self.vacancy.ai_match(owned_names)

    @property
    def next_reminder(self):
        """Найближче невиконане нагадування (використовує prefetch_related('reminders'))."""
        pending = [r for r in self.reminders.all() if not r.is_done]
        return pending[0] if pending else None


class Reminder(models.Model):
    """Нагадування до заявки (співбесіда, дедлайн тестового тощо)."""
    application = models.ForeignKey(
        Application, on_delete=models.CASCADE, related_name='reminders', verbose_name="Заявка",
    )
    remind_at = models.DateField(verbose_name="Дата")
    text = models.CharField(max_length=200, verbose_name="Текст нагадування")
    is_done = models.BooleanField(default=False, verbose_name="Виконано")

    class Meta:
        ordering = ['is_done', 'remind_at']
        verbose_name = "Нагадування"
        verbose_name_plural = "Нагадування"

    def __str__(self):
        return f"{self.remind_at:%d.%m.%Y} — {self.text}"

    SOON_DAYS = 3

    def get_absolute_url(self):
        return reverse('tracker:application_detail', args=[self.application_id])

    @property
    def urgency(self):
        """done / overdue / soon / later — для підсвітки нагадувань."""
        if self.is_done:
            return 'done'
        days = (self.remind_at - timezone.localdate()).days
        if days < 0:
            return 'overdue'
        return 'soon' if days <= self.SOON_DAYS else 'later'
