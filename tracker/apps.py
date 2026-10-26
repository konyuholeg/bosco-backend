from django.apps import AppConfig
from django.conf import settings
from django.db.models.signals import post_migrate, post_save


class TrackerConfig(AppConfig):
    name = 'tracker'

    def ready(self):
        from tracker.roles import assign_default_role, setup_roles

        post_migrate.connect(setup_roles, sender=self, dispatch_uid='tracker.setup_roles')
        post_save.connect(
            assign_default_role, sender=settings.AUTH_USER_MODEL, dispatch_uid='tracker.assign_default_role',
        )
