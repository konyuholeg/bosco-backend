import json
from collections import Counter
from datetime import datetime
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db import IntegrityError, transaction
from django.db.models import Case, Count, IntegerField, Q, When
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotAllowed, JsonResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from tracker.charts import build_status_chart
from tracker.forms import (
    ApplicationForm, CategorySortForm, LoginForm, RegisterForm, ReminderForm, ReminderUpdateForm,
)
from tracker.models import (
    SETTABLE_STATUSES, STATUS_CHOICES, Application, Company, ProfileSkill, Reminder, Skill, StudentProfile, Vacancy,
)
from tracker.permissions import permission_required_for
from tracker.roles import ROLE_GUEST, ensure_guest_user, get_role
from tracker.services import LEVELED_SKILLS, SKILL_GROUPS, SKILL_KEYWORDS, sync_all_categories
from tracker.validators import is_valid_skill

STATUS_COLORS = {
    'found': '#9ca3af', 'applied': '#3b82f6', 'offer': '#10b981', 'rejected': '#ef4444',
}


def can_match(user):
    """Збіг навичок доступний лише зареєстрованому користувачу (не гостю й не анонімному)."""
    return user.is_authenticated and get_role(user) != ROLE_GUEST


def _owned_skills(user):
    return StudentProfile.get_profile(user).skill_level_map() if can_match(user) else {}


def autoload_vacancies(request, user):
    """Паралельно завантажує всі категорії Jobicy; помилки категорій показує попередженням."""
    if not user.has_perm('tracker.sync_vacancies'):
        return
    _, _, failed = sync_all_categories(user)
    if failed:
        messages.warning(request, 'Не вдалося завантажити категорії: ' + ', '.join(failed) + '.')


class VacancyDetailView(DetailView):
    model = Vacancy
    template_name = 'vacancy_detail.html'
    queryset = Vacancy.objects.select_related('company').prefetch_related('skills')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['match'] = self.object.ai_match(_owned_skills(user)) if can_match(user) else None
        context['application'] = (
            Application.objects.filter(user=user, is_hidden=False, vacancy=self.object).first()
            if user.is_authenticated else None
        )
        return context


class CompanyListView(ListView):
    template_name = 'company_list.html'
    context_object_name = 'companies'
    paginate_by = 12
    queryset = Company.objects.annotate(n=Count('vacancies')).order_by('name')


class CompanyDetailView(DetailView):
    model = Company
    template_name = 'company_detail.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['vacancies'] = self.object.vacancies.prefetch_related('skills')
        return context


class SkillListView(ListView):
    template_name = 'skill_list.html'
    context_object_name = 'skills'
    paginate_by = 30
    queryset = Skill.objects.annotate(n=Count('vacancies')).order_by('category', 'title')


class SkillDetailView(DetailView):
    model = Skill
    template_name = 'skill_detail.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['vacancies'] = self.object.vacancies.select_related('company').prefetch_related('skills')
        return context


class OwnApplicationsMixin(LoginRequiredMixin, PermissionRequiredMixin):
    """Доступ лише автентифікованим із правом; у вибірці тільки власні заявки (чужі дають 404)."""

    def get_queryset(self):
        return (
            Application.objects.filter(user=self.request.user, is_hidden=False)
            .select_related('vacancy__company').prefetch_related('vacancy__skills', 'reminders')
        )


class ApplicationListView(OwnApplicationsMixin, ListView):
    permission_required = 'tracker.view_application'
    template_name = 'application_list.html'
    context_object_name = 'applications'
    paginate_by = 8

    def get_queryset(self):
        queryset = super().get_queryset()
        self.status = self.request.GET.get('status')
        if self.status in dict(STATUS_CHOICES):
            queryset = queryset.filter(status=self.status)
        else:
            self.status = None
        user = self.request.user
        self.gaps_mode = self.request.GET.get('gaps') == '1' and can_match(user)
        self.sort_form = CategorySortForm(self.request.GET)
        self.category = self.sort_form.cleaned_data['category'] if self.sort_form.is_valid() else ''
        self.top_gaps = []
        if self.gaps_mode:
            owned = _owned_skills(user)
            items = list(queryset)
            for item in items:
                item.match = item.ai_match(owned)
            self.top_gaps = Counter(m for a in items for m in a.match['missing']).most_common(8)
            items.sort(key=lambda a: (
                a.vacancy.category != self.category if self.category else 0,
                len(a.match['missing']), -a.match['score'],
            ))
            return items
        if self.category:
            first = Case(When(vacancy__category=self.category, then=0), default=1, output_field=IntegerField())
            return queryset.order_by(first, '-created_at', '-id')
        return queryset.order_by('-created_at', '-id')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        applications = list(context['applications'])
        if can_match(user) and not self.gaps_mode:
            owned = _owned_skills(user)
            for item in applications:
                item.match = item.ai_match(owned)
        counts = Application.objects.filter(user=user, is_hidden=False).aggregate(
            total=Count('id'),
            **{key: Count('id', filter=Q(status=key)) for key, _ in STATUS_CHOICES},
        )
        today = timezone.localdate()
        context.update({
            'applications': applications,
            'counts': counts,
            'tabs': [(key, label, counts[key]) for key, label in STATUS_CHOICES],
            'settable_statuses': SETTABLE_STATUSES,
            'current_status': self.status,
            'sort_form': self.sort_form,
            'gaps_mode': self.gaps_mode,
            'top_gaps': self.top_gaps,
            'upcoming': Reminder.objects.filter(
                application__user=user, application__is_hidden=False, is_done=False,
                remind_at__lte=today + timezone.timedelta(days=7),
            ).select_related('application__vacancy__company'),
        })
        return context


class ApplicationDetailView(OwnApplicationsMixin, DetailView):
    permission_required = 'tracker.view_application'
    template_name = 'application_detail.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        context['match'] = self.object.ai_match(_owned_skills(user)) if can_match(user) else None
        context['settable_statuses'] = SETTABLE_STATUSES
        return context


class ApplicationCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    """«Відстежувати»: створює заявку на вакансію з каталогу; власник призначається у form_valid()."""
    model = Application
    form_class = ApplicationForm
    template_name = 'form.html'
    permission_required = 'tracker.add_application'

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)
        self.vacancy = get_object_or_404(Vacancy.objects.select_related('company'), pk=kwargs['vacancy_pk'])

    def _existing(self):
        return Application.objects.filter(user=self.request.user, vacancy=self.vacancy).first()

    def _redirect_existing(self, existing):
        if existing.is_hidden:
            existing.is_hidden = False
            existing.save(update_fields=['is_hidden', 'updated_at'])
            messages.success(self.request, 'Вакансію повернено до ваших заявок.')
        else:
            messages.info(self.request, 'Ви вже відстежуєте цю вакансію.')
        return redirect(existing)

    def get(self, request, *args, **kwargs):
        existing = self._existing()
        return self._redirect_existing(existing) if existing else super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        existing = self._existing()
        return self._redirect_existing(existing) if existing else super().post(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.user = self.request.user
        form.instance.vacancy = self.vacancy
        try:
            with transaction.atomic():
                response = super().form_valid(form)
        except IntegrityError:
            return self._redirect_existing(self._existing())
        messages.success(self.request, 'Вакансію додано до ваших заявок.')
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'title': f'Відстежувати: {self.vacancy}',
            'cancel_url': self.vacancy.get_absolute_url(),
            'submit_label': 'Додати до заявок',
        })
        return context


class ApplicationUpdateView(OwnApplicationsMixin, UpdateView):
    form_class = ApplicationForm
    template_name = 'form.html'
    permission_required = 'tracker.change_application'

    def form_valid(self, form):
        messages.success(self.request, 'Зміни збережено!')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'title': f'Редагувати: {self.object.vacancy}',
            'cancel_url': self.object.get_absolute_url(),
            'submit_label': 'Зберегти',
        })
        return context


class ApplicationDeleteView(OwnApplicationsMixin, DeleteView):
    template_name = 'confirm_delete.html'
    permission_required = 'tracker.delete_application'
    success_url = reverse_lazy('tracker:application_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'Заявку видалено.')
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'title': 'Видалити заявку?',
            'what': str(self.object.vacancy),
            'cancel_url': self.object.get_absolute_url(),
        })
        return context


@login_required
@permission_required_for('tracker.change_application')
def change_status(request, pk):
    """POST: швидка зміна статусу заявки. «Знайдено» та невідомі статуси сервер відхиляє."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    application = get_object_or_404(Application, pk=pk, user=request.user, is_hidden=False)
    new_status = request.POST.get('status')
    if new_status not in dict(SETTABLE_STATUSES):
        return HttpResponseBadRequest('Недопустимий статус')
    application.status = new_status
    application.save(update_fields=['status', 'updated_at'])
    next_url = request.POST.get('next', '')
    if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
        return redirect(next_url)
    return redirect('tracker:application_list')


@login_required
@permission_required_for('tracker.change_application')
def dismiss_application(request, pk):
    """POST: «Нецікаво» — заявка зникає зі списку й не повертається при автозавантаженні."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    application = get_object_or_404(Application, pk=pk, user=request.user, is_hidden=False)
    application.is_hidden = True
    application.save(update_fields=['is_hidden', 'updated_at'])
    messages.info(request, 'Вакансію приховано зі списку.')
    return redirect('tracker:application_list')


class ReminderCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model = Reminder
    form_class = ReminderForm
    template_name = 'form.html'
    permission_required = 'tracker.add_reminder'

    def get_application(self):
        if not hasattr(self, '_application'):
            self._application = get_object_or_404(
                Application.objects.select_related('vacancy__company'),
                pk=self.kwargs['application_pk'], user=self.request.user,
            )
        return self._application

    def get(self, request, *args, **kwargs):
        self.get_application()
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        form.instance.application = self.get_application()
        messages.success(self.request, 'Нагадування додано.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        application = self.get_application()
        context.update({
            'title': f'Нове нагадування: {application.vacancy}',
            'cancel_url': application.get_absolute_url(),
            'submit_label': 'Додати',
        })
        return context


class OwnRemindersMixin(LoginRequiredMixin, PermissionRequiredMixin):
    def get_queryset(self):
        return Reminder.objects.filter(application__user=self.request.user).select_related('application__vacancy')


class ReminderListView(OwnRemindersMixin, ListView):
    """Усі нагадування користувача з вкладками «Активні / Прострочені / Виконані»."""
    permission_required = 'tracker.view_reminder'
    template_name = 'reminder_list.html'
    context_object_name = 'reminders'
    paginate_by = 10

    def get_queryset(self):
        queryset = (
            super().get_queryset().select_related('application__vacancy__company')
            .filter(application__is_hidden=False)
        )
        self.state = self.request.GET.get('state')
        if self.state == 'active':
            queryset = queryset.filter(is_done=False)
        elif self.state == 'overdue':
            queryset = queryset.filter(is_done=False, remind_at__lt=timezone.localdate())
        elif self.state == 'done':
            queryset = queryset.filter(is_done=True)
        else:
            self.state = ''
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        counts = Reminder.objects.filter(application__user=self.request.user, application__is_hidden=False).aggregate(
            total=Count('id'),
            active=Count('id', filter=Q(is_done=False)),
            overdue=Count('id', filter=Q(is_done=False, remind_at__lt=today)),
            done=Count('id', filter=Q(is_done=True)),
        )
        context.update({
            'counts': counts,
            'tabs': [
                ('active', 'Активні', counts['active']),
                ('overdue', 'Прострочені', counts['overdue']),
                ('done', 'Виконані', counts['done']),
            ],
            'current_state': self.state,
        })
        return context


class ReminderDetailView(OwnRemindersMixin, DetailView):
    """Сторінка одного нагадування; чуже нагадування дає 404 (queryset фільтрується за власником)."""
    permission_required = 'tracker.view_reminder'
    template_name = 'reminder_detail.html'


class ReminderUpdateView(OwnRemindersMixin, UpdateView):
    form_class = ReminderUpdateForm
    template_name = 'form.html'
    permission_required = 'tracker.change_reminder'

    def form_valid(self, form):
        messages.success(self.request, 'Нагадування оновлено.')
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'title': 'Редагувати нагадування',
            'cancel_url': self.object.get_absolute_url(),
            'submit_label': 'Зберегти',
        })
        return context


class ReminderDeleteView(OwnRemindersMixin, DeleteView):
    template_name = 'confirm_delete.html'
    permission_required = 'tracker.delete_reminder'

    def get_success_url(self):
        return self.object.get_absolute_url()

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'Нагадування видалено.')
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'title': 'Видалити нагадування?',
            'what': str(self.object),
            'cancel_url': self.object.get_absolute_url(),
        })
        return context


@login_required
@permission_required_for('tracker.change_reminder')
def reminder_toggle(request, pk):
    """POST: позначити нагадування виконаним / повернути в активні."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    reminder = get_object_or_404(Reminder, pk=pk, application__user=request.user)
    reminder.is_done = not reminder.is_done
    reminder.save(update_fields=['is_done'])
    return redirect(reminder.get_absolute_url())


def _request_data(request):
    """Тіло PUT: JSON або форма."""
    if 'application/json' in (request.content_type or ''):
        return json.loads(request.body.decode('utf-8')) if request.body else {}
    return QueryDict(request.body)


def _json_response(request, payload, status=200):
    """JsonResponse із власним заголовком: демонструє status_code та __setitem__."""
    response = JsonResponse(payload, status=status, json_dumps_params={'ensure_ascii': False})
    response['X-Request-Method'] = request.method
    return response


def _vacancy_to_dict(vacancy):
    return {
        'id': vacancy.id,
        'company': vacancy.company.name,
        'position': vacancy.position,
        'location': vacancy.location,
        'salary': vacancy.salary,
        'skills': [s.title for s in vacancy.skills.all()],
        'url': vacancy.url,
        'detail_url': vacancy.get_absolute_url(),
    }


def _application_to_dict(application):
    return {
        'id': application.id,
        'vacancy': str(application.vacancy),
        'status': application.status,
        'status_display': application.get_status_display(),
        'notes': application.notes,
    }


def vacancies_collection(request):
    """GET /api/vacancies/?q=&skill= — публічний список каталогу (не більше 50 записів)."""
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    queryset = Vacancy.objects.select_related('company').prefetch_related('skills')
    query = (request.GET.get('q') or '').strip()
    skill = (request.GET.get('skill') or '').strip().lower()
    if query:
        queryset = queryset.filter(Q(position__icontains=query) | Q(company__name__icontains=query))
    if skill:
        queryset = queryset.filter(skills__name=skill)
    results = [_vacancy_to_dict(v) for v in queryset.distinct()[:50]]
    return _json_response(request, {'method': request.method, 'path': request.path, 'count': len(results), 'results': results})


@login_required
@permission_required_for('tracker.change_application', methods=['PUT'], as_json=True)
@permission_required_for('tracker.delete_application', methods=['DELETE'], as_json=True)
def application_resource(request, pk):
    """/api/applications/<id>/ — GET читає, PUT змінює статус і нотатки, DELETE видаляє власну заявку."""
    application = get_object_or_404(
        Application.objects.select_related('vacancy__company'), pk=pk, user=request.user, is_hidden=False,
    )
    if request.method == 'GET':
        return _json_response(request, {'application': _application_to_dict(application)})
    if request.method == 'PUT':
        try:
            data = _request_data(request)
        except ValueError:
            return _json_response(request, {'success': False, 'message': 'Некоректний JSON'}, status=400)
        if 'status' in data:
            if data['status'] not in dict(SETTABLE_STATUSES):
                return _json_response(request, {'success': False, 'message': 'Недопустимий статус'}, status=400)
            application.status = data['status']
        if 'notes' in data:
            application.notes = str(data['notes'])[:2000]
        application.save()
        return _json_response(request, {'success': True, 'application': _application_to_dict(application)})
    if request.method == 'DELETE':
        application.delete()
        return _json_response(request, {'success': True, 'message': 'Заявку видалено'})
    return HttpResponseNotAllowed(['GET', 'PUT', 'DELETE'])


def _filtered_items(request):
    """Заявки користувача за періодом з request.GET (period, date_from, date_to)."""
    period = request.GET.get('period', 'all')
    date_from_str = request.GET.get('date_from', '').strip()
    date_to_str = request.GET.get('date_to', '').strip()

    items = Application.objects.filter(user=request.user, is_hidden=False)
    if period == 'month':
        items = items.filter(created_at__gte=timezone.now() - timezone.timedelta(days=30))
    elif period == 'custom' or (date_from_str or date_to_str):
        period = 'custom'
        for raw, lookup in ((date_from_str, 'created_at__date__gte'), (date_to_str, 'created_at__date__lte')):
            if raw:
                try:
                    items = items.filter(**{lookup: datetime.strptime(raw, '%Y-%m-%d').date()})
                except ValueError:
                    pass
    return items, period, date_from_str, date_to_str


def _pipeline(items):
    """Воронка відбору: один запит з annotate() замість окремого count() на кожен статус."""
    counted = dict(items.order_by().values_list('status').annotate(n=Count('id')))
    return [(key, label, counted.get(key, 0), STATUS_COLORS[key]) for key, label in STATUS_CHOICES]


@login_required
@permission_required_for('tracker.view_stats')
def stats(request):
    """GET: статистика та воронка відбору з фільтром за періодом та діаграмою."""
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])

    items, period, date_from_str, date_to_str = _filtered_items(request)
    pipeline = _pipeline(items)
    counts = {key: n for key, _, n, _ in pipeline}
    offers, rejected = counts['offer'], counts['rejected']
    chart_type = 'bar' if request.GET.get('chart') == 'bar' else 'pie'
    filter_params = {k: v for k, v in (('period', period), ('date_from', date_from_str), ('date_to', date_to_str)) if v}

    return render(request, 'stats.html', {
        'total': sum(counts.values()),
        'pipeline': pipeline,
        'offers': offers,
        'rejected': rejected,
        'period': period,
        'date_from': date_from_str,
        'date_to': date_to_str,
        'chart_type': chart_type,
        'chart_src': '?'.join([reverse('tracker:stats_chart'), urlencode({**filter_params, 'type': chart_type})]),
        'filter_qs': urlencode(filter_params),
    })


@login_required
@permission_required_for('tracker.view_stats')
def stats_chart(request):
    """GET: діаграма статусів, побудована Matplotlib, у вигляді PNG-зображення."""
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])
    items, _, _, _ = _filtered_items(request)
    pipeline = _pipeline(items)
    kind = 'bar' if request.GET.get('type') == 'bar' else 'pie'
    png = build_status_chart([p[1] for p in pipeline], [p[2] for p in pipeline], [p[3] for p in pipeline], kind)
    response = HttpResponse(png, content_type='image/png')
    response.status_code = 200
    response['Cache-Control'] = 'no-store'
    return response


def _valid_level(skill_name, level):
    """Повертає рівень, якщо він належить шкалі цієї навички, інакше порожній рядок."""
    if skill_name not in LEVELED_SKILLS:
        return ''
    return level if level in dict(ProfileSkill.choices_for(skill_name)) else ''


def _level_choices(skill_name):
    return ProfileSkill.choices_for(skill_name) if skill_name in LEVELED_SKILLS else []


def _skill_labels():
    return {value: label for _, items in SKILL_GROUPS for value, label in items}


def _profile_context(profile):
    levels = {item.skill.name: item for item in profile.skill_levels.select_related('skill')}
    selected = set(levels)
    saved = {name: _valid_level(name, item.level) for name, item in levels.items()}
    groups = [
        (
            title,
            [
                (value, label, value in selected, saved.get(value, ''), _level_choices(value))
                for value, label in items
            ],
        )
        for title, items in SKILL_GROUPS
    ]
    known = set(SKILL_KEYWORDS)
    preview = [
        (levels[name].skill.title, dict(_level_choices(name)).get(saved[name], ''))
        for name in sorted(selected)
    ]
    other = ', '.join(sorted(name for name in selected if name not in known))
    return {'profile': profile, 'skill_groups': groups, 'other_skills': other, 'preview': preview}


def _save_skills(profile, checked, other, post):
    """Зберігає навички профілю з рівнями; зняті відмітки видаляє."""
    labels = _skill_labels()
    names = list(dict.fromkeys(checked + other))
    profile.skill_levels.exclude(skill__name__in=names).delete()
    for name in names:
        skill, _ = Skill.objects.get_or_create(
            name=name, defaults={'title': labels.get(name, name)[:60], 'category': 'other'},
        )
        level = _valid_level(name, post.get(f'level_{name}'))
        ProfileSkill.objects.update_or_create(profile=profile, skill=skill, defaults={'level': level})


@login_required
@permission_required_for('tracker.change_studentprofile', methods=['POST'])
def profile_view(request):
    """GET — профіль із чек-листом технологій; POST — збереження навичок і рівнів.

    Гість має порожній профіль: замість чек-листа йому показується пояснення, що потрібна реєстрація.
    """
    if get_role(request.user) == ROLE_GUEST:
        if request.method != 'GET':
            return HttpResponseNotAllowed(['GET'])
        return render(request, 'profile_guest.html')
    profile = StudentProfile.get_profile(request.user)
    if request.method == 'POST':
        checked = list(dict.fromkeys(v for v in request.POST.getlist('skill') if v in SKILL_KEYWORDS))
        other = [
            x.strip().lower() for x in (request.POST.get('other_skills') or '').split(',')
            if is_valid_skill(x.strip())
        ][:20]
        with transaction.atomic():
            _save_skills(profile, checked, other, request.POST)
        messages.success(request, 'Навички студента оновлено!')
        return redirect('tracker:profile')
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET', 'POST'])
    return render(request, 'profile.html', _profile_context(profile))


def register_view(request):
    """GET — форма реєстрації; POST — створення користувача та автоматичний вхід."""
    if request.user.is_authenticated and get_role(request.user) != ROLE_GUEST:
        return redirect('tracker:index')
    if request.method == 'GET':
        form = RegisterForm()
    elif request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            autoload_vacancies(request, user)
            messages.success(request, 'Реєстрацію завершено. Вітаємо!')
            return redirect('tracker:index')
    else:
        return HttpResponseNotAllowed(['GET', 'POST'])
    return render(request, 'register.html', {'form': form})


def login_view(request):
    """GET — форма входу; POST — перевірка логіна й пароля та створення сесії."""
    if request.user.is_authenticated and get_role(request.user) != ROLE_GUEST:
        return redirect('tracker:index')
    next_url = request.POST.get('next') or request.GET.get('next') or ''
    if request.method == 'GET':
        form = LoginForm()
    elif request.method == 'POST':
        form = LoginForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            autoload_vacancies(request, user)
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)
            return redirect('tracker:index')
    else:
        return HttpResponseNotAllowed(['GET', 'POST'])
    return render(request, 'login.html', {'form': form, 'next': next_url})


def guest_login(request):
    """POST: вхід у спільний акаунт гостя (лише перегляд каталогу, без пароля)."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    if request.user.is_authenticated:
        return redirect('tracker:index')
    guest = ensure_guest_user(reset=True)
    login(request, guest, backend='django.contrib.auth.backends.ModelBackend')
    autoload_vacancies(request, guest)
    messages.info(request, 'Ви увійшли як гість.')
    return redirect('tracker:index')


def logout_view(request):
    """POST: завершення сесії користувача."""
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    logout(request)
    return redirect('tracker:login')
