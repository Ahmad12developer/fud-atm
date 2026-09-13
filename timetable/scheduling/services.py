"""
Pessimistic Locking & Atomic Allocation Services for Federal University Dutse (FUD) ATMS.
Eliminates Time-of-Check to Time-of-Use (TOCTOU) race conditions and Broken Object Level Authorization (BOLA).
"""
from typing import Optional, Dict, Any
from datetime import time
from django.db import transaction
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone

from timetable.models import (
    User, Timetable, Allocation, Venue, TimeSlot, Course, Lecturer
)
from timetable.audit import log_audit, get_client_ip


def commit_slot_override(
    *,
    request,
    timetable_id: int,
    allocation_id: int,
    new_venue_id: int,
    new_slot_id: int,
    new_day_of_week: int,
    justification: str
) -> Allocation:
    """
    Atomically commits a timetable slot override using row-level pessimistic database locking.

    Defense Layers:
    1. Transaction Isolation: Entire check-and-persist block executes inside transaction.atomic().
    2. Row-Level Locks: select_for_update() on Timetable, Allocation, and Venue prevents concurrent double-bookings.
    3. Multi-Tenant Authorization (Anti-BOLA): Verifies FACULTY_ADMIN cannot mutate foreign faculty timetables.
    4. Comprehensive Collision Invariants:
       - Friday Juma'at religious prayer blackout (12:30 PM - 2:00 PM)
       - Target room capacity check (venue.capacity >= course.expected_capacity)
       - Inter-faculty venue double-booking check across all active timetables
       - Lecturer cross-faculty simultaneous assignment check
       - Student cohort collision check (same Department + Level)
    5. Immutable SSDLC Audit Trail: Logs previous state, new state, user ID, client IP, and justification.

    Raises:
        ValidationError: If any scheduling invariant or capacity check fails.
        PermissionDenied: If a cross-faculty BOLA violation is attempted.
    """
    justification_clean = (justification or '').strip()
    if not justification_clean:
        raise ValidationError("Administrative justification is strictly required for slot overrides.")

    with transaction.atomic():
        # 1. Acquire row-level lock on the target timetable
        try:
            timetable = Timetable.objects.select_for_update().get(pk=timetable_id)
        except Timetable.DoesNotExist:
            raise ValidationError(f"Timetable ID {timetable_id} does not exist.")

        # 2. Anti-BOLA Authorization Guard:
        # FACULTY_ADMIN can only mutate timetables assigned to their own faculty
        if request.user.role == User.Role.FACULTY_ADMIN:
            if request.user.faculty_id != timetable.faculty_id:
                log_audit(
                    action="BOLA_BLOCKED",
                    entity_type="TIMETABLE",
                    entity_id=str(timetable_id),
                    user=request.user,
                    request=request,
                    details={
                        'user_faculty_id': request.user.faculty_id,
                        'target_faculty_id': timetable.faculty_id,
                        'attempted_override': True
                    }
                )
                raise PermissionDenied("Cross-faculty override forbidden (BOLA prevention).")

        # 3. Acquire row-level lock on the mutable allocation
        try:
            allocation = Allocation.objects.select_for_update().get(pk=allocation_id, timetable=timetable)
        except Allocation.DoesNotExist:
            raise ValidationError(f"Allocation ID {allocation_id} does not exist on timetable ID {timetable_id}.")

        # 4. Acquire row-level lock on target venue (must be active)
        try:
            target_venue = Venue.objects.select_for_update().get(pk=new_venue_id, is_active=True)
        except Venue.DoesNotExist:
            raise ValidationError(f"Active venue ID {new_venue_id} does not exist or is deactivated.")

        # 5. Retrieve target time slot
        try:
            target_slot = TimeSlot.objects.get(pk=new_slot_id)
        except TimeSlot.DoesNotExist:
            raise ValidationError(f"TimeSlot ID {new_slot_id} does not exist.")

        course = allocation.course
        lecturer = allocation.lecturer
        session = timetable.session
        semester = timetable.semester

        # 6. Enforce Friday Juma'at Prayer Hard Lockout (12:30 PM - 2:00 PM)
        # Day 4 is Friday
        if new_day_of_week == 4:
            prayer_start = time(12, 30)
            prayer_end = time(14, 0)
            if target_slot.start_time < prayer_end and target_slot.end_time > prayer_start:
                raise ValidationError(
                    "HARD CONFLICT: Senate policy strictly prohibits scheduling lectures during Friday Juma'at prayer (12:30 PM - 2:00 PM)."
                )

        # 7. Enforce Room Capacity
        if target_venue.capacity < course.expected_capacity:
            raise ValidationError(
                f"CAPACITY DEFICIT: Venue {target_venue.code} capacity ({target_venue.capacity} seats) is insufficient "
                f"for course {course.code} expected cohort size ({course.expected_capacity} students)."
            )

        # 8. Collision Checks across all active records in the same Academic Session and Semester
        active_timetables = Timetable.objects.filter(
            session=session,
            semester=semester
        )

        # (a) Venue collision across all approved/published timetables and active draft
        venue_clashes = Allocation.objects.filter(
            timetable__in=active_timetables,
            day_of_week=new_day_of_week,
            slot=target_slot,
            venue=target_venue
        ).exclude(pk=allocation.pk)

        if venue_clashes.exists():
            clash = venue_clashes.select_related('course', 'timetable__faculty').first()
            fac_name = clash.timetable.faculty.name if (clash.timetable and clash.timetable.faculty) else "University Central"
            raise ValidationError(
                f"VENUE COLLISION: Venue {target_venue.code} is already allocated to {clash.course.code} "
                f"({fac_name}) on this day and time slot."
            )

        # (b) Lecturer overlapping allocations across any faculty
        if lecturer:
            lecturer_clashes = Allocation.objects.filter(
                timetable__in=active_timetables,
                day_of_week=new_day_of_week,
                slot=target_slot,
                lecturer=lecturer
            ).exclude(pk=allocation.pk)

            if lecturer_clashes.exists():
                clash = lecturer_clashes.select_related('course').first()
                raise ValidationError(
                    f"STAFF DOUBLE-BOOKING: Lecturer {lecturer.user.get_full_name()} is already assigned to "
                    f"{clash.course.code} on this day and time slot."
                )

        # (c) Student Cohort collision (same Department + Level assigned to overlapping lectures)
        cohort_clashes = Allocation.objects.filter(
            timetable__in=active_timetables,
            day_of_week=new_day_of_week,
            slot=target_slot,
            course__department=course.department,
            course__level=course.level
        ).exclude(pk=allocation.pk)

        if cohort_clashes.exists():
            clash = cohort_clashes.select_related('course').first()
            raise ValidationError(
                f"STUDENT COHORT CLASH: {course.department.code} {course.level}L students are already scheduled "
                f"for {clash.course.code} on this day and time slot."
            )

        # 9. Capture Previous State for Immutable Audit
        previous_state = {
            'allocation_id': allocation.id,
            'timetable_id': timetable.id,
            'course_code': course.code,
            'venue_code': allocation.venue.code if allocation.venue else None,
            'slot_label': allocation.slot.label if allocation.slot else None,
            'slot_id': allocation.slot_id,
            'day_of_week': allocation.day_of_week
        }

        # 10. Persist State Changes with explicit update_fields
        allocation.venue = target_venue
        allocation.slot = target_slot
        allocation.day_of_week = new_day_of_week
        allocation.save(update_fields=['venue', 'slot', 'day_of_week'])

        new_state = {
            'allocation_id': allocation.id,
            'timetable_id': timetable.id,
            'course_code': course.code,
            'venue_code': target_venue.code,
            'slot_label': target_slot.label,
            'slot_id': target_slot.id,
            'day_of_week': new_day_of_week
        }

        # 11. Write Immutable SSDLC Audit Log Entry
        client_ip = get_client_ip(request)
        log_audit(
            action="MANUAL_OVERRIDE",
            entity_type="ALLOCATION",
            entity_id=str(allocation.id),
            user=request.user,
            request=request,
            details={
                'previous_state': previous_state,
                'new_state': new_state,
                'user_id': request.user.institutional_id,
                'client_ip': client_ip,
                'justification': justification_clean
            }
        )

        return allocation
