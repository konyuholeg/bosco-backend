from django.urls import path

from tracker import landing, views

app_name = 'tracker'

urlpatterns = [
    path('', landing.home, name='index'),

    path('vacancies/<int:pk>/', views.VacancyDetailView.as_view(), name='vacancy_detail'),
    path('companies/', views.CompanyListView.as_view(), name='company_list'),
    path('companies/<int:pk>/', views.CompanyDetailView.as_view(), name='company_detail'),
    path('skills/', views.SkillListView.as_view(), name='skill_list'),
    path('skills/<int:pk>/', views.SkillDetailView.as_view(), name='skill_detail'),

    path('applications/', views.ApplicationListView.as_view(), name='application_list'),
    path('applications/add/<int:vacancy_pk>/', views.ApplicationCreateView.as_view(), name='application_add'),
    path('applications/<int:pk>/', views.ApplicationDetailView.as_view(), name='application_detail'),
    path('applications/<int:pk>/edit/', views.ApplicationUpdateView.as_view(), name='application_edit'),
    path('applications/<int:pk>/delete/', views.ApplicationDeleteView.as_view(), name='application_delete'),
    path('applications/<int:pk>/status/', views.change_status, name='change_status'),
    path('applications/<int:pk>/dismiss/', views.dismiss_application, name='dismiss_application'),
    path('applications/<int:application_pk>/reminders/add/', views.ReminderCreateView.as_view(), name='reminder_add'),
    path('reminders/', views.ReminderListView.as_view(), name='reminder_list'),
    path('reminders/<int:pk>/', views.ReminderDetailView.as_view(), name='reminder_detail'),
    path('reminders/<int:pk>/edit/', views.ReminderUpdateView.as_view(), name='reminder_edit'),
    path('reminders/<int:pk>/delete/', views.ReminderDeleteView.as_view(), name='reminder_delete'),
    path('reminders/<int:pk>/toggle/', views.reminder_toggle, name='reminder_toggle'),

    path('stats/', views.stats, name='stats'),
    path('stats/chart.png', views.stats_chart, name='stats_chart'),
    path('profile/', views.profile_view, name='profile'),

    path('login/', views.login_view, name='login'),
    path('register/', views.register_view, name='register'),
    path('guest/', views.guest_login, name='guest_login'),
    path('logout/', views.logout_view, name='logout'),

    path('api/vacancies/', views.vacancies_collection, name='api_vacancies'),
    path('api/applications/<int:pk>/', views.application_resource, name='api_application'),
]
