import re

from django.core.exceptions import ValidationError
from django.utils import timezone

USERNAME_RE = re.compile(r'[A-Za-z0-9_]{3,30}')
NOTES_RE = re.compile(r'.{0,2000}', re.DOTALL)
REMINDER_TEXT_RE = re.compile(r'.{3,200}', re.DOTALL)
HAS_LETTER_OR_DIGIT_RE = re.compile(r'[^\W_]')
SKILL_RE = re.compile(r'[\w#+./ -]{1,50}')
WHITESPACE_RE = re.compile(r'\s+')


def normalize_spaces(value):
    """Стискає будь-які послідовності пробілів і переносів рядка в один пробіл."""
    return WHITESPACE_RE.sub(' ', value or '').strip()


def validate_username(value):
    """Імʼя користувача: 3-30 символів, лише латиниця, цифри та підкреслення."""
    if not USERNAME_RE.fullmatch(value or ''):
        raise ValidationError(
            'Імʼя користувача: від 3 до 30 символів, лише латиниця, цифри та підкреслення.', code='bad_username',
        )


def validate_notes(value):
    if not NOTES_RE.fullmatch(value or ''):
        raise ValidationError('Нотатки задовгі: не більше 2000 символів.', code='notes_too_long')


def validate_reminder_text(value):
    """Текст нагадування: 3-200 символів і хоча б одна літера або цифра."""
    if not REMINDER_TEXT_RE.fullmatch(value or '') or not HAS_LETTER_OR_DIGIT_RE.search(value):
        raise ValidationError(
            'Опишіть нагадування щонайменше трьома символами, серед яких є літера або цифра.', code='bad_reminder_text',
        )


def is_valid_skill(value):
    """Назва власної навички: літери, цифри та символи # + . / - (до 50 символів)."""
    return bool(SKILL_RE.fullmatch(value or ''))


def validate_not_future(value):
    """Дата події не може бути в майбутньому (наприклад, дата подачі заявки)."""
    if value and value > timezone.localdate():
        raise ValidationError('Дата не може бути в майбутньому.', code='future_date')
