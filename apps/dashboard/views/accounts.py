from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.password_validation import password_validators_help_texts, validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core import audit, ratelimit, turnstile
from apps.core.models import Admin, AuditLog, Role
from apps.core.permissions import require_perm
from apps.core.utils import client_ip

from ..forms import AdminCreateForm
from ._util import paginate


class RateLimitedAuthForm(AuthenticationForm):
    def clean(self):
        from django import forms
        if not ratelimit.allow("login_per_ip", client_ip(self.request) or "unknown"):
            raise forms.ValidationError("Too many sign-in attempts. Wait 15 minutes and try again.")
        # Cloudflare Turnstile, when configured (checked before the password is even looked at)
        if not turnstile.verify(self.data.get(turnstile.TOKEN_FIELD, ""), client_ip(self.request)):
            raise forms.ValidationError("Complete the security check, then sign in again.")
        return super().clean()

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if user.is_deleted:
            from django import forms
            raise forms.ValidationError("This account has been deactivated.", code="inactive")


login_view = auth_views.LoginView.as_view(template_name="dashboard/login.html",
                                          authentication_form=RateLimitedAuthForm, redirect_authenticated_user=True)


@require_POST
def logout_view(request):
    return auth_views.LogoutView.as_view(next_page="dashboard:login")(request)


@login_required
def password_change(request):
    """Any admin changes their own password (current password + the new one twice). Other sessions of
    this account are signed out; this one stays signed in."""
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        update_session_auth_hash(request, form.user)
        audit.record("admin.password_changed", request=request, entity=form.user)
        messages.success(request, "Your password has been changed.")
        return redirect("dashboard:home")
    return render(request, "dashboard/password_change.html",
                  {"form": form, "rules": password_validators_help_texts()})


@require_perm("audit.view")
def audit_log(request):
    qs = AuditLog.objects.select_related("actor")
    action, actor, entity = request.GET.get("action", ""), request.GET.get("actor", ""), request.GET.get("entity", "")
    if action:
        qs = qs.filter(action__startswith=action)
    if actor:
        qs = qs.filter(actor_label__icontains=actor)
    if entity:
        qs = qs.filter(entity_id=entity)
    page, qstring = paginate(request, qs, 100)
    actions = AuditLog.objects.order_by().values_list("action", flat=True).distinct()
    return render(request, "dashboard/audit.html", {"page": page, "qstring": qstring, "actions": sorted(actions),
                                                    "f": {"action": action, "actor": actor, "entity": entity}})


@require_perm("admins.manage")
def admin_list(request):
    form = AdminCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            d = form.cleaned_data
            admin = Admin.objects.create_user(email=d["email"], password=d["password"], full_name=d["full_name"],
                                              role=d["role"], created_by=request.user)
            audit.record("admin.created", request=request, entity=admin, after=audit.snapshot(admin))
        messages.success(request, f"Admin {admin.email} created. Share the temporary password through a secure channel.")
        return redirect("dashboard:admins")
    admins = Admin.objects.select_related("created_by").order_by("is_deleted", "full_name")
    return render(request, "dashboard/admins.html", {"admins": admins, "form": form, "roles": Role.choices})


@require_POST
@require_perm("admins.manage")
@transaction.atomic
def admin_update(request, pk):
    admin = get_object_or_404(Admin, pk=pk)
    if admin.pk == request.user.pk:
        messages.error(request, "You can't change your own role or deactivate yourself.")
        return redirect("dashboard:admins")
    before = audit.snapshot(admin)
    op = request.POST.get("op")
    if op == "role" and request.POST.get("role") in Role.values:
        admin.role = request.POST["role"]
    elif op == "deactivate":
        admin.is_active, admin.is_deleted, admin.deleted_at, admin.deleted_by = False, True, timezone.now(), request.user
    elif op == "reactivate":
        admin.is_active, admin.is_deleted, admin.deleted_at, admin.deleted_by = True, False, None, None
    elif op == "password":
        # Super Admin sets a new temporary password for someone who forgot theirs; it signs them out
        # everywhere. The password itself is never logged.
        password = request.POST.get("password", "")
        try:
            validate_password(password, user=admin)
        except ValidationError as exc:
            messages.error(request, f"Password for {admin.email} not changed: " + " ".join(exc.messages))
            return redirect("dashboard:admins")
        admin.set_password(password)
        admin.save()
        audit.record("admin.password_reset", request=request, entity=admin)
        messages.success(request, f"New password set for {admin.email}. Share it through a secure channel and "
                                  "ask them to change it on “Change password” after signing in.")
        return redirect("dashboard:admins")
    else:
        messages.error(request, "Unknown action.")
        return redirect("dashboard:admins")
    admin.save()
    audit.record(f"admin.{op}", request=request, entity=admin, before=before, after=audit.snapshot(admin))
    messages.success(request, f"Updated {admin.email}.")
    return redirect("dashboard:admins")
