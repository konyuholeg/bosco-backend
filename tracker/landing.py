from django.http import HttpResponseNotAllowed
from django.shortcuts import redirect, render

from tracker.services import start_background_sync


def home(request):
    """GET /: незалогінений бачить hero-сторінку (тим часом у фоні наповнюється каталог),
    залогінений одразу потрапляє у свій список вакансій."""
    if request.user.is_authenticated:
        return redirect('tracker:application_list')
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    start_background_sync()
    return render(request, 'landing.html')
