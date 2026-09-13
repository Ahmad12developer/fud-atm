"""
Global context processor for Federal University Dutse (FUD) ATMS.
Supplies institutional identity, academic session, and authenticated user role scope.
"""
from .models import AcademicSession


def fud_context(request):
    current_sess = AcademicSession.objects.filter(is_current=True).first()
    session_name = current_sess.name if current_sess else "2025/2026 Academic Session"

    user_role = getattr(request.user, 'role', 'ANONYMOUS') if request.user.is_authenticated else 'ANONYMOUS'

    return {
        'INSTITUTION_NAME': 'Federal University Dutse',
        'INSTITUTION_SHORT': 'FUD',
        'INSTITUTION_STATE': 'Jigawa State, Nigeria',
        'INSTITUTION_MOTTO': 'Knowledge, Excellence & Service',
        'ACADEMIC_SESSION': session_name,
        'ACADEMIC_SEMESTER': 'Harmattan (1st) Semester',
        'user_role': user_role,
        'user': request.user,
    }
