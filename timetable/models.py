"""
Core Domain Models for Federal University Dutse (FUD) ATMS.
Enforces relational integrity, SSDLC principles, and database-level invariants.
"""
from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.core.exceptions import ValidationError
from django.utils import timezone


# ==============================================================================
# 1. FACULTY & DEPARTMENT SCHEMAS
# ==============================================================================

class Faculty(models.Model):
    name = models.CharField(max_length=120, unique=True)
    code = models.CharField(max_length=8, unique=True, help_text="e.g. COMP, SCI, AGR")

    class Meta:
        verbose_name_plural = "Faculties"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"


class Department(models.Model):
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=8, help_text="e.g. CSC, SE, CYB")
    faculty = models.ForeignKey(Faculty, on_delete=models.PROTECT, related_name='departments')

    class Meta:
        unique_together = ('faculty', 'code')
        ordering = ['faculty', 'name']

    def __str__(self):
        return f"{self.name} ({self.code}) - {self.faculty.code}"


# ==============================================================================
# 2. CUSTOM USER & RBAC (EXTENDS AbstractUser)
# ==============================================================================

class CustomUserManager(BaseUserManager):
    def create_user(self, institutional_id, password=None, **extra_fields):
        if not institutional_id:
            raise ValueError("The Institutional ID is strictly required.")
        extra_fields.setdefault('username', institutional_id)
        user = self.model(institutional_id=institutional_id, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, institutional_id, password=None, **extra_fields):
        extra_fields.setdefault('role', User.Role.CENTRAL_ADMIN)
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(institutional_id, password, **extra_fields)


class User(AbstractUser):
    class Role(models.TextChoices):
        CENTRAL_ADMIN = 'CENTRAL_ADMIN', 'Central Administrator'
        FACULTY_ADMIN = 'FACULTY_ADMIN', 'Faculty Timetable Officer'
        LECTURER = 'LECTURER', 'Academic Staff / Lecturer'
        STUDENT = 'STUDENT', 'Undergraduate Student'

    LEVEL_CHOICES = [(l, f"{l} Level") for l in (100, 200, 300, 400, 500)]

    institutional_id = models.CharField(max_length=64, unique=True, db_index=True)
    role = models.CharField(max_length=20, choices=Role.choices, db_index=True)
    faculty = models.ForeignKey(Faculty, null=True, blank=True, on_delete=models.PROTECT, related_name='users')
    department = models.ForeignKey(Department, null=True, blank=True, on_delete=models.PROTECT, related_name='users')
    level = models.PositiveSmallIntegerField(null=True, blank=True, choices=LEVEL_CHOICES)

    # Anti-Brute-Force Bookkeeping
    failed_login_count = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    objects = CustomUserManager()

    USERNAME_FIELD = 'institutional_id'
    REQUIRED_FIELDS = ['first_name', 'last_name', 'email']

    def is_locked(self):
        if self.locked_until and self.locked_until > timezone.now():
            return True
        return False

    def clean(self):
        super().clean()
        # Enforce role-to-scope invariants defensively
        if self.role == self.Role.STUDENT:
            if not self.department:
                raise ValidationError({'department': 'Students must belong to an academic Department.'})
            if not self.level:
                raise ValidationError({'level': 'Students must have an assigned undergraduate Level.'})
            if self.department and not self.faculty:
                self.faculty = self.department.faculty

        elif self.role == self.Role.FACULTY_ADMIN:
            if not self.faculty:
                raise ValidationError({'faculty': 'Faculty Admins must be bound to an authorized Faculty.'})
            self.department = None
            self.level = None

        elif self.role == self.Role.CENTRAL_ADMIN:
            # Defensive clearance of scoped domains
            self.faculty = None
            self.department = None
            self.level = None

        elif self.role == self.Role.LECTURER:
            if not self.department:
                raise ValidationError({'department': 'Lecturers must belong to an academic Department.'})
            if self.department and not self.faculty:
                self.faculty = self.department.faculty
            self.level = None

    def save(self, *args, **kwargs):
        self.username = self.institutional_id
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_full_name() or self.username} [{self.role}] ({self.institutional_id})"


# ==============================================================================
# 3. CANONICAL TIMESLOT SCHEMA
# ==============================================================================

class TimeSlot(models.Model):
    index = models.PositiveSmallIntegerField(unique=True, help_text="Order index (1..N)")
    start_time = models.TimeField()
    end_time = models.TimeField()
    label = models.CharField(max_length=32, help_text='e.g. "08:00 - 10:00"')

    class Meta:
        ordering = ['index']

    def clean(self):
        super().clean()
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError({'end_time': 'TimeSlot start time must strictly precede end time.'})

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.label


# ==============================================================================
# 4. ACADEMIC ENTITIES (COURSE, VENUE, LECTURER, AVAILABILITY)
# ==============================================================================

class Course(models.Model):
    SEMESTER_CHOICES = [
        (1, 'Harmattan (1st) Semester'),
        (2, 'Rain (2nd) Semester')
    ]
    LEVEL_CHOICES = [(l, f"{l}L") for l in (100, 200, 300, 400, 500)]

    code = models.CharField(max_length=16, unique=True, help_text="e.g. CSC 301")
    title = models.CharField(max_length=200)
    credit_units = models.PositiveSmallIntegerField(default=3)
    contact_hours = models.PositiveSmallIntegerField(default=2)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name='courses')
    level = models.PositiveSmallIntegerField(choices=LEVEL_CHOICES)
    semester = models.PositiveSmallIntegerField(choices=SEMESTER_CHOICES, default=1)
    expected_capacity = models.PositiveIntegerField(help_text="Expected student enrollment count")

    class Meta:
        ordering = ['level', 'code']

    def __str__(self):
        return f"{self.code} - {self.title} ({self.credit_units} CU)"


class Venue(models.Model):
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=16, unique=True, help_text="e.g. LT-AG, TWIN-A")
    capacity = models.PositiveIntegerField()
    faculty = models.ForeignKey(
        Faculty,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='venues',
        help_text="Null denotes a shared central university venue (e.g. Abubakar Gimba Theatre)"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-capacity', 'name']

    def __str__(self):
        scope = self.faculty.code if self.faculty else "CENTRAL_SHARED"
        return f"{self.name} ({self.code}, Cap: {self.capacity}) [{scope}]"


class Lecturer(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, limit_choices_to={'role': User.Role.LECTURER}, related_name='lecturer_profile')
    staff_id = models.CharField(max_length=32, unique=True)
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name='lecturers')
    max_hours_per_week = models.PositiveSmallIntegerField(default=12)

    class Meta:
        ordering = ['user__first_name', 'user__last_name']

    def __str__(self):
        return f"{self.user.get_full_name()} ({self.staff_id}) - {self.department.code}"


class LecturerAvailability(models.Model):
    DAY_CHOICES = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
    ]

    lecturer = models.ForeignKey(Lecturer, on_delete=models.CASCADE, related_name='availabilities')
    day_of_week = models.PositiveSmallIntegerField(choices=DAY_CHOICES)
    slot = models.ForeignKey(TimeSlot, on_delete=models.CASCADE)
    is_available = models.BooleanField(default=True)

    class Meta:
        unique_together = ('lecturer', 'day_of_week', 'slot')
        ordering = ['lecturer', 'day_of_week', 'slot__index']

    def __str__(self):
        state = "Available" if self.is_available else "Unavailable"
        return f"{self.lecturer.staff_id} - {self.get_day_of_week_display()} {self.slot.label} ({state})"


# ==============================================================================
# 5. TIMETABLE, ALLOCATION & CHANGE REQUESTS
# ==============================================================================

class AcademicSession(models.Model):
    name = models.CharField(max_length=16, unique=True, help_text="e.g. 2025/2026")
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ['-name']

    def __str__(self):
        return f"{self.name}{' (Current)' if self.is_current else ''}"


class Timetable(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft / In Preparation'
        FACULTY_APPROVED = 'FACULTY_APPROVED', 'Faculty Approved'
        PUBLISHED = 'PUBLISHED', 'Formally Published'

    SEMESTER_CHOICES = [
        (1, 'Harmattan (1st) Semester'),
        (2, 'Rain (2nd) Semester')
    ]

    session = models.ForeignKey(AcademicSession, on_delete=models.PROTECT, related_name='timetables')
    semester = models.PositiveSmallIntegerField(choices=SEMESTER_CHOICES, default=1)
    faculty = models.ForeignKey(Faculty, on_delete=models.PROTECT, related_name='timetables')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('session', 'semester', 'faculty')
        ordering = ['-session', 'faculty']

    def __str__(self):
        return f"{self.faculty.code} - {self.session.name} Sem {self.semester} [{self.status}]"


class Allocation(models.Model):
    DAY_CHOICES = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
    ]

    timetable = models.ForeignKey(Timetable, on_delete=models.CASCADE, related_name='allocations')
    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name='allocations')
    lecturer = models.ForeignKey(Lecturer, on_delete=models.PROTECT, related_name='allocations')
    venue = models.ForeignKey(Venue, on_delete=models.PROTECT, related_name='allocations')
    day_of_week = models.PositiveSmallIntegerField(choices=DAY_CHOICES)
    slot = models.ForeignKey(TimeSlot, on_delete=models.PROTECT)

    class Meta:
        indexes = [
            models.Index(fields=['timetable', 'day_of_week', 'slot'], name='alloc_tt_day_slot_idx'),
            models.Index(fields=['venue', 'day_of_week', 'slot'], name='alloc_venue_day_slot_idx'),
            models.Index(fields=['lecturer', 'day_of_week', 'slot'], name='alloc_lec_day_slot_idx'),
        ]
        ordering = ['day_of_week', 'slot__index']

    def __str__(self):
        return f"{self.course.code} @ {self.venue.code} ({self.get_day_of_week_display()} {self.slot.label})"


class ChangeRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending Review'
        APPROVED = 'APPROVED', 'Approved & Rescheduled'
        REJECTED = 'REJECTED', 'Rejected'

    DAY_CHOICES = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
    ]

    lecturer = models.ForeignKey(Lecturer, on_delete=models.CASCADE, related_name='change_requests')
    allocation = models.ForeignKey(Allocation, on_delete=models.CASCADE, related_name='change_requests')
    requested_day = models.PositiveSmallIntegerField(choices=DAY_CHOICES, null=True, blank=True)
    requested_venue = models.ForeignKey(Venue, null=True, blank=True, on_delete=models.SET_NULL)
    requested_slot = models.ForeignKey(TimeSlot, null=True, blank=True, on_delete=models.SET_NULL)
    reason = models.TextField(max_length=2000)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    admin_feedback = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"REQ-{self.id}: {self.allocation.course.code} by {self.lecturer.staff_id} [{self.status}]"


# ==============================================================================
# 6. AUDIT LOG & COMPLIANCE
# ==============================================================================

class AuditLog(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='audit_entries')
    action = models.CharField(max_length=64, db_index=True)
    entity_type = models.CharField(max_length=64)
    entity_id = models.CharField(max_length=64)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        actor = self.user.institutional_id if self.user else "ANONYMOUS/SYSTEM"
        return f"{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')} - {actor} - {self.action} on {self.entity_type} {self.entity_id}"


# ==============================================================================
# 7. SUPPORTING MODELS (COMMUNICATIONS, OPTIMIZATION & INCIDENTS)
# ==============================================================================

class InterAdminMessage(models.Model):
    PRIORITY_CHOICES = [
        ('ROUTINE', 'Routine Directive'),
        ('URGENT', 'Urgent Action Required')
    ]
    sender = models.ForeignKey(User, on_delete=models.PROTECT, related_name='sent_messages')
    faculty = models.ForeignKey(Faculty, on_delete=models.PROTECT, related_name='admin_messages')
    priority = models.CharField(max_length=16, choices=PRIORITY_CHOICES, default='ROUTINE')
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']


class OptimizationSetting(models.Model):
    weight_student_gap = models.PositiveSmallIntegerField(default=85)
    weight_lecturer_pref = models.PositiveSmallIntegerField(default=90)
    weight_travel_dist = models.PositiveSmallIntegerField(default=75)
    weight_load_dist = models.PositiveSmallIntegerField(default=80)
    friday_hard_lock = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)


class IncidentReport(models.Model):
    CATEGORY_CHOICES = [
        ('VENUE_DOUBLE_BOOKED', 'Venue Double-Booked'),
        ('HALL_LOCKED', 'Lecture Theatre Locked / Inaccessible'),
        ('CAPACITY_OVERFLOW', 'Severe Capacity Overflow'),
        ('SCHEDULE_OVERLAP', 'Direct Schedule Overlap'),
        ('LECTURER_ABSENT', 'Lecturer Did Not Appear')
    ]
    reported_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='incident_reports')
    category = models.CharField(max_length=32, choices=CATEGORY_CHOICES)
    course_code = models.CharField(max_length=16)
    venue = models.CharField(max_length=64)
    day = models.CharField(max_length=16)
    time_slot = models.CharField(max_length=32)
    description = models.TextField(max_length=2000)
    resolved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
