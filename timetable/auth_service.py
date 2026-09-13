"""
Deterministic Authentication & Defense-in-Depth Service for FUD ATMS.
OWASP Top 10 mitigations: Constant-time authentication, anti-enumeration dummy hash,
sliding window IP rate limiting, 15-minute account lockout, and uniform error messaging.
"""
import re
from datetime import timedelta
from django.core.cache import cache
from django.contrib.auth import authenticate, login
from django.contrib.auth.hashers import check_password
from django.utils import timezone
from .models import User
from .audit import log_audit, get_client_ip


# Security Constraints
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_DURATION_MINUTES = 15
MAX_IP_ATTEMPTS_PER_MIN = 20
RATE_LIMIT_WINDOW_SECONDS = 60

# Pre-computed authentic PBKDF2 hash (1,500,000 rounds) matching standard Django 6 cost factor
# Ensures identical response latency when validating non-existent users or locked accounts
DUMMY_PBKDF2_HASH = 'pbkdf2_sha256$1500000$ObdlmPFfzS7sCO6b4AnjZu$pIJYW627KcpJVrxJL5VEtXJb6a9Gyymuh/yB4jmFmZs='

# Institutional ID format integrity pattern
INSTITUTIONAL_ID_REGEX = re.compile(
    r'^(?P<fac>[A-Z]{2,4})/(?P<dept>[A-Z]{2,4})/(?P<year>\d{2,4})/(?P<reg>\d+)$'
)

# Strict Uniform Error Message to prevent user enumeration
UNIFORM_AUTH_ERROR = "Invalid credentials."


class AuthenticationResult:
    def __init__(self, success: bool, message: str, user: User = None, error_code: str = None):
        self.success = success
        self.message = message
        self.user = user
        self.error_code = error_code


def check_ip_rate_limit(ip_address: str) -> bool:
    """
    Sliding window IP throttle: enforces a hard cap of 20 attempts per 60-second window.
    Maintained in Django's cache layer.
    """
    cache_key = f"login_ip_sliding_{ip_address}"
    now = timezone.now().timestamp()
    attempts = cache.get(cache_key, [])
    # Filter attempts strictly within the sliding window
    attempts = [ts for ts in attempts if now - ts < RATE_LIMIT_WINDOW_SECONDS]
    if len(attempts) >= MAX_IP_ATTEMPTS_PER_MIN:
        return False
    attempts.append(now)
    cache.set(cache_key, attempts, timeout=RATE_LIMIT_WINDOW_SECONDS + 10)
    return True


def verify_institutional_id_format(institutional_id: str) -> dict:
    """
    Integrity regex check for Institutional ID schema.
    Used solely as an integrity cross-check; the database remains the single source of truth.
    """
    match = INSTITUTIONAL_ID_REGEX.match(institutional_id)
    if match:
        return match.groupdict()
    return {}


def authenticate_user(request, institutional_id: str, password: str) -> AuthenticationResult:
    """
    Production-grade login verification with constant-time defense and zero-enumeration protection.

    Defense Layers:
    1. IP-Based Sliding Window Throttle: Caps attempts to 20/min per IP.
    2. Anti-Enumeration Dummy Hashing: Computes PBKDF2 hash on missing/locked accounts.
    3. 15-Minute Account Lockout: Enforced upon 5 consecutive failed attempts.
    4. Constant-Time Authentication: Delegates to Django's constant-time authenticate().
    5. Uniform Error Messaging: Returns "Invalid credentials." for all failures.
    6. Credential Sanitization: Strips password and sensitive details from audit logs.
    """
    clean_id = (institutional_id or '').strip().upper()
    password = password or ''
    client_ip = get_client_ip(request)

    # 1. Sliding Window IP Rate Limiting
    if not check_ip_rate_limit(client_ip):
        log_audit(
            action="LOGIN_THROTTLED",
            entity_type="IP_ADDRESS",
            entity_id=client_ip,
            request=request,
            details={'client_ip': client_ip, 'attempted_id': clean_id}
        )
        return AuthenticationResult(
            success=False,
            message="Too many login attempts from this network. Please wait before trying again.",
            error_code="THROTTLED"
        )

    # Validate input presence with constant-time dummy hashing on empty inputs
    if not clean_id or not password:
        check_password(password or 'empty', DUMMY_PBKDF2_HASH)
        return AuthenticationResult(
            success=False,
            message=UNIFORM_AUTH_ERROR,
            error_code="MISSING_CREDENTIALS"
        )

    # 2. Check Database Record for Lockout State
    try:
        user_candidate = User.objects.get(institutional_id=clean_id)
    except User.DoesNotExist:
        user_candidate = None

    # Anti-Enumeration Branch: If user does not exist, compute dummy hash to equalize timing
    if user_candidate is None:
        check_password(password, DUMMY_PBKDF2_HASH)
        log_audit(
            action="LOGIN_FAILED",
            entity_type="USER",
            entity_id=clean_id,
            request=request,
            details={'attempted_id': clean_id, 'client_ip': client_ip, 'reason': 'nonexistent_user'}
        )
        return AuthenticationResult(
            success=False,
            message=UNIFORM_AUTH_ERROR,
            error_code="INVALID_CREDENTIALS"
        )

    # Lockout Branch: If user is locked, execute dummy hash to equalize timing before returning
    if user_candidate.is_locked():
        check_password(password, DUMMY_PBKDF2_HASH)
        remaining = int((user_candidate.locked_until - timezone.now()).total_seconds() // 60) + 1
        log_audit(
            action="LOGIN_LOCKED",
            entity_type="USER",
            entity_id=clean_id,
            user=user_candidate,
            request=request,
            details={'failed_attempts': user_candidate.failed_login_count, 'minutes_remaining': remaining}
        )
        return AuthenticationResult(
            success=False,
            message=UNIFORM_AUTH_ERROR,
            error_code="ACCOUNT_LOCKED"
        )

    # 3. Constant-Time Authentication via Django backend
    user = authenticate(request, username=clean_id, password=password)

    if user is None:
        # Increment failed login counter
        user_candidate.failed_login_count += 1
        if user_candidate.failed_login_count >= MAX_FAILED_ATTEMPTS:
            user_candidate.locked_until = timezone.now() + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
            user_candidate.save(update_fields=['failed_login_count', 'locked_until'])
            log_audit(
                action="LOGIN_LOCKED",
                entity_type="USER",
                entity_id=clean_id,
                user=user_candidate,
                request=request,
                details={'failed_attempts': user_candidate.failed_login_count, 'lockout_minutes': LOCKOUT_DURATION_MINUTES}
            )
            return AuthenticationResult(
                success=False,
                message=UNIFORM_AUTH_ERROR,
                error_code="ACCOUNT_LOCKED"
            )
        else:
            user_candidate.save(update_fields=['failed_login_count'])

        log_audit(
            action="LOGIN_FAILED",
            entity_type="USER",
            entity_id=clean_id,
            request=request,
            details={'attempted_id': clean_id, 'client_ip': client_ip, 'failed_count': user_candidate.failed_login_count}
        )
        return AuthenticationResult(
            success=False,
            message=UNIFORM_AUTH_ERROR,
            error_code="INVALID_CREDENTIALS"
        )

    # 4. Successful Authentication: Reset Brute-Force State strictly
    if user.failed_login_count > 0 or user.locked_until is not None:
        user.failed_login_count = 0
        user.locked_until = None
        user.save(update_fields=['failed_login_count', 'locked_until'])

    # 5. Execute Session Login
    login(request, user)

    # 6. Immutable Audit Trail (stripping credentials)
    log_audit(
        action="LOGIN_SUCCESS",
        entity_type="USER",
        entity_id=user.institutional_id,
        user=user,
        request=request,
        details={'role': user.role, 'client_ip': client_ip}
    )

    return AuthenticationResult(
        success=True,
        message=f"Authentication successful. Welcome, {user.get_full_name() or user.institutional_id}.",
        user=user
    )
