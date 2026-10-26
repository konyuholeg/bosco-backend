import json
from datetime import date, timedelta
from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.management import call_command
from django.db import IntegrityError
from django.db.models import ProtectedError
from django.db import connection
from django.test import Client, RequestFactory, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.template import Context, Template
from django.urls import reverse
from django.utils import timezone

from tracker import services
from tracker.services import JOB_CATEGORIES, sync_all_categories, sync_jobicy
from tracker.models import Application, Company, ProfileSkill, Reminder, Skill, StudentProfile, Vacancy
from tracker.roles import ensure_guest_user, ensure_roles, get_role, setup_roles

User = get_user_model()
PASSWORD = 'pass12345'

_autoload_patcher = None


def setUpModule():
    """Автозавантаження вакансій при вході підміняємо, щоб тести не звертались до мережі."""
    global _autoload_patcher
    _autoload_patcher = patch('tracker.views.sync_all_categories', return_value=(0, 0, []))
    _autoload_patcher.start()


def tearDownModule():
    _autoload_patcher.stop()


def make_vacancy(company='Acme', position='Dev', skills=(), **extra):
    company_obj, _ = Company.objects.get_or_create(name=company)
    vacancy = Vacancy.objects.create(company=company_obj, position=position, **extra)
    vacancy.skills.set(Skill.objects.filter(name__in=skills))
    return vacancy


def make_user(name='tester', skills=()):
    user = User.objects.create_user(name, password=PASSWORD)
    profile = StudentProfile.get_profile(user)
    for skill in Skill.objects.filter(name__in=skills):
        ProfileSkill.objects.create(profile=profile, skill=skill)
    return user


class MatchTests(TestCase):
    def setUp(self):
        self.user = make_user('m', skills=['python', 'sql', 'rest'])
        self.owned = StudentProfile.get_profile(self.user).skill_names()

    def test_full_match(self):
        match = make_vacancy(skills=['python', 'sql', 'rest']).ai_match(self.owned)
        self.assertEqual(match['score'], 100)
        self.assertEqual(match['missing'], [])
        self.assertIn('Python', match['matched'])

    def test_partial_match(self):
        match = make_vacancy(skills=['python', 'sql', 'docker', 'aws']).ai_match(self.owned)
        self.assertEqual(match['score'], 50)
        self.assertCountEqual(match['missing'], ['Docker', 'AWS'])

    def test_java_does_not_match_javascript(self):
        match = make_vacancy(skills=['java']).ai_match({'javascript'})
        self.assertEqual(match['score'], 0)

    def test_no_requirements_is_full_match(self):
        self.assertEqual(make_vacancy().ai_match(self.owned)['score'], 100)


class LevelMatchTests(TestCase):
    def setUp(self):
        self.user = make_user('lvl')
        self.profile = StudentProfile.get_profile(self.user)
        for name, level in (('python', 'junior'), ('java', 'middle'), ('english', 'a2'), ('sql', 'senior')):
            skill = Skill.objects.get(name=name)
            ProfileSkill.objects.create(profile=self.profile, skill=skill, level=level)

    def test_skill_level_map(self):
        self.assertEqual(self.profile.skill_level_map(), {'python': 'junior', 'java': 'middle', 'english': 'a2', 'sql': ''})

    def test_lower_level_is_below_and_gives_half_score(self):
        vacancy = make_vacancy(skills=['python', 'java', 'docker'], level='middle')
        match = vacancy.ai_match(self.profile.skill_level_map())
        self.assertEqual(match['matched'], ['Java'])
        self.assertEqual(match['below'], ['Python'])
        self.assertEqual(match['missing'], ['Docker'])
        self.assertEqual(match['score'], 50)

    def test_equal_or_higher_level_is_matched(self):
        vacancy = make_vacancy(skills=['python', 'java'], level='junior')
        match = vacancy.ai_match(self.profile.skill_level_map())
        self.assertEqual((match['below'], match['score']), ([], 100))

    def test_vacancy_without_level_ignores_student_level(self):
        match = make_vacancy(skills=['python', 'java']).ai_match(self.profile.skill_level_map())
        self.assertEqual((match['below'], match['score']), ([], 100))

    def test_levels_outside_languages_and_cefr_are_not_compared(self):
        vacancy = make_vacancy(skills=['sql', 'english'], level='senior')
        match = vacancy.ai_match(self.profile.skill_level_map())
        self.assertEqual((match['below'], match['score']), ([], 100))

    def test_set_of_names_still_supported(self):
        match = make_vacancy(skills=['python'], level='senior').ai_match({'python'})
        self.assertEqual((match['below'], match['score']), ([], 100))

    def test_jobicy_level_mapping_and_save(self):
        from tracker.services import level_from_jobicy, save_jobs
        cases = {'Senior': 'senior', 'Director': 'senior', 'Midweight': 'middle',
                 'Entry-Level, Junior': 'junior', 'Any': '', None: ''}
        for raw, expected in cases.items():
            self.assertEqual(level_from_jobicy(raw), expected, raw)
        save_jobs([{'id': 901, 'jobTitle': 'Dev', 'companyName': 'Acme', 'jobLevel': 'Midweight'}])
        self.assertEqual(Vacancy.objects.get(external_id='901').level, 'middle')

    def test_pills_show_required_level_text(self):
        vacancy = make_vacancy(skills=['python', 'java'], level='middle')
        html = self.render_pills(vacancy)
        self.assertIn('Необхідний рівень (Java, Python): Middle', html)
        self.assertNotIn('Рівень: Middle', html)
        self.assertNotIn('level-note', html)
        self.assertNotIn('pill-below', html)

    def test_required_level_without_languages_and_without_level(self):
        plain = make_vacancy(skills=['sql'], level='senior')
        self.assertIn('Необхідний рівень: Senior', self.render_pills(plain))
        self.assertNotIn('Необхідний рівень', self.render_pills(make_vacancy(skills=['python'])))

    def render_pills(self, vacancy):
        from django.template import Context, Template
        match = vacancy.ai_match(self.profile.skill_level_map())
        return Template('{% load tracker_tags %}{% skill_pills vacancy match %}').render(Context({'vacancy': vacancy, 'match': match}))


class VacancyPagesTests(TestCase):
    def setUp(self):
        self.a = make_vacancy('Alpha', 'Python Intern', ['python', 'sql'], salary='300 USD', salary_max=300, is_remote=True)
        self.b = make_vacancy('Beta', 'QA Trainee', ['qa'], salary='100 USD', salary_max=100)
        self.c = make_vacancy('Gamma', 'Java Dev', ['java'])

    def test_vacancy_list_route_is_removed(self):
        from django.urls import NoReverseMatch
        with self.assertRaises(NoReverseMatch):
            reverse('tracker:vacancy_list')
        self.assertEqual(self.client.get('/vacancies/').status_code, 404)

    def test_application_list_paginates(self):
        user = make_user('pager')
        self.client.force_login(user)
        for i in range(10):
            Application.objects.create(user=user, vacancy=make_vacancy('Co', f'Job {i}'))
        url = reverse('tracker:application_list')
        first = self.client.get(url)
        self.assertEqual(len(first.context['applications']), 8)
        self.assertTrue(first.context['is_paginated'])
        self.assertEqual(len(self.client.get(url, {'page': 2}).context['applications']), 2)

    def test_detail_shows_match_and_tracking_state(self):
        user = make_user('d', skills=['python'])
        self.client.force_login(user)
        res = self.client.get(self.a.get_absolute_url())
        self.assertContains(res, 'Збіг навичок: 50%')
        self.assertNotContains(res, reverse('tracker:application_add', args=[self.a.pk]))
        Application.objects.create(user=user, vacancy=self.a)
        self.assertContains(self.client.get(self.a.get_absolute_url()), 'Моя заявка')

    def test_company_and_skill_pages(self):
        self.assertContains(self.client.get(reverse('tracker:company_list')), 'Alpha')
        self.assertContains(self.client.get(self.a.company.get_absolute_url()), 'Python Intern')
        self.assertEqual(self.client.get(reverse('tracker:skill_list')).status_code, 200)
        python = Skill.objects.get(name='python')
        self.assertContains(self.client.get(python.get_absolute_url()), 'Python Intern')

    def test_missing_vacancy_is_404(self):
        self.assertEqual(self.client.get(reverse('tracker:vacancy_detail', args=[9999])).status_code, 404)


def jobicy_response(*jobs):
    response = Mock(status_code=200)
    response.raise_for_status = Mock()
    response.json.return_value = {'jobs': list(jobs)}
    return response


JOB = {
    'id': 101, 'jobTitle': 'Python Internship', 'companyName': 'Acme', 'url': 'https://jobicy.com/jobs/101',
    'jobGeo': 'Europe', 'jobDescription': '<p>We need Python, SQL and REST skills</p>',
    'salaryMin': 1000, 'salaryMax': 2000, 'salaryCurrency': 'USD', 'salaryPeriod': 'month',
}


class SyncTests(TestCase):
    def test_sync_creates_catalog_entries_and_tracks_for_user(self):
        user = make_user('s')
        with patch('tracker.services.requests.get', return_value=jobicy_response(JOB)) as get_mock:
            created, updated = sync_jobicy('Python', user=user)
        self.assertEqual((created, updated), (1, 0))
        self.assertEqual(get_mock.call_args.kwargs['params']['tag'], 'Python')
        vacancy = Vacancy.objects.get(external_id='101')
        self.assertEqual(vacancy.company.name, 'Acme')
        self.assertEqual((vacancy.source, vacancy.salary_min, vacancy.salary_max), ('jobicy', 1000, 2000))
        self.assertTrue(vacancy.is_remote)
        self.assertCountEqual(vacancy.skills.values_list('name', flat=True), ['python', 'sql', 'rest'])
        self.assertEqual(vacancy.raw_json['jobTitle'], 'Python Internship')
        application = Application.objects.get(user=user, vacancy=vacancy)
        self.assertEqual(application.status, 'found')

    def test_sync_without_user_only_fills_catalog(self):
        with patch('tracker.services.requests.get', return_value=jobicy_response(JOB)):
            sync_jobicy('Python')
        self.assertEqual((Vacancy.objects.count(), Application.objects.count()), (1, 0))

    def test_sync_has_no_duplicates_and_keeps_status(self):
        user = make_user('s')
        with patch('tracker.services.requests.get', return_value=jobicy_response(JOB)):
            sync_jobicy('Python', user=user)
            Application.objects.filter(user=user).update(status='applied')
            self.assertEqual(sync_jobicy('Python', user=user), (0, 1))
        self.assertEqual(Vacancy.objects.filter(external_id='101').count(), 1)
        self.assertEqual(Application.objects.get().status, 'applied')

    def test_same_vacancy_is_shared_between_users(self):
        users = [make_user('u1'), make_user('u2')]
        with patch('tracker.services.requests.get', return_value=jobicy_response(JOB)):
            for user in users:
                sync_jobicy('Python', user=user)
        self.assertEqual(Vacancy.objects.count(), 1)
        self.assertEqual(Application.objects.count(), 2)

    def test_dismissed_application_is_not_restored_by_sync(self):
        user = make_user('s')
        with patch('tracker.services.requests.get', return_value=jobicy_response(JOB)):
            sync_jobicy('Python', user=user)
            Application.objects.filter(user=user).update(is_hidden=True)
            sync_jobicy('Python', user=user)
        self.assertEqual(Application.objects.count(), 1)
        self.assertTrue(Application.objects.get().is_hidden)

    def test_sync_api_error(self):
        with patch('tracker.services.requests.get', side_effect=requests.ConnectionError()):
            with self.assertRaises(requests.ConnectionError):
                sync_jobicy('Java')

    def test_sync_url_is_removed(self):
        self.assertEqual(self.client.post('/sync/').status_code, 404)

    def test_sync_command(self):
        user = make_user('cmd')
        with patch('tracker.services.requests.get', return_value=jobicy_response(JOB)):
            call_command('sync_jobs', '--tag', 'Python', '--username', 'cmd', stdout=Mock())
        self.assertEqual((Vacancy.objects.count(), Application.objects.filter(user=user).count()), (1, 1))

    def test_sync_command_reports_total_failure(self):
        from django.core.management.base import CommandError
        with patch('tracker.services.requests.get', side_effect=requests.ConnectionError()):
            with self.assertRaises(CommandError):
                call_command('sync_jobs', '--tag', 'Python')

    def test_sync_command_unknown_user(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('sync_jobs', '--username', 'nobody')

    def test_background_sync_is_disabled_in_tests_by_default(self):
        self.assertFalse(services.start_background_sync())

    @override_settings(CATALOG_AUTO_SYNC=True)
    def test_background_sync_runs_once_per_interval(self):
        cache.clear()
        with patch('tracker.services.threading.Thread') as thread:
            self.assertTrue(services.start_background_sync())
            self.assertFalse(services.start_background_sync())
        thread.return_value.start.assert_called_once()
        cache.clear()

    @override_settings(CATALOG_AUTO_SYNC=True)
    def test_landing_starts_background_sync_for_anonymous_only(self):
        cache.clear()
        with patch('tracker.landing.start_background_sync') as start:
            self.client.get(reverse('tracker:index'))
            start.assert_called_once()
            self.client.force_login(make_user('x'))
            self.client.get(reverse('tracker:index'))
            start.assert_called_once()
        cache.clear()

    @override_settings(CATALOG_AUTO_SYNC=True)
    def test_background_failure_allows_retry_later(self):
        cache.clear()
        with patch('tracker.services.sync_all_categories', return_value=(0, 0, ['Java'])), \
                patch('tracker.services.connections'):
            services._run_background_sync()
        self.assertTrue(cache.get(services.SYNC_LOCK_KEY))
        cache.clear()


def numbered_response(counter):
    return lambda *args, **kwargs: jobicy_response({'id': next(counter), 'jobTitle': 'Python Dev', 'companyName': 'Acme'})


class AutoloadTests(TestCase):
    """Автозавантаження всіх категорій Jobicy при вході, реєстрації та вході гостем."""

    def test_sync_all_categories_requests_every_category(self):
        user = make_user('loader')
        counter = iter(range(1, 100))
        with patch('tracker.services.requests.get', side_effect=numbered_response(counter)) as get:
            created, updated, failed = sync_all_categories(user)
        self.assertEqual(get.call_count, len(JOB_CATEGORIES))
        self.assertEqual(len(JOB_CATEGORIES), 9)
        self.assertEqual({c.kwargs['params']['tag'] for c in get.call_args_list}, {t for t, _ in JOB_CATEGORIES})
        self.assertEqual((created, updated, failed), (9, 0, []))
        self.assertEqual(Application.objects.filter(user=user, status='found').count(), 9)

    def test_failed_category_does_not_block_others(self):
        user = make_user('loader')
        counter = iter(range(1, 100))

        def fake_get(url, params=None, **kwargs):
            if params['tag'] == 'Java':
                raise requests.ConnectionError()
            return numbered_response(counter)()

        with patch('tracker.services.requests.get', side_effect=fake_get):
            created, updated, failed = sync_all_categories(user)
        self.assertEqual((failed, created), (['Java'], 8))
        self.assertEqual(Application.objects.filter(user=user).count(), 8)

    def test_repeat_load_keeps_status_and_no_duplicates(self):
        user = make_user('loader')
        with patch('tracker.services.requests.get', side_effect=lambda *a, **k: jobicy_response(JOB)):
            sync_all_categories(user)
            Application.objects.filter(user=user).update(status='applied')
            created, updated, _ = sync_all_categories(user)
        self.assertEqual(Application.objects.filter(user=user).count(), 1)
        self.assertEqual(Application.objects.get(user=user).status, 'applied')
        self.assertEqual(created, 0)

    def test_login_register_and_guest_trigger_autoload(self):
        User.objects.create_user('ann', password=PASSWORD)
        with patch('tracker.views.sync_all_categories', return_value=(0, 0, [])) as load:
            self.client.post(reverse('tracker:login'), {'username': 'ann', 'password': PASSWORD})
            self.assertEqual(load.call_count, 1)
            self.client.post(reverse('tracker:logout'))
            self.client.post(reverse('tracker:register'), {
                'username': 'newbie', 'password1': 'Str0ng-pass-77', 'password2': 'Str0ng-pass-77',
            })
            self.assertEqual(load.call_count, 2)
            self.assertEqual(load.call_args.args[0].username, 'newbie')
            self.client.post(reverse('tracker:logout'))
            self.client.post(reverse('tracker:guest_login'))
            self.assertEqual(load.call_count, 3)
            self.assertEqual(load.call_args.args[0].username, 'guest')

    def test_wrong_password_does_not_autoload(self):
        User.objects.create_user('ann', password=PASSWORD)
        with patch('tracker.views.sync_all_categories') as load:
            self.client.post(reverse('tracker:login'), {'username': 'ann', 'password': 'wrong'})
        load.assert_not_called()

    def test_failed_categories_shown_as_warning(self):
        User.objects.create_user('ann', password=PASSWORD)
        with patch('tracker.views.sync_all_categories', return_value=(3, 0, ['Java', 'PHP'])):
            res = self.client.post(reverse('tracker:login'), {'username': 'ann', 'password': PASSWORD}, follow=True)
        self.assertContains(res, 'Не вдалося завантажити категорії: Java, PHP.')

    def test_all_categories_failing_still_logs_in(self):
        User.objects.create_user('ann', password=PASSWORD)
        with patch('tracker.views.sync_all_categories', wraps=sync_all_categories), \
             patch('tracker.services.requests.get', side_effect=requests.Timeout()):
            res = self.client.post(reverse('tracker:login'), {'username': 'ann', 'password': PASSWORD}, follow=True)
        self.assertContains(res, 'Не вдалося завантажити категорії')
        self.assertTrue(res.context['user'].is_authenticated)

    def test_autoloaded_vacancies_appear_in_user_list(self):
        User.objects.create_user('ann', password=PASSWORD)
        with patch('tracker.views.sync_all_categories', side_effect=sync_all_categories), \
             patch('tracker.services.requests.get', side_effect=lambda *a, **k: jobicy_response(JOB)):
            self.client.post(reverse('tracker:login'), {'username': 'ann', 'password': PASSWORD})
        res = self.client.get(reverse('tracker:application_list'))
        self.assertContains(res, 'Python Internship')
        self.assertEqual(res.context['counts']['found'], 1)


class ApplicationCrudTests(TestCase):
    def setUp(self):
        self.user = make_user('owner', skills=['python', 'sql'])
        self.vacancy = make_vacancy('Acme', 'Python Intern', ['python', 'sql', 'docker'])
        self.client.force_login(self.user)

    def application(self, **extra):
        return Application.objects.create(user=self.user, vacancy=self.vacancy, **extra)

    def test_create_assigns_owner_and_vacancy_on_server(self):
        url = reverse('tracker:application_add', args=[self.vacancy.pk])
        form_page = self.client.get(url)
        self.assertNotContains(form_page, 'name="user"')
        self.assertNotContains(form_page, 'name="vacancy"')
        other = User.objects.create_user('other', password=PASSWORD)
        res = self.client.post(url, {'status': 'found', 'notes': 'Цікаво', 'user': other.pk, 'vacancy': 999})
        application = Application.objects.get()
        self.assertRedirects(res, application.get_absolute_url())
        self.assertEqual((application.user, application.vacancy), (self.user, self.vacancy))
        self.assertEqual(application.notes, 'Цікаво')

    def test_cannot_track_same_vacancy_twice(self):
        existing = self.application()
        res = self.client.post(reverse('tracker:application_add', args=[self.vacancy.pk]), {'status': 'found'})
        self.assertRedirects(res, existing.get_absolute_url())
        self.assertEqual(Application.objects.count(), 1)

    def test_create_requires_login_and_permission(self):
        url = reverse('tracker:application_add', args=[self.vacancy.pk])
        anon = Client()
        res = anon.post(url, {'status': 'found'})
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login/', res['Location'])
        guest = Client()
        guest.post(reverse('tracker:guest_login'))
        self.assertEqual(guest.post(url, {'status': 'found'}).status_code, 403)
        self.assertEqual(Application.objects.count(), 0)

    def test_create_missing_vacancy_is_404(self):
        self.assertEqual(self.client.get(reverse('tracker:application_add', args=[9999])).status_code, 404)

    def test_list_shows_only_own_applications_with_match(self):
        self.application()
        other = make_user('other')
        Application.objects.create(user=other, vacancy=make_vacancy('Secret', 'Hidden Role'))
        res = self.client.get(reverse('tracker:application_list'))
        self.assertContains(res, 'Python Intern')
        self.assertContains(res, 'Збіг навичок: 66%')
        self.assertNotContains(res, 'Hidden Role')

    def test_list_status_filter_and_counts(self):
        self.application(status='applied')
        Application.objects.create(user=self.user, vacancy=make_vacancy('B', 'Found Role'))
        res = self.client.get(reverse('tracker:application_list'), {'status': 'applied'})
        self.assertEqual([a.vacancy.position for a in res.context['applications']], ['Python Intern'])
        self.assertEqual((res.context['counts']['total'], res.context['counts']['found']), (2, 1))

    def test_list_is_paginated(self):
        for i in range(10):
            Application.objects.create(user=self.user, vacancy=make_vacancy('P', f'P{i}'))
        res = self.client.get(reverse('tracker:application_list'))
        self.assertEqual(len(res.context['applications']), 8)
        self.assertContains(res, 'page=2')

    def test_gaps_mode_shows_missing_skills(self):
        self.application()
        res = self.client.get(reverse('tracker:application_list') + '?gaps=1')
        self.assertContains(res, 'Бракує (1)')
        self.assertContains(res, 'Docker')
        self.assertContains(res, 'Чого вам найчастіше бракує')
        self.assertNotContains(self.client.get(reverse('tracker:application_list')), 'Бракує (')

    def test_update_changes_status_and_notes(self):
        application = self.application()
        url = reverse('tracker:application_edit', args=[application.pk])
        res = self.client.post(url, {'status': 'applied', 'applied_at': '2026-01-10', 'notes': '  нотатка  '})
        self.assertRedirects(res, application.get_absolute_url())
        application.refresh_from_db()
        self.assertEqual((application.status, application.notes), ('applied', 'нотатка'))

    def test_update_form_cannot_return_to_found(self):
        application = self.application(status='applied')
        res = self.client.post(reverse('tracker:application_edit', args=[application.pk]), {'status': 'found'})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Оберіть допустимий статус зі списку.')
        application.refresh_from_db()
        self.assertEqual(application.status, 'applied')

    def test_future_date_is_rejected_with_ukrainian_message(self):
        application = self.application()
        future = (timezone.localdate() + timedelta(days=3)).isoformat()
        res = self.client.post(reverse('tracker:application_edit', args=[application.pk]),
                               {'status': 'applied', 'applied_at': future})
        self.assertContains(res, 'Дата не може бути в майбутньому.')

    def test_found_status_with_date_is_rejected(self):
        res = self.client.post(reverse('tracker:application_add', args=[self.vacancy.pk]),
                               {'status': 'found', 'applied_at': '2026-01-10'})
        self.assertContains(res, 'Для статусу «Знайдено» дату подачі вказувати не потрібно.')
        self.assertEqual(Application.objects.count(), 0)

    def test_too_long_notes_are_rejected(self):
        res = self.client.post(reverse('tracker:application_add', args=[self.vacancy.pk]),
                               {'status': 'found', 'notes': 'x' * 2001})
        self.assertContains(res, 'Нотатки задовгі')

    def test_delete_requires_post_and_removes_application(self):
        application = self.application()
        url = reverse('tracker:application_delete', args=[application.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(Application.objects.count(), 1)
        self.assertRedirects(self.client.post(url), reverse('tracker:application_list'))
        self.assertEqual(Application.objects.count(), 0)
        self.assertEqual(Vacancy.objects.count(), 1)

    def test_foreign_applications_are_not_accessible(self):
        other = make_user('other')
        foreign = Application.objects.create(user=other, vacancy=self.vacancy)
        for name in ('application_detail', 'application_edit', 'application_delete'):
            self.assertEqual(self.client.get(reverse(f'tracker:{name}', args=[foreign.pk])).status_code, 404, name)
        self.assertEqual(self.client.post(reverse('tracker:application_delete', args=[foreign.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('tracker:change_status', args=[foreign.pk]), {'status': 'offer'}).status_code, 404)
        foreign.refresh_from_db()
        self.assertEqual(foreign.status, 'found')

    def test_change_status(self):
        application = self.application()
        url = reverse('tracker:change_status', args=[application.pk])
        self.assertEqual(self.client.post(url, {'status': 'applied'}).status_code, 302)
        application.refresh_from_db()
        self.assertEqual(application.status, 'applied')
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_change_status_rejects_invalid_found_and_removed_statuses(self):
        application = self.application(status='applied')
        url = reverse('tracker:change_status', args=[application.pk])
        for bad in ('interview', 'tech_interview', 'found', 'nonsense', ''):
            self.assertEqual(self.client.post(url, {'status': bad}).status_code, 400, bad)
            application.refresh_from_db()
            self.assertEqual(application.status, 'applied', bad)

    def test_change_status_next_must_be_local(self):
        application = self.application()
        url = reverse('tracker:change_status', args=[application.pk])
        res = self.client.post(url, {'status': 'applied', 'next': 'https://evil.example/'})
        self.assertEqual(res['Location'], reverse('tracker:application_list'))
        res = self.client.post(url, {'status': 'offer', 'next': '/applications/?status=offer'})
        self.assertEqual(res['Location'], '/applications/?status=offer')

    def test_sort_application_list_by_category(self):
        py = Application.objects.create(user=self.user, vacancy=make_vacancy('A', 'Py Dev', category='Python'))
        java = Application.objects.create(user=self.user, vacancy=make_vacancy('B', 'Java Dev', category='Java'))
        qa = Application.objects.create(user=self.user, vacancy=make_vacancy('C', 'QA Dev', category='QA Engineer'))
        url = reverse('tracker:application_list')

        def ids(**params):
            res = self.client.get(url, params)
            self.assertEqual(res.status_code, 200)
            return [a.pk for a in res.context['applications']]

        self.assertEqual(ids(), [qa.pk, java.pk, py.pk])
        self.assertEqual(ids(category='Java'), [java.pk, qa.pk, py.pk])
        self.assertEqual(ids(category='Python')[0], py.pk)
        self.assertEqual(len(ids(category='Python')), 3)
        self.assertEqual(ids(category='hack'), [qa.pk, java.pk, py.pk])
        Application.objects.filter(pk=py.pk).update(status='applied')
        self.assertEqual(ids(category='Python', status='applied'), [py.pk])

    def test_category_select_matches_job_categories(self):
        res = self.client.get(reverse('tracker:application_list'), {'category': 'Java', 'status': 'found', 'gaps': '1'})
        for tag, title in JOB_CATEGORIES:
            self.assertContains(res, f'>{title}</option>')
        self.assertContains(res, '<option value="Java" selected>')
        self.assertContains(res, '<input type="hidden" name="status" value="found">')
        self.assertContains(res, '<input type="hidden" name="gaps" value="1">')
        self.assertNotContains(res, 'Збіг навичок</option>')
        self.assertNotContains(res, 'Компанія А–Я')

    def test_save_jobs_stores_category_once(self):
        from tracker.services import save_jobs
        raw = {'id': 777, 'jobTitle': 'Dev', 'companyName': 'Acme'}
        save_jobs([raw], 'Python')
        save_jobs([raw], 'Java')
        self.assertEqual(Vacancy.objects.get(external_id='777').category, 'Python')

    def test_dismiss_hides_application_from_everything(self):
        application = self.application()
        url = reverse('tracker:dismiss_application', args=[application.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url).status_code, 302)
        application.refresh_from_db()
        self.assertTrue(application.is_hidden)
        page = self.client.get(reverse('tracker:application_list'))
        self.assertNotContains(page, 'Python Intern')
        self.assertEqual(page.context['counts']['total'], 0)
        self.assertEqual(self.client.get(reverse('tracker:stats')).context['total'], 0)
        for name in ('application_detail', 'application_edit'):
            self.assertEqual(self.client.get(reverse(f'tracker:{name}', args=[application.pk])).status_code, 404)

    def test_tracking_a_dismissed_vacancy_restores_it(self):
        application = self.application(is_hidden=True)
        res = self.client.post(reverse('tracker:application_add', args=[self.vacancy.pk]), {'status': 'found'})
        self.assertRedirects(res, application.get_absolute_url())
        application.refresh_from_db()
        self.assertFalse(application.is_hidden)
        self.assertEqual(Application.objects.count(), 1)

    def test_dismiss_requires_ownership_and_permission(self):
        foreign = Application.objects.create(user=make_user('other'), vacancy=make_vacancy('Z', 'Z'))
        self.assertEqual(self.client.post(reverse('tracker:dismiss_application', args=[foreign.pk])).status_code, 404)
        guest = ensure_guest_user()
        item = Application.objects.create(user=guest, vacancy=self.vacancy)
        self.client.force_login(guest)
        self.assertEqual(self.client.post(reverse('tracker:dismiss_application', args=[item.pk])).status_code, 403)
        item.refresh_from_db()
        self.assertFalse(item.is_hidden)
        self.assertNotContains(self.client.get(reverse('tracker:application_list')), 'Нецікаво')

    def test_list_has_dismiss_but_no_inline_delete(self):
        self.application()
        page = self.client.get(reverse('tracker:application_list'))
        self.assertContains(page, 'Нецікаво')
        self.assertNotContains(page, 'Відкрити вакансію')
        self.assertNotContains(page, '/delete/')

    def test_status_labels(self):
        keys = [k for k, _ in Application._meta.get_field('status').choices]
        self.assertEqual(keys, ['found', 'applied', 'offer', 'rejected'])
        self.assertEqual(dict(Application._meta.get_field('status').choices)['offer'], 'Зацікавило')


class ReminderTests(TestCase):
    def setUp(self):
        self.user = make_user('rem')
        self.application = Application.objects.create(user=self.user, vacancy=make_vacancy())
        self.client.force_login(self.user)
        self.today = timezone.localdate()

    def remind(self, days, **extra):
        return Reminder.objects.create(
            application=self.application, remind_at=self.today + timedelta(days=days), text=f'R{days}', **extra,
        )

    def test_urgency_levels(self):
        self.assertEqual(self.remind(-1).urgency, 'overdue')
        self.assertEqual(self.remind(0).urgency, 'soon')
        self.assertEqual(self.remind(3).urgency, 'soon')
        self.assertEqual(self.remind(4).urgency, 'later')
        self.assertEqual(self.remind(-5, is_done=True).urgency, 'done')

    def test_create_assigns_application_on_server(self):
        url = reverse('tracker:reminder_add', args=[self.application.pk])
        res = self.client.post(url, {'remind_at': '2030-01-01', 'text': '  Співбесіда   о 10  ', 'application': 999})
        self.assertRedirects(res, self.application.get_absolute_url())
        reminder = Reminder.objects.get()
        self.assertEqual((reminder.application, reminder.text), (self.application, 'Співбесіда о 10'))

    def test_short_text_is_rejected(self):
        res = self.client.post(reverse('tracker:reminder_add', args=[self.application.pk]),
                               {'remind_at': '2030-01-01', 'text': 'ab'})
        self.assertContains(res, 'щонайменше трьома символами')
        self.assertEqual(Reminder.objects.count(), 0)

    def test_update_toggle_and_delete(self):
        reminder = self.remind(2)
        self.client.post(reverse('tracker:reminder_edit', args=[reminder.pk]),
                         {'remind_at': '2030-02-02', 'text': 'Нова дата', 'is_done': 'on'})
        reminder.refresh_from_db()
        self.assertEqual((reminder.text, reminder.is_done), ('Нова дата', True))
        self.client.post(reverse('tracker:reminder_toggle', args=[reminder.pk]))
        reminder.refresh_from_db()
        self.assertFalse(reminder.is_done)
        self.assertEqual(self.client.get(reverse('tracker:reminder_toggle', args=[reminder.pk])).status_code, 405)
        res = self.client.post(reverse('tracker:reminder_delete', args=[reminder.pk]))
        self.assertRedirects(res, self.application.get_absolute_url())
        self.assertEqual(Reminder.objects.count(), 0)

    def test_foreign_reminders_are_not_accessible(self):
        other_app = Application.objects.create(user=make_user('o2'), vacancy=make_vacancy('Z', 'Z'))
        foreign = Reminder.objects.create(application=other_app, remind_at=self.today, text='Чуже')
        self.assertEqual(self.client.get(reverse('tracker:reminder_edit', args=[foreign.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('tracker:reminder_delete', args=[foreign.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('tracker:reminder_toggle', args=[foreign.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('tracker:reminder_add', args=[other_app.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse('tracker:reminder_add', args=[other_app.pk]),
                                          {'remind_at': '2030-01-01', 'text': 'Підкинуте'}).status_code, 404)
        self.assertEqual(Reminder.objects.filter(application=other_app).count(), 1)

    def test_overdue_and_soon_are_highlighted_on_list(self):
        self.remind(-2)
        self.remind(1)
        res = self.client.get(reverse('tracker:application_list'))
        self.assertContains(res, 'reminder-overdue')
        self.assertContains(res, 'прострочено')
        self.assertEqual(len(res.context['upcoming']), 2)

    def test_deleting_application_removes_reminders(self):
        self.remind(1)
        self.application.delete()
        self.assertEqual(Reminder.objects.count(), 0)


class StatsTests(TestCase):
    def setUp(self):
        self.user = make_user('st')
        self.client.force_login(self.user)
        for i, status in enumerate(['found', 'applied', 'offer', 'rejected', 'rejected']):
            Application.objects.create(user=self.user, vacancy=make_vacancy('S', f'S{i}'), status=status)

    def test_stats_view_counts(self):
        res = self.client.get(reverse('tracker:stats'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Діаграма статусів')
        self.assertContains(res, '<img src="/stats/chart.png?')
        self.assertEqual((res.context['total'], res.context['offers'], res.context['rejected']), (5, 1, 2))
        self.assertNotIn('offer_rate', res.context)
        self.assertNotContains(res, 'Рівень зацікавленості')
        self.assertNotContains(res, "Інтерв'ю")

    def test_stats_use_few_queries(self):
        with CaptureQueriesContext(connection) as queries:
            self.client.get(reverse('tracker:stats'))
        statement_count = len([q for q in queries if q['sql'].startswith('SELECT') and 'tracker_application' in q['sql']])
        self.assertEqual(statement_count, 1)

    def test_stats_chart_png(self):
        for kind in ('pie', 'bar'):
            res = self.client.get(reverse('tracker:stats_chart') + f'?type={kind}')
            self.assertEqual(res['Content-Type'], 'image/png')
            self.assertTrue(res.content.startswith(b'\x89PNG'))

    def test_stats_chart_empty_data(self):
        Application.objects.all().delete()
        self.assertTrue(self.client.get(reverse('tracker:stats_chart')).content.startswith(b'\x89PNG'))

    def test_period_filter(self):
        old = Application.objects.first()
        Application.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=40))
        self.assertEqual(self.client.get(reverse('tracker:stats'), {'period': 'all'}).context['total'], 5)
        self.assertEqual(self.client.get(reverse('tracker:stats'), {'period': 'month'}).context['total'], 4)
        res = self.client.get(reverse('tracker:stats'), {'period': 'custom', 'date_from': '2026-01-01', 'date_to': '2099-12-31'})
        self.assertContains(res, '2026-01-01')

    def test_stats_show_only_own_data(self):
        Application.objects.create(user=make_user('someone'), vacancy=make_vacancy('Q', 'Q'))
        self.assertEqual(self.client.get(reverse('tracker:stats')).context['total'], 5)

    def test_guest_and_anonymous_have_no_stats(self):
        anon = Client()
        for name in ('stats', 'stats_chart'):
            self.assertEqual(anon.get(reverse(f'tracker:{name}')).status_code, 302)
        guest = Client()
        guest.post(reverse('tracker:guest_login'))
        for name in ('stats', 'stats_chart'):
            self.assertEqual(guest.get(reverse(f'tracker:{name}')).status_code, 403, name)
        self.assertNotContains(guest.get(reverse('tracker:application_list')), reverse('tracker:stats'))
        self.assertContains(self.client.get(reverse('tracker:application_list')), reverse('tracker:stats'))


class RegexValidationTests(TestCase):
    """Перевірка введених даних регулярними виразами (модуль re у tracker/validators.py)."""

    def register(self, username):
        from tracker.forms import RegisterForm
        return RegisterForm({'username': username, 'password1': 'Str0ng-pass-77', 'password2': 'Str0ng-pass-77'})

    def test_username_pattern(self):
        for good in ('abc', 'Olena_92', 'a' * 30):
            self.assertTrue(self.register(good).is_valid(), good)
        for bad in ('ab', 'a' * 31, 'ім\'я', 'bad name', 'x@y.com', '<b>x</b>', 'a-b'):
            form = self.register(bad)
            self.assertFalse(form.is_valid(), bad)
            self.assertIn('username', form.errors)
        self.assertIn('лише латиниця', ' '.join(self.register('a b').errors['username']))

    def test_notes_limit(self):
        from tracker.forms import ApplicationForm
        ok = ApplicationForm({'status': 'applied', 'notes': 'x' * 2000})
        self.assertTrue(ok.is_valid(), ok.errors)
        long = ApplicationForm({'status': 'applied', 'notes': 'x' * 2001})
        self.assertFalse(long.is_valid())
        self.assertIn('не більше 2000 символів', long.errors['notes'][0])

    def test_reminder_text_pattern(self):
        from tracker.forms import ReminderForm
        today = timezone.localdate().isoformat()
        for bad in ('ab', '!!!', '   ', '___', 'x' * 201):
            self.assertFalse(ReminderForm({'remind_at': today, 'text': bad}).is_valid(), bad)
        form = ReminderForm({'remind_at': today, 'text': '  Call \n  HR  '})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['text'], 'Call HR')

    def test_skill_pattern(self):
        from tracker.validators import is_valid_skill
        for good in ('go', 'C#', 'Node.js', 'CI/CD', 'machine learning', 'react-native'):
            self.assertTrue(is_valid_skill(good), good)
        for bad in ('', '<script>', 'a' * 51, 'x;drop', 'a"b'):
            self.assertFalse(is_valid_skill(bad), bad)

    def test_profile_rejects_unsafe_other_skills(self):
        user = make_user('regex')
        self.client.force_login(user)
        self.client.post(reverse('tracker:profile'), {'skill': ['python'], 'other_skills': 'Go, <script>alert(1)</script>, Figma'})
        names = set(StudentProfile.get_profile(user).skill_names())
        self.assertEqual(names, {'python', 'go', 'figma'})

    def test_normalize_spaces(self):
        from tracker.validators import normalize_spaces
        self.assertEqual(normalize_spaces('  a \t b\n\nc '), 'a b c')
        self.assertEqual(normalize_spaces(None), '')


class ProfileTests(TestCase):
    def setUp(self):
        self.user = make_user('leveler')
        self.client.force_login(self.user)
        self.profile = StudentProfile.get_profile(self.user)

    def levels(self):
        return {item.skill.name: item.level for item in self.profile.skill_levels.select_related('skill')}

    def post(self, data):
        return self.client.post(reverse('tracker:profile'), data)

    def test_profile_page(self):
        for skill in Skill.objects.filter(name__in=['python', 'sql']):
            ProfileSkill.objects.create(profile=self.profile, skill=skill)
        res = self.client.get(reverse('tracker:profile'))
        self.assertContains(res, 'Відмітьте технології')
        self.assertContains(res, '>SQL</span>')
        self.assertNotContains(res, "Ім'я студента")
        self.assertNotRegex(res.content.decode(), r'type="radio"[^>]*\bchecked')

    def test_checklist_saves_known_and_other_skills(self):
        self.assertEqual(self.post({'skill': ['python', 'git', 'bogus'], 'other_skills': 'Go, Figma'}).status_code, 302)
        self.assertEqual(set(self.levels()), {'python', 'git', 'go', 'figma'})
        self.assertEqual(Skill.objects.get(name='figma').category, 'other')
        self.assertContains(self.client.get(reverse('tracker:profile')), 'value="python" checked')
        self.assertContains(self.client.get(reverse('tracker:profile')), 'value="figma, go"')

    def test_levels_saved_and_updated_and_removed(self):
        self.post({'skill': ['python', 'java'], 'level_python': 'senior', 'level_java': 'beginner'})
        self.assertEqual(self.levels(), {'python': 'senior', 'java': 'beginner'})
        self.post({'skill': ['python'], 'level_python': 'middle'})
        self.assertEqual(self.levels(), {'python': 'middle'})

    def test_no_levels_outside_languages(self):
        html = self.client.get(reverse('tracker:profile')).content.decode()
        for name in ('django', 'sql', 'qa', 'docker', 'html'):
            self.assertNotIn(f'name="level_{name}"', html)
        for name in ('python', 'english'):
            self.assertIn(f'name="level_{name}"', html)
        self.post({'skill': ['python', 'docker'], 'level_python': 'junior', 'level_docker': 'senior'})
        self.assertEqual(self.levels(), {'python': 'junior', 'docker': ''})

    def test_invalid_level_stays_empty(self):
        self.post({'skill': ['python', 'git'], 'level_python': 'wizard'})
        self.assertEqual(self.levels(), {'python': '', 'git': ''})

    def test_saved_level_is_preselected_and_shown(self):
        self.post({'skill': ['python'], 'level_python': 'senior'})
        res = self.client.get(reverse('tracker:profile'))
        self.assertContains(res, 'name="level_python" value="senior" checked')
        self.assertContains(res, 'Python · Senior')

    def test_english_uses_cefr_scale(self):
        html = self.client.get(reverse('tracker:profile')).content.decode()
        for code in ('a1', 'a2', 'b1', 'b2', 'c1', 'c2'):
            self.assertIn(f'name="level_english" value="{code}"', html)
        self.assertNotIn('name="level_english" value="senior"', html)
        self.post({'skill': ['english', 'python'], 'level_english': 'b2', 'level_python': 'b2'})
        self.assertEqual(self.levels(), {'english': 'b2', 'python': ''})
        self.assertContains(self.client.get(reverse('tracker:profile')), 'English · B2')

    def test_level_does_not_change_match(self):
        vacancy = make_vacancy(skills=['python', 'sql'])
        self.post({'skill': ['python', 'sql'], 'level_python': 'beginner', 'level_sql': 'beginner'})
        low = vacancy.ai_match(self.profile.skill_names())
        self.post({'skill': ['python', 'sql'], 'level_python': 'senior', 'level_sql': 'senior'})
        self.assertEqual(vacancy.ai_match(self.profile.skill_names()), low)

    def test_profile_skill_unique_per_profile(self):
        skill = Skill.objects.get(name='python')
        ProfileSkill.objects.create(profile=self.profile, skill=skill)
        with self.assertRaises(IntegrityError):
            ProfileSkill.objects.create(profile=self.profile, skill=skill)

    def test_profile_requires_login(self):
        res = Client().post(reverse('tracker:profile'), {'skill': ['python']})
        self.assertEqual(res.status_code, 302)
        self.assertIn('login', res['Location'])


class AuthTests(TestCase):
    def test_protected_pages_require_login(self):
        for name in ('application_list', 'stats', 'profile', 'stats_chart'):
            res = self.client.get(reverse(f'tracker:{name}'))
            self.assertEqual(res.status_code, 302, name)
            self.assertIn('/login/', res['Location'])

    def test_register_creates_user_with_user_role_and_logs_in(self):
        res = self.client.post(reverse('tracker:register'), {
            'username': 'newuser', 'password1': 'Str0ng-pass-77', 'password2': 'Str0ng-pass-77',
        })
        self.assertEqual(res.status_code, 302)
        user = User.objects.get(username='newuser')
        self.assertEqual(get_role(user), 'user')
        self.assertEqual(self.client.get(reverse('tracker:application_list')).status_code, 200)

    def test_register_password_mismatch(self):
        res = self.client.post(reverse('tracker:register'), {
            'username': 'newuser', 'password1': 'Str0ng-pass-77', 'password2': 'other',
        })
        self.assertEqual(res.status_code, 200)
        self.assertFalse(User.objects.filter(username='newuser').exists())

    def test_register_page_has_no_safe_filter_output_issues(self):
        res = self.client.get(reverse('tracker:register'))
        self.assertContains(res, '<ul>')

    def test_login_logout_flow(self):
        User.objects.create_user('ann', password=PASSWORD)
        self.assertEqual(self.client.post(reverse('tracker:login'), {'username': 'ann', 'password': PASSWORD}).status_code, 302)
        self.assertEqual(self.client.get(reverse('tracker:application_list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('tracker:logout')).status_code, 405)
        self.assertEqual(self.client.post(reverse('tracker:logout')).status_code, 302)
        self.assertEqual(self.client.get(reverse('tracker:application_list')).status_code, 302)

    def test_login_wrong_password(self):
        User.objects.create_user('ann', password=PASSWORD)
        res = self.client.post(reverse('tracker:login'), {'username': 'ann', 'password': 'wrong'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.client.get(reverse('tracker:stats')).status_code, 302)

    def test_login_redirects_only_to_local_next(self):
        User.objects.create_user('ann', password=PASSWORD)
        res = self.client.post(reverse('tracker:login'), {'username': 'ann', 'password': PASSWORD, 'next': '/stats/'})
        self.assertEqual(res['Location'], '/stats/')
        self.client.post(reverse('tracker:logout'))
        res = self.client.post(reverse('tracker:login'), {'username': 'ann', 'password': PASSWORD, 'next': 'https://evil.com/'})
        self.assertEqual(res['Location'], reverse('tracker:index'))


class ModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('owner', password=PASSWORD)
        self.company = Company.objects.create(name='EPAM')
        self.python = Skill.objects.get(name='python')
        self.vacancy = Vacancy.objects.create(company=self.company, position='QA Trainee')
        self.vacancy.skills.add(self.python, Skill.objects.get(name='sql'))

    def test_str_methods(self):
        self.assertEqual(str(self.company), 'EPAM')
        self.assertEqual(str(self.python), 'Python')
        self.assertEqual(str(self.vacancy), 'EPAM — QA Trainee')
        application = Application.objects.create(user=self.user, vacancy=self.vacancy)
        self.assertIn('Знайдено', str(application))
        reminder = Reminder.objects.create(application=application, remind_at=date(2026, 11, 1), text='Співбесіда')
        self.assertEqual(str(reminder), '01.11.2026 — Співбесіда')
        self.assertIn('owner', str(StudentProfile.get_profile(self.user)))

    def test_absolute_urls(self):
        application = Application.objects.create(user=self.user, vacancy=self.vacancy)
        self.assertEqual(self.vacancy.get_absolute_url(), f'/vacancies/{self.vacancy.pk}/')
        self.assertEqual(application.get_absolute_url(), f'/applications/{application.pk}/')
        self.assertEqual(self.company.get_absolute_url(), f'/companies/{self.company.pk}/')
        self.assertEqual(self.python.get_absolute_url(), f'/skills/{self.python.pk}/')

    def test_related_names(self):
        application = Application.objects.create(user=self.user, vacancy=self.vacancy)
        Reminder.objects.create(application=application, remind_at=date(2026, 11, 1), text='Тест')
        self.assertEqual(self.python.vacancies.count(), 1)
        self.assertEqual(self.company.vacancies.count(), 1)
        self.assertEqual(self.user.applications.count(), 1)
        self.assertEqual(application.reminders.count(), 1)

    def test_constraints(self):
        Application.objects.create(user=self.user, vacancy=self.vacancy)
        with self.assertRaises(IntegrityError):
            Application.objects.create(user=self.user, vacancy=self.vacancy)

    def test_vacancy_unique_external_id_per_source(self):
        Vacancy.objects.create(company=self.company, position='A', source='jobicy', external_id='1')
        with self.assertRaises(IntegrityError):
            Vacancy.objects.create(company=self.company, position='B', source='jobicy', external_id='1')

    def test_company_protected_and_user_cascade(self):
        with self.assertRaises(ProtectedError):
            self.company.delete()
        Application.objects.create(user=self.user, vacancy=self.vacancy)
        self.user.delete()
        self.assertEqual((Application.objects.count(), Vacancy.objects.count()), (0, 1))

    def test_vacancy_in_use_cannot_be_deleted(self):
        Application.objects.create(user=self.user, vacancy=self.vacancy)
        with self.assertRaises(ProtectedError):
            self.vacancy.delete()


class RolesTests(TestCase):
    def setUp(self):
        self.owner = make_user('regular')
        self.vacancy = make_vacancy('Acme', 'Dev')
        self.application = Application.objects.create(user=self.owner, vacancy=self.vacancy)

    def as_guest(self):
        self.assertEqual(self.client.post(reverse('tracker:guest_login')).status_code, 302)
        return User.objects.get(username='guest')

    def test_guest_login_creates_readonly_account(self):
        guest = self.as_guest()
        self.assertEqual(get_role(guest), 'guest')
        self.assertFalse(guest.has_usable_password())
        self.assertEqual(list(guest.groups.values_list('name', flat=True)), ['Guest'])
        self.assertEqual(Application.objects.filter(user=guest).count(), 0)
        profile = StudentProfile.get_profile(guest)
        self.assertEqual(profile.full_name, '')
        self.assertFalse(profile.skill_levels.exists())

    def test_guest_login_resets_previous_guest_data(self):
        guest = self.as_guest()
        Application.objects.create(user=guest, vacancy=self.vacancy)
        self.client.post(reverse('tracker:logout'))
        self.as_guest()
        self.assertEqual(Application.objects.filter(user=guest).count(), 0)

    def test_guest_login_requires_post(self):
        self.assertEqual(self.client.get(reverse('tracker:guest_login')).status_code, 405)

    def test_group_permissions(self):
        ensure_roles()
        guest = set(Group.objects.get(name='Guest').permissions.values_list('codename', flat=True))
        user = set(Group.objects.get(name='User').permissions.values_list('codename', flat=True))
        self.assertTrue(all(c.startswith('view_') or c == 'sync_vacancies' for c in guest))
        self.assertTrue({'view_vacancy', 'view_company', 'view_skill', 'view_application', 'sync_vacancies'} <= guest)
        self.assertNotIn('view_stats', guest)
        self.assertTrue({'add_application', 'change_application', 'delete_application', 'view_stats',
                         'add_reminder', 'change_reminder', 'delete_reminder', 'sync_vacancies'} <= user)
        self.assertFalse(user & {'add_vacancy', 'change_vacancy', 'delete_vacancy', 'add_company'})

    def test_ensure_roles_is_idempotent(self):
        ensure_roles()
        before = {g.name: g.permissions.count() for g in Group.objects.all()}
        ensure_roles()
        self.assertEqual(before, {g.name: g.permissions.count() for g in Group.objects.all()})

    def test_guest_can_browse_catalog_list_and_profile_page(self):
        self.as_guest()
        for name in ('application_list', 'profile', 'company_list', 'skill_list'):
            self.assertEqual(self.client.get(reverse(f'tracker:{name}')).status_code, 200, name)
        self.assertEqual(self.client.get(self.vacancy.get_absolute_url()).status_code, 200)

    def test_guest_gets_autoloaded_found_list_but_cannot_change_it(self):
        with patch('tracker.views.sync_all_categories', side_effect=lambda user, **kw: (*sync_jobicy('Python', user=user), [])):
            with patch('tracker.services.requests.get', return_value=jobicy_response(JOB)):
                guest = self.as_guest()
        item = Application.objects.get(user=guest)
        self.assertEqual(item.status, 'found')
        page = self.client.get(reverse('tracker:application_list'))
        self.assertContains(page, 'Python Internship')
        self.assertNotContains(page, 'name="status"')
        self.assertEqual(self.client.post(reverse('tracker:change_status', args=[item.pk]), {'status': 'offer'}).status_code, 403)
        item.refresh_from_db()
        self.assertEqual(item.status, 'found')

    def test_guest_cannot_use_applications_or_reminders(self):
        self.as_guest()
        reminder = Reminder.objects.create(application=self.application, remind_at=date(2030, 1, 1), text='Нагадування')
        checks = [
            ('post', reverse('tracker:application_add', args=[self.vacancy.pk])),
            ('post', reverse('tracker:application_edit', args=[self.application.pk])),
            ('post', reverse('tracker:application_delete', args=[self.application.pk])),
            ('post', reverse('tracker:change_status', args=[self.application.pk])),
            ('post', reverse('tracker:dismiss_application', args=[self.application.pk])),
            ('post', reverse('tracker:reminder_add', args=[self.application.pk])),
            ('post', reverse('tracker:reminder_toggle', args=[reminder.pk])),
            ('post', reverse('tracker:reminder_delete', args=[reminder.pk])),
        ]
        for method, url in checks:
            self.assertEqual(getattr(self.client, method)(url, {'status': 'offer'}).status_code, 403, url)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'found')
        self.assertEqual(Application.objects.count(), 1)
        self.assertEqual(Reminder.objects.count(), 1)

    def test_guest_nav_hides_stats_link(self):
        self.as_guest()
        page = self.client.get(reverse('tracker:application_list')).content.decode()
        self.assertIn(reverse('tracker:application_list'), page)
        self.assertNotIn(reverse('tracker:stats'), page)

    def test_guest_cannot_change_profile(self):
        self.as_guest()
        res = self.client.post(reverse('tracker:profile'), {'skill': ['python']})
        self.assertEqual(res.status_code, 403)
        self.assertFalse(StudentProfile.get_profile(User.objects.get(username='guest')).skill_levels.exists())

    def test_guest_profile_page_asks_to_register(self):
        self.as_guest()
        res = self.client.get(reverse('tracker:profile'))
        self.assertTemplateUsed(res, 'profile_guest.html')
        self.assertContains(res, 'потрібно зареєструватися')

    def test_guest_can_register_and_becomes_regular_user(self):
        self.as_guest()
        res = self.client.post(reverse('tracker:register'), {
            'username': 'convert', 'password1': 'Str0ng-pass-77', 'password2': 'Str0ng-pass-77',
        })
        self.assertEqual(res.status_code, 302)
        self.assertEqual(get_role(User.objects.get(username='convert')), 'user')
        self.assertEqual(self.client.get(reverse('tracker:application_list')).status_code, 200)

    def test_forbidden_page_explains_guest_limits(self):
        self.as_guest()
        res = self.client.get(reverse('tracker:stats'))
        self.assertContains(res, 'Гість може лише переглядати', status_code=403)

    def test_anonymous_sees_hero_page_on_home(self):
        res = self.client.get(reverse('tracker:index'))
        self.assertTemplateUsed(res, 'landing.html')
        self.assertContains(res, reverse('tracker:guest_login'))
        self.assertEqual(self.client.post(reverse('tracker:index')).status_code, 405)

    def test_logged_in_user_is_sent_to_application_list(self):
        self.client.force_login(self.owner)
        self.assertRedirects(self.client.get(reverse('tracker:index')), reverse('tracker:application_list'))

    def test_navbar_has_single_vacancies_item_without_reminders(self):
        self.client.force_login(self.owner)
        res = self.client.get(reverse('tracker:application_list'))
        nav = res.content.decode().split('<main')[0]
        self.assertEqual(nav.count('>Вакансії</a>'), 1)
        self.assertIn(f'href="{reverse("tracker:application_list")}"', nav)
        self.assertNotIn('Нагадування', nav)
        self.assertNotIn('Мої заявки', nav)
        self.assertNotContains(res, 'Каталог вакансій')
        self.assertNotContains(res, 'Відстежувати')

    def test_vacancy_cards_have_no_details_button(self):
        self.client.force_login(self.owner)
        self.assertNotContains(self.client.get(reverse('tracker:application_list')), 'Докладніше')

    def test_no_hardcoded_urls_in_static_js(self):
        from pathlib import Path
        js = Path(__file__).resolve().parent.parent / 'static' / 'js'
        self.assertFalse(js.exists() and any(js.iterdir()))

    def test_reminder_pages_still_exist_without_menu_item(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse('tracker:reminder_list')).status_code, 200)

    def test_anonymous_navbar_has_no_vacancies_tab(self):
        nav = self.client.get(reverse('tracker:index')).content.decode().split('<main')[0]
        self.assertNotIn('>Вакансії</a>', nav)
        self.assertIn(reverse('tracker:login'), nav)
        self.assertIn(reverse('tracker:register'), nav)

    def test_anonymous_cannot_track_vacancy(self):
        res = self.client.get(reverse('tracker:application_add', args=[self.vacancy.pk]))
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login/', res['Location'])

    def test_registered_user_gets_user_role_via_signal(self):
        user = User.objects.create_user('signal', password=PASSWORD)
        self.assertTrue(user.groups.filter(name='User').exists())

    def test_existing_user_without_group_gets_user_role_after_migrate(self):
        legacy = User.objects.create_user('legacy', password=PASSWORD)
        legacy.groups.clear()
        setup_roles(sender=None)
        self.assertTrue(legacy.groups.filter(name='User').exists())

    def test_superuser_keeps_full_access(self):
        boss = User.objects.create_superuser('boss', password=PASSWORD)
        self.client.force_login(boss)
        self.assertEqual(self.client.get(reverse('tracker:stats')).status_code, 200)

    def test_each_user_has_exactly_three_roles(self):
        self.assertEqual(get_role(self.client_user()), 'user')
        self.client.logout()
        self.assertEqual(get_role(__import__('django.contrib.auth.models', fromlist=['AnonymousUser']).AnonymousUser()), 'anonymous')

    def client_user(self):
        self.client.force_login(self.owner)
        return self.owner


class ApiTests(TestCase):
    def setUp(self):
        self.user = make_user('api')
        self.vacancy = make_vacancy('Acme', 'Python Intern', ['python'])
        self.application = Application.objects.create(user=self.user, vacancy=self.vacancy)

    def put(self, payload, pk=None):
        return self.client.put(
            reverse('tracker:api_application', args=[pk or self.application.pk]),
            json.dumps(payload), content_type='application/json',
        )

    def test_vacancies_api_is_public_and_read_only(self):
        url = reverse('tracker:api_vacancies')
        res = self.client.get(url, {'q': 'acme'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['count'], 1)
        self.assertEqual(res['X-Request-Method'], 'GET')
        self.assertEqual(self.client.get(url, {'skill': 'java'}).json()['count'], 0)
        self.assertEqual(self.client.post(url, json.dumps({'company': 'X'}), content_type='application/json').status_code, 405)

    def test_application_api_crud(self):
        self.client.force_login(self.user)
        url = reverse('tracker:api_application', args=[self.application.pk])
        self.assertEqual(self.client.get(url).json()['application']['status'], 'found')
        res = self.put({'status': 'offer', 'notes': 'ok'})
        self.assertEqual(res.status_code, 200)
        self.application.refresh_from_db()
        self.assertEqual((self.application.status, self.application.notes), ('offer', 'ok'))
        self.assertEqual(self.client.delete(url).status_code, 200)
        self.assertFalse(Application.objects.exists())

    def test_application_api_rejects_invalid_status_and_json(self):
        self.client.force_login(self.user)
        for bad in ('interview', 'found', 'x'):
            self.assertEqual(self.put({'status': bad}).status_code, 400, bad)
        res = self.client.put(reverse('tracker:api_application', args=[self.application.pk]),
                              '{broken', content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.application.refresh_from_db()
        self.assertEqual(self.application.status, 'found')

    def test_application_api_is_private(self):
        foreign = Application.objects.create(user=make_user('other'), vacancy=make_vacancy('B', 'B'))
        self.client.force_login(self.user)
        url = reverse('tracker:api_application', args=[foreign.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.put({'status': 'offer'}, pk=foreign.pk).status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)
        self.assertEqual(Client().get(url).status_code, 302)

    def test_guest_api_write_is_forbidden(self):
        guest = Client()
        guest.post(reverse('tracker:guest_login'))
        url = reverse('tracker:api_application', args=[self.application.pk])
        self.assertEqual(guest.put(url, '{"status": "offer"}', content_type='application/json').status_code, 403)
        self.assertEqual(guest.delete(url).status_code, 403)
        self.assertTrue(Application.objects.filter(pk=self.application.pk).exists())


class TemplateTagTests(TestCase):
    def render(self, source, **context):
        return Template('{% load tracker_tags %}' + source).render(Context(context))

    def test_status_badge(self):
        html = self.render('{% status_badge "offer" %}')
        self.assertIn('badge-offer', html)
        self.assertIn('Зацікавило', html)

    def test_query_string_keeps_filters_and_replaces_page(self):
        request = RequestFactory().get('/vacancies/', {'q': 'py', 'page': '2', 'sort': 'old'})
        html = self.render('{% query_string page=3 %}', request=request)
        self.assertIn('q=py', html)
        self.assertIn('sort=old', html)
        self.assertIn('page=3', html)
        self.assertNotIn('page=2', html)

    def test_skill_pills_neutral_and_matched(self):
        vacancy = make_vacancy(skills=['python', 'docker'])
        neutral = self.render('{% skill_pills vacancy %}', vacancy=vacancy)
        self.assertIn('pill-neutral', neutral)
        matched = self.render('{% skill_pills vacancy match %}', vacancy=vacancy, match=vacancy.ai_match({'python'}))
        self.assertIn('pill-match', matched)
        self.assertIn('pill-miss', matched)

    def test_reminder_badge_marks_overdue(self):
        reminder = Reminder(remind_at=timezone.localdate() - timedelta(days=1), text='Тест')
        html = self.render('{% reminder_badge reminder %}', reminder=reminder)
        self.assertIn('reminder-overdue', html)
        self.assertIn('прострочено', html)


class DemoDataTests(TestCase):
    def test_seed_data_builds_catalog_user_and_guest(self):
        call_command('seed_data', stdout=Mock())
        user = User.objects.get(username='demo')
        self.assertTrue(user.check_password('demo12345'))
        self.assertGreaterEqual(Vacancy.objects.count(), 8)
        self.assertEqual(Application.objects.filter(user=user).count(), 6)
        self.assertTrue(Reminder.objects.filter(application__user=user, is_done=False).exists())
        self.assertTrue(User.objects.filter(username='guest').exists())
        call_command('seed_data', stdout=Mock())
        self.assertEqual(Vacancy.objects.filter(source='demo').count(), 8)
        self.assertEqual(Application.objects.filter(user=user).count(), 6)