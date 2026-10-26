from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

from tracker.models import SETTABLE_STATUSES, STATUS_CHOICES, Application, Reminder
from tracker.services import JOB_CATEGORIES
from tracker.validators import normalize_spaces, validate_notes, validate_reminder_text, validate_username

class CategorySortForm(forms.Form):
    """Вибір категорії для кнопки «Сортувати» (GET-параметр; не пов'язана з моделлю)."""
    category = forms.ChoiceField(
        choices=JOB_CATEGORIES, required=False, label='Сортувати за',
        error_messages={'invalid_choice': 'Оберіть категорію зі списку.'},
        widget=forms.Select(attrs={'class': 'form-select form-select-sm w-auto'}),
    )

    def clean_category(self):
        return normalize_spaces(self.cleaned_data['category'])


class ApplicationForm(forms.ModelForm):
    """Заявка користувача: власник і вакансія задаються у view, а не у формі."""

    class Meta:
        model = Application
        fields = ['status', 'applied_at', 'notes']
        error_messages = {
            'status': {'invalid_choice': 'Оберіть допустимий статус зі списку.'},
            'applied_at': {'invalid': 'Введіть дату у форматі РРРР-ММ-ДД.'},
        }
        widgets = {
            'status': forms.Select(attrs={'class': 'form-select'}),
            'applied_at': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Контакти рекрутера, вимоги, нотатки'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            allowed = list(SETTABLE_STATUSES)
            if self.instance.status == 'found':
                allowed.insert(0, STATUS_CHOICES[0])
            self.fields['status'].choices = allowed

    def clean_notes(self):
        notes = self.cleaned_data['notes'].strip()
        validate_notes(notes)
        return notes

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('status') == 'found' and cleaned.get('applied_at'):
            self.add_error('applied_at', 'Для статусу «Знайдено» дату подачі вказувати не потрібно.')
        return cleaned


class ReminderForm(forms.ModelForm):
    class Meta:
        model = Reminder
        fields = ['remind_at', 'text']
        widgets = {
            'is_done': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'remind_at': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}, format='%Y-%m-%d'),
            'text': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'напр. Технічна співбесіда або дедлайн тестового'}),
        }

    def clean_text(self):
        text = normalize_spaces(self.cleaned_data['text'])
        validate_reminder_text(text)
        return text


class ReminderUpdateForm(ReminderForm):
    class Meta(ReminderForm.Meta):
        fields = ['remind_at', 'text', 'is_done']


class RegisterForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        fields = ('username',)

    def clean_username(self):
        username = super().clean_username()
        validate_username(username)
        return username

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs['class'] = 'form-control'
