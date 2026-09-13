"""
Pre-Commit Validation Engine for Federal University Dutse (FUD) ATMS.
Evaluates multi-entity scheduling invariants against active timetables across FUD databases.
"""
from typing import Tuple, Optional
from django.db.models import Q
from ..models import (
    Course, Lecturer, Venue, TimeSlot, Allocation,
    LecturerAvailability, Timetable, AcademicSession
)


def validate_slot_allocation(
    *,
    course: Course,
    lecturer: Lecturer,
    venue: Venue,
    day: int,
    slot_id: int,
    session_id: int,
    semester: int,
    exclude_allocation_id: Optional[int] = None
) -> Tuple[bool, str]:
    """
    Validates whether an allocation violates hard institutional constraints across:
    1. Venue collision (including shared central venues across all faculties)
    2. Lecturer simultaneous double-booking
    3. Student cohort collision (same department and level at the same time slot)
    4. Venue capacity adequacy
    5. Lecturer availability preference
    6. Institutional religious/cultural blackout (Friday Juma'at 12:30 PM - 2:00 PM)

    Returns:
        (is_valid: bool, reason: str)
    """
    # 0. Retrieve Slot Object
    try:
        slot = TimeSlot.objects.get(id=slot_id)
    except TimeSlot.DoesNotExist:
        return False, f"TimeSlot ID {slot_id} does not exist."

    # 1. Friday Juma'at Prayer Hard Lockout (12:30 PM - 2:00 PM)
    # Day 4 is Friday. If slot starts between 12:00 and 14:00 or overlaps 12:30-14:00
    if day == 4:
        # Check slot time overlap with 12:30 - 14:00
        from datetime import time
        prayer_start = time(12, 30)
        prayer_end = time(14, 0)
        if (slot.start_time < prayer_end and slot.end_time > prayer_start):
            return False, "HARD CONFLICT: Senate policy strictly prohibits scheduling lectures during Friday Juma'at prayer (12:30 PM - 2:00 PM)."

    # 2. Venue Capacity Verification
    if venue.capacity < course.expected_capacity:
        return False, (
            f"CAPACITY DEFICIT: Venue {venue.code} capacity ({venue.capacity} seats) is insufficient "
            f"for course {course.code} expected cohort size ({course.expected_capacity} students)."
        )

    # 3. Active Allocation Scope (Active timetables in this session/semester)
    active_timetables = Timetable.objects.filter(
        session_id=session_id,
        semester=semester,
        status__in=[Timetable.Status.DRAFT, Timetable.Status.FACULTY_APPROVED, Timetable.Status.PUBLISHED]
    )

    alloc_query = Allocation.objects.filter(
        timetable__in=active_timetables,
        day_of_week=day,
        slot=slot
    )

    if exclude_allocation_id:
        alloc_query = alloc_query.exclude(id=exclude_allocation_id)

    # 4. Venue Collision (Ensures no other course is scheduled in this venue at this time)
    venue_clash = alloc_query.filter(venue=venue).select_related('course', 'timetable__faculty').first()
    if venue_clash:
        return False, (
            f"VENUE COLLISION: Venue {venue.code} ({venue.name}) is already occupied on "
            f"{venue_clash.get_day_of_week_display()} at {slot.label} by {venue_clash.course.code} "
            f"({venue_clash.timetable.faculty.code})."
        )

    # 5. Lecturer Overlapping Assignment (Lecturer cannot teach two courses simultaneously)
    lecturer_clash = alloc_query.filter(lecturer=lecturer).select_related('course', 'venue').first()
    if lecturer_clash:
        return False, (
            f"LECTURER CLASH: {lecturer.user.get_full_name()} is already scheduled to teach "
            f"{lecturer_clash.course.code} at {slot.label} in {lecturer_clash.venue.code}."
        )

    # 6. Student Cohort Collision (Department + Level cannot have two lectures at the same time)
    cohort_clash = alloc_query.filter(
        course__department=course.department,
        course__level=course.level
    ).select_related('course', 'venue').first()
    if cohort_clash:
        return False, (
            f"STUDENT COHORT CLASH: {course.department.code} {course.level}L students are already "
            f"scheduled for {cohort_clash.course.code} in {cohort_clash.venue.code} at this time slot."
        )

    # 7. Lecturer Availability Compliance
    try:
        avail = LecturerAvailability.objects.get(lecturer=lecturer, day_of_week=day, slot=slot)
        if not avail.is_available:
            return False, (
                f"LECTURER UNAVAILABILITY: {lecturer.user.get_full_name()} marked "
                f"{avail.get_day_of_week_display()} {slot.label} as unavailable."
            )
    except LecturerAvailability.DoesNotExist:
        # If no explicit record, default to available
        pass

    return True, "No conflicts detected. Allocation satisfies all institutional hard constraints."
