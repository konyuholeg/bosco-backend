from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from tracker.models import Application, Company, Reminder, Vacancy
from tracker.roles import ensure_guest_user

User = get_user_model()


class ReminderListDetailTests(TestCase):
    """В6.1: List і Detail для нагадувань; доступ лише до власних."""

    def setUp(self):
        self.today = timezone.localdate()
        company = Company.objects.create(name='SoftServe')
        self.vacancy = Vacancy.objects.create(company=company, position='Python Internship')
        self.user = User.objects.create_user('owner', password='pass12345')
        self.other = User.objects.create_user('other', password='pass12345')
        self.application = Application.objects.create(user=self.user, vacancy=self.vacancy, status='applied')
        self.foreign_application = Application.objects.create(user=self.other, vacancy=self.vacancy, status='applied')
        self.active = Reminder.objects.create(
            application=self.application, remind_at=self.today + timedelta(days=2), text='Співбесіда')
        self.overdue = Reminder.objects.create(
            application=self.application, remind_at=self.today - timedelta(days=3), text='Тестове завдання')
        self.done = Reminder.objects.create(
            application=self.application, remind_at=self.today, text='Дзвінок HR', is_done=True)
        self.foreign = Reminder.objects.create(
            application=self.foreign_application, remind_at=self.today, text='Чуже нагадування')
        self.client = Client()
        self.client.force_login(self.user)

    def test_list_shows_only_own_reminders(self):
        res = self.client.get(reverse('tracker:reminder_list'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Співбесіда')
        self.assertContains(res, 'Дзвінок HR')
        self.assertNotContains(res, 'Чуже нагадування')

    def test_list_filters_by_state(self):
        url = reverse('tracker:reminder_list')
        overdue = self.client.get(url, {'state': 'overdue'})
        self.assertContains(overdue, 'Тестове завдання')
        self.assertNotContains(overdue, 'Співбесіда')
        done = self.client.get(url, {'state': 'done'})
        self.assertContains(done, 'Дзвінок HR')
        self.assertNotContains(done, 'Тестове завдання')
        active = self.client.get(url, {'state': 'active'})
        self.assertContains(active, 'Співбесіда')
        self.assertNotContains(active, 'Дзвінок HR')

    def test_unknown_state_is_ignored(self):
        res = self.client.get(reverse('tracker:reminder_list'), {'state': 'bogus'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.context['reminders']), 3)

    def test_tab_counts_use_aggregate(self):
        counts = self.client.get(reverse('tracker:reminder_list')).context['counts']
        self.assertEqual((counts['total'], counts['active'], counts['overdue'], counts['done']), (3, 2, 1, 1))

    def test_pagination(self):
        for i in range(10):
            Reminder.objects.create(application=self.application, remind_at=self.today, text=f'Задача {i}')
        res = self.client.get(reverse('tracker:reminder_list'))
        self.assertTrue(res.context['is_paginated'])
        self.assertEqual(len(res.context['reminders']), 10)
        self.assertEqual(self.client.get(reverse('tracker:reminder_list'), {'page': 2}).status_code, 200)

    def test_detail_of_own_reminder(self):
        res = self.client.get(reverse('tracker:reminder_detail', args=[self.active.pk]))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'Співбесіда')
        self.assertContains(res, 'Python Internship')

    def test_foreign_reminder_detail_is_404(self):
        self.assertEqual(self.client.get(reverse('tracker:reminder_detail', args=[self.foreign.pk])).status_code, 404)

    def test_anonymous_is_redirected_to_login(self):
        anonymous = Client()
        for url in (reverse('tracker:reminder_list'), reverse('tracker:reminder_detail', args=[self.active.pk])):
            res = anonymous.get(url)
            self.assertEqual(res.status_code, 302)
            self.assertIn(reverse('tracker:login'), res['Location'])

    def test_guest_sees_empty_list_and_no_foreign_detail(self):
        guest = Client()
        guest.force_login(ensure_guest_user())
        res = guest.get(reverse('tracker:reminder_list'))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(res.context['reminders']), 0)
        self.assertEqual(guest.get(reverse('tracker:reminder_detail', args=[self.active.pk])).status_code, 404)

    def test_nav_has_reminders_link(self):
        res = self.client.get(reverse('tracker:reminder_list'))
        self.assertContains(res, reverse('tracker:reminder_list'))
