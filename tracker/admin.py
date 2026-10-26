from django.contrib import admin
from tracker.models import Application, Company, ProfileSkill, Reminder, Skill, StudentProfile, Vacancy


class ProfileSkillInline(admin.TabularInline):
    model = ProfileSkill
    extra = 0


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'user')
    search_fields = ('full_name', 'user__username')
    inlines = [ProfileSkillInline]


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ('name', 'website', 'created_at')
    search_fields = ('name',)


@admin.register(Skill)
class SkillAdmin(admin.ModelAdmin):
    list_display = ('title', 'name', 'category')
    list_filter = ('category',)
    search_fields = ('title', 'name')


@admin.register(Vacancy)
class VacancyAdmin(admin.ModelAdmin):
    list_display = ('company', 'position', 'location', 'is_remote', 'salary_min', 'salary_max', 'source')
    list_filter = ('source', 'is_remote', 'company')
    search_fields = ('position', 'company__name', 'description')
    filter_horizontal = ('skills',)


class ReminderInline(admin.TabularInline):
    model = Reminder
    extra = 0


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ('vacancy', 'user', 'status', 'is_hidden', 'applied_at', 'created_at')
    list_filter = ('status', 'is_hidden')
    search_fields = ('vacancy__position', 'vacancy__company__name', 'user__username')
    inlines = [ReminderInline]


@admin.register(Reminder)
class ReminderAdmin(admin.ModelAdmin):
    list_display = ('text', 'application', 'remind_at', 'is_done')
    list_filter = ('is_done',)
    search_fields = ('text',)


@admin.register(ProfileSkill)
class ProfileSkillAdmin(admin.ModelAdmin):
    list_display = ('profile', 'skill', 'level')
    list_filter = ('level', 'skill__category')
    search_fields = ('profile__full_name', 'profile__user__username', 'skill__title')
