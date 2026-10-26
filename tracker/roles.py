from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission

GUEST_GROUP = 'Guest'
USER_GROUP = 'User'
GUEST_USERNAME = 'guest'

ROLE_ANONYMOUS = 'anonymous'
ROLE_GUEST = 'guest'
ROLE_USER = 'user'

GUEST_VIEW_MODELS = ['studentprofile', 'profileskill', 'company', 'skill', 'vacancy', 'application', 'reminder']
FULL_ACCESS_MODELS = ['studentprofile', 'profileskill', 'application', 'reminder']
USER_VIEW_ONLY_MODELS = ['company', 'skill', 'vacancy']


def _permissions(codenames):
    return Permission.objects.filter(content_type__app_label='tracker', codename__in=codenames)


def ensure_roles():
    """Створює групи Guest і User та виставляє їм права (безпечно викликати повторно)."""
    guest_group, _ = Group.objects.get_or_create(name=GUEST_GROUP)
    user_group, _ = Group.objects.get_or_create(name=USER_GROUP)

    guest_codes = [f'view_{m}' for m in GUEST_VIEW_MODELS] + ['sync_vacancies']
    guest_group.permissions.set(_permissions(guest_codes))

    user_codes = [f'{action}_{m}' for m in FULL_ACCESS_MODELS for action in ('add', 'change', 'delete', 'view')]
    user_codes += [f'view_{m}' for m in USER_VIEW_ONLY_MODELS] + ['sync_vacancies', 'view_stats']
    user_group.permissions.set(_permissions(user_codes))
    return guest_group, user_group


def get_role(user):
    """Роль поточного відвідувача: anonymous, guest або user."""
    if not user.is_authenticated:
        return ROLE_ANONYMOUS
    if user.groups.filter(name=GUEST_GROUP).exists():
        return ROLE_GUEST
    return ROLE_USER


def ensure_guest_user(reset=False):
    """Повертає спільний акаунт гостя (без пароля). reset=True очищає його заявки."""
    from tracker.models import Application, StudentProfile

    guest_group, _ = ensure_roles()
    User = get_user_model()
    user, created = User.objects.get_or_create(username=GUEST_USERNAME, defaults={'first_name': 'Гість'})
    if created:
        user.set_unusable_password()
        user.save()
    user.groups.set([guest_group])
    if reset:
        Application.objects.filter(user=user).delete()
    profile = StudentProfile.get_profile(user)
    if profile.full_name or profile.skill_levels.exists():
        profile.skill_levels.all().delete()
        profile.full_name = ''
        profile.save()
    return user


def assign_default_role(sender, instance, created, raw=False, **kwargs):
    """Кожен новий звичайний користувач автоматично отримує роль User."""
    if raw or not created or instance.is_superuser or instance.username == GUEST_USERNAME:
        return
    _, user_group = ensure_roles()
    instance.groups.add(user_group)


def setup_roles(sender, using='default', **kwargs):
    """post_migrate: групи й права; наявні користувачі без групи стають User."""
    from django.db import connections

    if 'auth_user_groups' not in connections[using].introspection.table_names():
        return
    _, user_group = ensure_roles()
    User = get_user_model()
    orphans = User.objects.filter(groups__isnull=True, is_superuser=False).exclude(username=GUEST_USERNAME)
    for user in orphans:
        user.groups.add(user_group)
