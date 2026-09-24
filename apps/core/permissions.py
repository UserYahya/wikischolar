"""Role-based access control (least privilege)."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

VIEWER = {
    "students.view", "reference.view", "schools.view", "messages.view",
}
ADMIN = VIEWER | {
    "students.edit", "students.delete", "students.export",
    "reference.edit", "schools.edit", "schools.merge",
    "messages.send", "audit.view",
}
SUPER_ADMIN = ADMIN | {"admins.manage", "settings.manage"}

ROLE_PERMISSIONS = {"viewer": VIEWER, "admin": ADMIN, "super_admin": SUPER_ADMIN}


def role_has(role, code):
    return code in ROLE_PERMISSIONS.get(role, set())


def require_perm(code):
    def deco(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.has_perm_code(code):
                raise PermissionDenied(f"Missing permission: {code}")
            return view(request, *args, **kwargs)
        return wrapped
    return deco
