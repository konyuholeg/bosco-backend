from functools import wraps

from django.http import JsonResponse
from django.shortcuts import render


def permission_required_for(perm, methods=None, as_json=False):
    """Перевірка права на сервері; methods — для яких HTTP-методів (None = усі)."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            applies = methods is None or request.method in methods
            if applies and not request.user.has_perm(perm):
                if as_json:
                    return JsonResponse({'success': False, 'message': 'Недостатньо прав для цієї дії'}, status=403)
                return render(request, '403.html', status=403)
            return view(request, *args, **kwargs)
        return wrapper
    return decorator
