from django import template

from tracker.models import STATUS_CHOICES

register = template.Library()
STATUS_LABELS = dict(STATUS_CHOICES)


@register.inclusion_tag('tags/status_badge.html')
def status_badge(status):
    """Кольоровий значок статусу заявки."""
    return {'status': status, 'label': STATUS_LABELS.get(status, status)}


@register.inclusion_tag('tags/skill_pills.html')
def skill_pills(vacancy, match=None):
    """
    Вимоги вакансії у вигляді позначок. З match (зареєстрований користувач) збіглі й відсутні
    навички підсвічуються; без нього всі позначки нейтральні.
    """
    return {
        'skills': [s.title for s in vacancy.skills.all()],
        'match': match,
        'level': vacancy.get_level_display() if vacancy.level else '',
        'languages': [s.title for s in vacancy.skills.all() if s.category == 'lang'],
    }


@register.inclusion_tag('tags/reminder_badge.html')
def reminder_badge(reminder):
    """Нагадування з підсвіткою: прострочене, найближче (до 3 днів), майбутнє, виконане."""
    return {'reminder': reminder}


@register.simple_tag(takes_context=True)
def query_string(context, **changes):
    """Поточний GET-запит із підміненими параметрами (для пагінації з фільтрами)."""
    params = context['request'].GET.copy()
    for key, value in changes.items():
        if value in (None, ''):
            params.pop(key, None)
        else:
            params[key] = value
    return params.urlencode()
