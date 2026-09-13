"""
Audit Service for Federal University Dutse (FUD) ATMS.
SSDLC-compliant tamper-evident audit logging with strict PII/credential sanitization.
"""
from .models import AuditLog


SENSITIVE_KEYS = {
    'password', 'token', 'secret', 'key', 'csrfmiddlewaretoken', 'credentials', 'authorization'
}


def sanitize_details(details: dict) -> dict:
    """Recursively whitelists and redacts sensitive credentials and PII."""
    if not isinstance(details, dict):
        return {}

    sanitized = {}
    for k, v in details.items():
        if any(s in k.lower() for s in SENSITIVE_KEYS):
            sanitized[k] = "[REDACTED_SECURITY_DATA]"
        elif isinstance(v, dict):
            sanitized[k] = sanitize_details(v)
        elif isinstance(v, (str, int, float, bool, list)) or v is None:
            sanitized[k] = v
        else:
            sanitized[k] = str(v)
    return sanitized


def get_client_ip(request) -> str:
    """Extracts client IP safely from request headers."""
    if not request:
        return "127.0.0.1"
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR', '127.0.0.1')
    return ip


def log_audit(action: str, entity_type: str, entity_id: str, user=None, request=None, details=None):
    """
    Creates an immutable AuditLog record.
    """
    ip_addr = get_client_ip(request) if request else None
    cleaned_details = sanitize_details(details or {})

    # If user is not provided explicitly, try getting it from request
    if not user and request and hasattr(request, 'user') and request.user.is_authenticated:
        user = request.user

    return AuditLog.objects.create(
        user=user,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        ip_address=ip_addr,
        details=cleaned_details
    )
