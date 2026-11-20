from django.db.models import Q
from django.http import Http404
from .models import CARE_KINDS


def access_level(member, kind):
    if member.user_id == member.circle.owner_id:
        return 'help'
    value = member.care_permissions.get(kind, 'none')
    return value if value in ['view', 'help'] else 'none'


def allowed_kinds(member):
    return [kind for kind, _ in CARE_KINDS if access_level(member, kind) != 'none']


def task_filter(member):
    return Q(care_record__isnull=True) | Q(care_record__kind__in=allowed_kinds(member), care_record__archived=False)


def check_task_access(member, task):
    if task.care_record_id and (task.care_record.archived or access_level(member, task.care_record.kind) == 'none'):
        raise Http404
