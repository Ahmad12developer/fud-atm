"""
Root-level alias package for core permissions.
"""
from timetable.core.permissions import role_required, faculty_scoped_required

__all__ = ['role_required', 'faculty_scoped_required']
