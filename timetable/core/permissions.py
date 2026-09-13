"""
Role-Based Access Control (RBAC) & Scope Enforcement for FUD ATMS.
Implements the Principle of Least Privilege and defensible role boundaries.
"""
from functools import wraps
from django.shortcuts import redirect
from django.core.exceptions import PermissionDenied
from django.contrib import messages
from django.http import JsonResponse


def role_required(allowed_roles):
    """
    Decorator enforcing that the authenticated user possesses one of the allowed roles.
    Redirects to login if unauthenticated, or raises 403 / denies access if unauthorized.
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                messages.warning(request, "Please log in with your institutional credentials to access this portal.")
                return redirect('/login/')

            if request.user.role not in allowed_roles:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.path.startswith('/api/'):
                    return JsonResponse({'error': 'Unauthorized role access.'}, status=403)
                messages.error(request, "Access Denied: You do not possess the required institutional privilege.")
                raise PermissionDenied("Access Denied by Institutional RBAC Policy.")

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


def faculty_scoped_required(view_func):
    """
    Ensures Faculty Admins and Lecturers access only data within their bound faculty.
    Central Admins bypass faculty scoping.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('/login/')

        # Central Admins hold university-wide scope
        if request.user.role == 'CENTRAL_ADMIN':
            return view_func(request, *args, **kwargs)

        # Faculty Admin & Lecturer scoping check
        target_faculty_id = kwargs.get('faculty_id') or request.GET.get('faculty_id') or request.POST.get('faculty_id')
        if target_faculty_id:
            try:
                target_faculty_id = int(target_faculty_id)
            except (ValueError, TypeError):
                target_faculty_id = None

        if target_faculty_id and request.user.faculty_id:
            if request.user.faculty_id != target_faculty_id:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.path.startswith('/api/'):
                    return JsonResponse({'error': 'Cross-faculty access forbidden.'}, status=403)
                messages.error(request, "Forbidden: Cross-faculty resource access is prohibited.")
                raise PermissionDenied("Cross-faculty boundary violation.")

        return view_func(request, *args, **kwargs)
    return _wrapped_view
