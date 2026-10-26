from tracker.roles import ROLE_GUEST, get_role


def role(request):
    current = get_role(request.user)
    return {'role': current, 'is_guest': current == ROLE_GUEST}
