"""
Root-level alias package for authentication service.
"""
from timetable.auth_service import (
    authenticate_user,
    check_ip_rate_limit,
    verify_institutional_id_format,
    AuthenticationResult,
    DUMMY_PBKDF2_HASH,
    UNIFORM_AUTH_ERROR
)

__all__ = [
    'authenticate_user',
    'check_ip_rate_limit',
    'verify_institutional_id_format',
    'AuthenticationResult',
    'DUMMY_PBKDF2_HASH',
    'UNIFORM_AUTH_ERROR'
]
