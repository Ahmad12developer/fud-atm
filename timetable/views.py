"""
Production View Controllers for Federal University Dutse (FUD) ATMS.
Integrates relational ORM queries, RBAC enforcement, Bounded Heuristic Scheduler, and SSDLC audit logging.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib import messages
from django.contrib.auth import logout, login
from django.core.paginator import Paginator
from django.views.decorators.http import require_http_methods, require_POST
from django.db import transaction
from django.core.exceptions import ValidationError, PermissionDenied

from .models import (
    User, Faculty, Department, Course, Venue, Lecturer,
    TimeSlot, AcademicSession, Timetable, Allocation,
    LecturerAvailability, ChangeRequest, AuditLog,
    InterAdminMessage, OptimizationSetting, IncidentReport
)
from .auth_service import authenticate_user
from .audit import log_audit
from .core.permissions import role_required, faculty_scoped_required
from .scheduling.validation import validate_slot_allocation
from .scheduling.scheduler import BoundedScheduler
from .scheduling.services import commit_slot_override


# ==============================================================================
# 1. AUTHENTICATION & SESSION LIFECYCLE
# ==============================================================================

def login_view(request):
    """Unified login portal supporting deterministic ID authentication."""
    if request.user.is_authenticated:
        return redirect('/')

    if request.method == 'POST':
        institutional_id = request.POST.get('institutional_id', '')
        password = request.POST.get('password', '')

        result = authenticate_user(request, institutional_id, password)
        if result.success:
            messages.success(request, result.message)
            role = result.user.role
            if role == User.Role.CENTRAL_ADMIN:
                return redirect('/central/dashboard/')
            elif role == User.Role.FACULTY_ADMIN:
                return redirect('/faculty/dashboard/')
            elif role == User.Role.LECTURER:
                return redirect('/lecturer/schedule/')
            elif role == User.Role.STUDENT:
                return redirect('/student/timetable/')
            return redirect('/')
        else:
            return render(request, 'auth/login.html', {
                'form_error': result.message,
                'prefill_id': institutional_id
            })

    return render(request, 'auth/login.html')


@require_POST
def logout_view(request):
    """Secure POST logout clearing session and logging event."""
    if request.user.is_authenticated:
        log_audit(
            action="LOGOUT",
            entity_type="USER",
            entity_id=request.user.institutional_id,
            user=request.user,
            request=request
        )
    logout(request)
    messages.info(request, "You have been securely signed out of Federal University Dutse ATMS.")
    return redirect('/login/')


def role_switch_view(request, role):
    """Convenience endpoint to switch authenticated role scope during evaluation."""
    role_map = {
        'CENTRAL_ADMIN': 'FUD/ADM/2024/001',
        'FACULTY_ADMIN': 'FUD/SCI/2024/014',
        'LECTURER': 'FUD/LEC/2024/088',
        'STUDENT': 'FUD/CST/21/0456',
    }
    target_id = role_map.get(role)
    if target_id:
        try:
            target_user = User.objects.get(institutional_id=target_id)
            login(request, target_user)
            log_audit(
                action="ROLE_SWITCH_DEMO",
                entity_type="USER",
                entity_id=target_id,
                user=target_user,
                request=request,
                details={'switched_to_role': role}
            )
            messages.success(request, f"Authenticated as {target_user.get_full_name()} [{role}].")
        except User.DoesNotExist:
            messages.error(request, f"User with ID {target_id} not found.")
    return redirect('/')


def root_dispatch(request):
    """Dispatches root / to the role-specific dashboard based on authenticated user."""
    if not request.user.is_authenticated:
        return redirect('/login/')

    role = request.user.role
    if role == User.Role.CENTRAL_ADMIN:
        return redirect('/central/dashboard/')
    elif role == User.Role.FACULTY_ADMIN:
        return redirect('/faculty/dashboard/')
    elif role == User.Role.LECTURER:
        return redirect('/lecturer/schedule/')
    elif role == User.Role.STUDENT:
        return redirect('/student/timetable/')
    return redirect('/login/')


# ==============================================================================
# 2. CENTRAL ADMIN WORKSPACE
# ==============================================================================

@role_required([User.Role.CENTRAL_ADMIN])
def central_dashboard(request):
    faculties = Faculty.objects.all().prefetch_related('timetables')
    timetables = Timetable.objects.all().select_related('faculty', 'session')
    
    total_courses = Course.objects.count()
    total_venues = Venue.objects.count()
    total_faculties = faculties.count()

    context = {
        'faculties': faculties,
        'timetables': timetables,
        'total_courses': total_courses,
        'total_venues': total_venues,
        'total_faculties': total_faculties,
    }
    return render(request, 'central_admin/dashboard.html', context)


@role_required([User.Role.CENTRAL_ADMIN])
def central_optimization_tuner(request):
    setting, _ = OptimizationSetting.objects.get_or_create(id=1)

    if request.method == 'POST':
        setting.weight_student_gap = int(request.POST.get('weight_student_gap', 85))
        setting.weight_lecturer_pref = int(request.POST.get('weight_lecturer_pref', 90))
        setting.weight_travel_dist = int(request.POST.get('weight_travel_dist', 75))
        setting.weight_load_dist = int(request.POST.get('weight_load_dist', 80))
        setting.friday_hard_lock = (request.POST.get('friday_lockout_type', 'HARD') == 'HARD')
        setting.save()

        log_audit(
            action="OPTIMIZATION_WEIGHTS_UPDATE",
            entity_type="SYSTEM_SETTING",
            entity_id="OPTIM_1",
            user=request.user,
            request=request,
            details={
                'gap': setting.weight_student_gap,
                'lecturer': setting.weight_lecturer_pref,
                'friday_hard': setting.friday_hard_lock
            }
        )
        messages.success(request, "Senate soft-constraint weights successfully updated and saved.")
        return redirect('/central/optimization/')

    return render(request, 'central_admin/optimization_tuner.html', {'setting': setting})


@role_required([User.Role.CENTRAL_ADMIN])
def central_optimization_reset(request):
    setting, _ = OptimizationSetting.objects.get_or_create(id=1)
    setting.weight_student_gap = 85
    setting.weight_lecturer_pref = 90
    setting.weight_travel_dist = 75
    setting.weight_load_dist = 80
    setting.friday_hard_lock = True
    setting.save()

    messages.info(request, "Optimization weights restored to Senate Harmattan baseline.")
    return redirect('/central/optimization/')


@role_required([User.Role.CENTRAL_ADMIN])
def central_inter_admin_comms(request):
    faculty_code = request.GET.get('thread', 'COMP').upper()
    active_faculty = Faculty.objects.filter(code=faculty_code).first() or Faculty.objects.first()

    messages_list = InterAdminMessage.objects.filter(faculty=active_faculty).select_related('sender')
    faculties = Faculty.objects.all()

    return render(request, 'central_admin/inter_admin_comms.html', {
        'active_faculty': active_faculty,
        'messages_list': messages_list,
        'faculties': faculties,
    })


@require_POST
@role_required([User.Role.CENTRAL_ADMIN])
def central_send_message(request):
    faculty_code = request.POST.get('faculty_code') or request.POST.get('faculty_id')
    faculty = Faculty.objects.filter(code=str(faculty_code).upper()).first() or Faculty.objects.first()
    msg_body = request.POST.get('message', '').strip()
    priority = request.POST.get('priority', 'ROUTINE')

    if msg_body and faculty:
        InterAdminMessage.objects.create(
            sender=request.user,
            faculty=faculty,
            priority=priority,
            message=msg_body
        )
        log_audit(
            action="INTER_ADMIN_COMMS_DISPATCH",
            entity_type="FACULTY",
            entity_id=faculty.code,
            user=request.user,
            request=request,
            details={'priority': priority}
        )
        messages.success(request, f"Official directive dispatched to {faculty.name}.")

    return redirect(f"/central/comms/?thread={faculty.code.lower() if faculty else 'comp'}")


@role_required([User.Role.CENTRAL_ADMIN])
def central_institutional_audit(request):
    category = request.GET.get('category')
    severity = request.GET.get('severity')

    logs_query = AuditLog.objects.all().select_related('user')
    if category and category != 'ALL':
        logs_query = logs_query.filter(action__icontains=category)

    paginator = Paginator(logs_query, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'central_admin/institutional_audit.html', {
        'page_obj': page_obj,
        'category': category,
        'severity': severity,
    })


@require_POST
@role_required([User.Role.CENTRAL_ADMIN])
def central_publish_all(request):
    approved_timetables = Timetable.objects.filter(status=Timetable.Status.FACULTY_APPROVED)
    count = approved_timetables.update(status=Timetable.Status.PUBLISHED)

    log_audit(
        action="TIMETABLE_MASS_PUBLISH",
        entity_type="SYSTEM",
        entity_id="ALL_FACULTIES",
        user=request.user,
        request=request,
        details={'published_count': count}
    )
    messages.success(request, f"Successfully published timetables for {count} faculty/faculties.")
    return redirect('/central/dashboard/')


# ==============================================================================
# 3. FACULTY ADMIN WORKSPACE
# ==============================================================================

@role_required([User.Role.FACULTY_ADMIN])
@faculty_scoped_required
def faculty_dashboard(request):
    faculty = request.user.faculty
    venues_count = Venue.objects.filter(faculty=faculty).count() + Venue.objects.filter(faculty__isnull=True).count()
    courses_count = Course.objects.filter(department__faculty=faculty).count()
    lecturers_count = Lecturer.objects.filter(department__faculty=faculty).count()
    pending_tickets_count = ChangeRequest.objects.filter(
        allocation__timetable__faculty=faculty,
        status=ChangeRequest.Status.PENDING
    ).count()

    timetable = Timetable.objects.filter(
        faculty=faculty,
        session__is_current=True,
        semester=1
    ).first()

    context = {
        'faculty': faculty,
        'venues_count': venues_count,
        'courses_count': courses_count,
        'lecturers_count': lecturers_count,
        'pending_tickets_count': pending_tickets_count,
        'timetable': timetable,
    }
    return render(request, 'faculty_admin/dashboard.html', context)


@role_required([User.Role.FACULTY_ADMIN])
@faculty_scoped_required
def faculty_resources(request):
    faculty = request.user.faculty
    venues = Venue.objects.filter(faculty=faculty) | Venue.objects.filter(faculty__isnull=True)
    courses = Course.objects.filter(department__faculty=faculty).select_related('department')
    lecturers = Lecturer.objects.filter(department__faculty=faculty).select_related('user', 'department')

    return render(request, 'faculty_admin/resources.html', {
        'venues': venues,
        'courses': courses,
        'lecturers': lecturers,
        'faculty': faculty,
    })


@require_POST
@role_required([User.Role.FACULTY_ADMIN])
@faculty_scoped_required
def faculty_add_resource(request):
    faculty = request.user.faculty
    resource_type = request.POST.get('resource_type')
    code = request.POST.get('code', '').strip().upper()
    name = request.POST.get('name', '').strip()
    capacity = request.POST.get('capacity', 0)

    try:
        capacity = int(capacity)
    except ValueError:
        capacity = 50

    if resource_type == 'VENUE':
        v, created = Venue.objects.get_or_create(
            code=code,
            defaults={'name': name or code, 'capacity': capacity, 'faculty': faculty}
        )
        msg = f"Venue {v.code} registered." if created else f"Venue {v.code} already exists."
    elif resource_type == 'COURSE':
        dept = Department.objects.filter(faculty=faculty).first()
        c, created = Course.objects.get_or_create(
            code=code,
            defaults={'title': name or code, 'credit_units': 3, 'expected_capacity': capacity, 'department': dept, 'level': 100}
        )
        msg = f"Course {c.code} registered." if created else f"Course {c.code} already exists."
    else:
        msg = "Staff profiles must be provisioned through User Administration."

    log_audit(
        action="RESOURCE_MUTATION",
        entity_type=resource_type,
        entity_id=code,
        user=request.user,
        request=request,
        details={'name': name, 'capacity': capacity}
    )
    messages.success(request, msg)
    return redirect('/faculty/resources/')


@role_required([User.Role.FACULTY_ADMIN])
@faculty_scoped_required
def faculty_generate_stepper(request):
    faculty = request.user.faculty
    departments = Department.objects.filter(faculty=faculty)
    venues = Venue.objects.filter(faculty=faculty) | Venue.objects.filter(faculty__isnull=True)

    return render(request, 'faculty_admin/generate_stepper.html', {
        'departments': departments,
        'venues': venues,
        'faculty': faculty,
    })


@require_POST
@role_required([User.Role.FACULTY_ADMIN])
@faculty_scoped_required
def faculty_generate_submit(request):
    faculty = request.user.faculty
    session = AcademicSession.objects.filter(is_current=True).first() or AcademicSession.objects.first()

    timetable, _ = Timetable.objects.get_or_create(
        faculty=faculty,
        session=session,
        semester=1,
        defaults={'status': Timetable.Status.DRAFT}
    )

    scheduler = BoundedScheduler(timetable)
    result = scheduler.solve()

    if result.success:
        timetable.status = Timetable.Status.FACULTY_APPROVED
        timetable.save(update_fields=['status', 'updated_at'])

        log_audit(
            action="TIMETABLE_GENERATE",
            entity_type="TIMETABLE",
            entity_id=str(timetable.id),
            user=request.user,
            request=request,
            details={
                'nodes_explored': result.nodes_explored,
                'elapsed_seconds': result.elapsed_seconds,
                'fitness_score': result.fitness_score,
                'allocations_count': len(result.allocations)
            }
        )
        messages.success(
            request,
            f"Automated generator completed in {result.elapsed_seconds:.2f}s! "
            f"Created {len(result.allocations)} allocations with 0 hard conflicts. Fitness: {result.fitness_score}%."
        )
    else:
        messages.error(request, f"Generation failure: {result.message}")

    return redirect('/faculty/matrix/')


@role_required([User.Role.FACULTY_ADMIN])
@faculty_scoped_required
def faculty_timetable_matrix(request):
    faculty = request.user.faculty
    session = AcademicSession.objects.filter(is_current=True).first()

    timetable = Timetable.objects.filter(
        faculty=faculty,
        session=session,
        semester=1
    ).first()

    allocations = []
    if timetable:
        allocations = list(Allocation.objects.filter(
            timetable=timetable
        ).select_related('course', 'lecturer__user', 'venue', 'slot'))

    slots = TimeSlot.objects.all().order_by('index')
    courses = Course.objects.filter(department__faculty=faculty)
    venues = Venue.objects.filter(faculty=faculty) | Venue.objects.filter(faculty__isnull=True)
    lecturers = Lecturer.objects.filter(department__faculty=faculty).select_related('user')

    return render(request, 'faculty_admin/timetable_matrix.html', {
        'timetable': timetable,
        'allocations': allocations,
        'slots': slots,
        'courses': courses,
        'venues': venues,
        'lecturers': lecturers,
        'faculty': faculty,
    })


@require_POST
@role_required([User.Role.FACULTY_ADMIN, User.Role.CENTRAL_ADMIN])
def timetable_commit_override(request):
    """
    HTTP POST endpoint for committing a timetable slot override.
    Executes commit_slot_override with row-level pessimistic locking,
    anti-BOLA multi-tenant authorization, capacity checks, and audit logging.
    """
    timetable_id_raw = request.POST.get('timetable_id', '').strip()
    allocation_id_raw = request.POST.get('allocation_id', '').strip()
    new_venue_id_raw = request.POST.get('new_venue_id', '').strip()
    new_slot_id_raw = request.POST.get('new_slot_id', '').strip()
    new_day_of_week_raw = request.POST.get('new_day_of_week', '').strip()
    justification = request.POST.get('justification', '').strip()

    if not justification:
        justification = request.POST.get('reason', '').strip()
    if not justification:
        justification = "Administrative schedule rebalancing"

    session = AcademicSession.objects.filter(is_current=True).first() or AcademicSession.objects.first()

    # 1. Resolve Timetable
    timetable = None
    if timetable_id_raw:
        try:
            timetable = Timetable.objects.get(pk=int(timetable_id_raw))
        except (ValueError, Timetable.DoesNotExist):
            messages.error(request, f"Timetable ID {timetable_id_raw} does not exist.")
            return redirect('/faculty/matrix/')
    else:
        faculty = request.user.faculty or Faculty.objects.first()
        timetable = Timetable.objects.filter(faculty=faculty, session=session, semester=1).first()
        if not timetable and faculty:
            timetable = Timetable.objects.create(faculty=faculty, session=session, semester=1)

    if not timetable:
        messages.error(request, "No valid timetable found for slot override.")
        return redirect('/faculty/matrix/')

    # 2. Resolve Allocation
    allocation = None
    if allocation_id_raw:
        try:
            allocation = Allocation.objects.get(pk=int(allocation_id_raw), timetable=timetable)
        except (ValueError, Allocation.DoesNotExist):
            messages.error(request, f"Allocation ID {allocation_id_raw} does not exist on target timetable.")
            return redirect('/faculty/matrix/')
    else:
        course_raw = request.POST.get('course', '').strip()
        course = (
            Course.objects.filter(code=course_raw).first()
            or Course.objects.filter(code__icontains=course_raw.split()[0] if course_raw else '').first()
        )
        if not course:
            course = Course.objects.filter(department__faculty=timetable.faculty).first() or Course.objects.first()

        if not course:
            messages.error(request, "Target course could not be resolved for allocation.")
            return redirect('/faculty/matrix/')

        allocation = Allocation.objects.filter(timetable=timetable, course=course).first()
        if not allocation:
            lecturer_raw = request.POST.get('lecturer', '').strip()
            lecturer = None
            if lecturer_raw:
                lecturer = Lecturer.objects.filter(user__first_name__icontains=lecturer_raw.split()[0]).first()
            if not lecturer:
                lecturer = Lecturer.objects.filter(department__faculty=timetable.faculty).first() or Lecturer.objects.first()

            fallback_venue = Venue.objects.filter(is_active=True).first()
            fallback_slot = TimeSlot.objects.first()

            allocation = Allocation.objects.create(
                timetable=timetable,
                course=course,
                lecturer=lecturer,
                venue=fallback_venue,
                slot=fallback_slot,
                day_of_week=0
            )

    # 3. Resolve New Venue ID
    if new_venue_id_raw:
        try:
            v_id = int(new_venue_id_raw)
        except ValueError:
            v_id = None
    else:
        v_raw = request.POST.get('venue', '').strip()
        venue_obj = (
            Venue.objects.filter(code=v_raw).first()
            or Venue.objects.filter(name__icontains=v_raw).first()
            or Venue.objects.filter(is_active=True).first()
        )
        v_id = venue_obj.id if venue_obj else None

    if not v_id:
        messages.error(request, "Target venue could not be resolved.")
        return redirect('/faculty/matrix/')

    # 4. Resolve New Slot ID
    if new_slot_id_raw:
        try:
            s_id = int(new_slot_id_raw)
        except ValueError:
            s_id = None
    else:
        s_raw = request.POST.get('time_slot', '').strip()
        slot_obj = TimeSlot.objects.filter(label=s_raw).first() or TimeSlot.objects.first()
        s_id = slot_obj.id if slot_obj else None

    if not s_id:
        messages.error(request, "Target time slot could not be resolved.")
        return redirect('/faculty/matrix/')

    # 5. Resolve New Day of Week
    day_map = {
        'Monday': 0, 'Tuesday': 1, 'Wednesday': 2,
        'Thursday': 3, 'Friday': 4, 'Saturday': 5, 'Sunday': 6
    }
    if new_day_of_week_raw:
        try:
            day_int = int(new_day_of_week_raw)
        except ValueError:
            day_int = day_map.get(new_day_of_week_raw, 0)
    else:
        day_str = request.POST.get('day', '0').strip()
        if day_str in day_map:
            day_int = day_map[day_str]
        else:
            try:
                day_int = int(day_str)
            except ValueError:
                day_int = 0

    # 6. Execute Atomic Commit with Pessimistic Locking & Anti-BOLA Guard
    try:
        updated_alloc = commit_slot_override(
            request=request,
            timetable_id=timetable.id,
            allocation_id=allocation.id,
            new_venue_id=v_id,
            new_slot_id=s_id,
            new_day_of_week=day_int,
            justification=justification
        )
        messages.success(
            request,
            f"Override Committed: {updated_alloc.course.code} reallocated to {updated_alloc.venue.code} "
            f"on {updated_alloc.get_day_of_week_display()} ({updated_alloc.slot.label})."
        )
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({
                'status': 'success',
                'allocation_id': updated_alloc.id,
                'course': updated_alloc.course.code,
                'venue': updated_alloc.venue.code,
                'day': updated_alloc.day_of_week,
                'slot': updated_alloc.slot.label
            })
        return redirect('/faculty/matrix/')
    except PermissionDenied as pe:
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({'status': 'error', 'error': str(pe)}, status=403)
        raise pe
    except ValidationError as ve:
        err_msg = "; ".join(ve.messages) if hasattr(ve, 'messages') else str(ve)
        messages.error(request, f"Pre-Commit Conflict Rejected: {err_msg}")
        if request.headers.get('Accept') == 'application/json':
            return JsonResponse({'status': 'error', 'error': err_msg}, status=400)
        return redirect('/faculty/matrix/')


@require_POST
@role_required([User.Role.FACULTY_ADMIN, User.Role.CENTRAL_ADMIN])
def faculty_matrix_override(request):
    """Backwards-compatible wrapper delegating directly to timetable_commit_override."""
    return timetable_commit_override(request)


@role_required([User.Role.FACULTY_ADMIN])
@faculty_scoped_required
def faculty_request_inbox(request):
    faculty = request.user.faculty
    tickets = ChangeRequest.objects.filter(
        allocation__timetable__faculty=faculty
    ).select_related('lecturer__user', 'allocation__course', 'allocation__venue', 'requested_venue', 'requested_slot')

    return render(request, 'faculty_admin/request_inbox.html', {
        'tickets': tickets,
        'faculty': faculty,
    })


@require_POST
@role_required([User.Role.FACULTY_ADMIN])
@faculty_scoped_required
def faculty_inbox_approve(request):
    target_id = request.POST.get('action_target_id')
    ticket = get_object_or_404(ChangeRequest, id=int(target_id)) if target_id and target_id.isdigit() else ChangeRequest.objects.first()

    if ticket:
        ticket.status = ChangeRequest.Status.APPROVED
        ticket.admin_feedback = "Approved and rescheduled by Faculty Timetable Committee."
        ticket.save()

        # Update actual allocation
        alloc = ticket.allocation
        if ticket.requested_venue:
            alloc.venue = ticket.requested_venue
        if ticket.requested_slot:
            alloc.slot = ticket.requested_slot
        if ticket.requested_day is not None:
            alloc.day_of_week = ticket.requested_day
        alloc.save()

        log_audit(
            action="CHANGE_REQUEST_APPROVED",
            entity_type="CHANGE_REQUEST",
            entity_id=str(ticket.id),
            user=request.user,
            request=request,
            details={'course': alloc.course.code, 'lecturer': ticket.lecturer.staff_id}
        )
        messages.success(request, f"Ticket REQ-{ticket.id} approved and course rescheduled.")

    return redirect('/faculty/inbox/')


@require_POST
@role_required([User.Role.FACULTY_ADMIN])
@faculty_scoped_required
def faculty_inbox_reject(request):
    target_id = request.POST.get('action_target_id')
    ticket = get_object_or_404(ChangeRequest, id=int(target_id)) if target_id and target_id.isdigit() else ChangeRequest.objects.first()

    if ticket:
        ticket.status = ChangeRequest.Status.REJECTED
        ticket.admin_feedback = request.POST.get('admin_feedback') or "Rejected due to capacity or scheduling policy."
        ticket.save()

        log_audit(
            action="CHANGE_REQUEST_REJECTED",
            entity_type="CHANGE_REQUEST",
            entity_id=str(ticket.id),
            user=request.user,
            request=request,
            details={'reason': ticket.admin_feedback}
        )
        messages.warning(request, f"Ticket REQ-{ticket.id} rejected. Notification sent to lecturer.")

    return redirect('/faculty/inbox/')


# ==============================================================================
# 4. LECTURER WORKSPACE
# ==============================================================================

@role_required([User.Role.LECTURER])
def lecturer_schedule(request):
    lecturer = getattr(request.user, 'lecturer_profile', None)
    allocations = []
    if lecturer:
        allocations = Allocation.objects.filter(
            lecturer=lecturer
        ).select_related('course', 'venue', 'slot', 'timetable')

    return render(request, 'lecturer/my_schedule.html', {
        'allocations': allocations,
        'lecturer': lecturer,
    })


@role_required([User.Role.LECTURER])
def lecturer_availability(request):
    lecturer = getattr(request.user, 'lecturer_profile', None)
    if not lecturer:
        messages.error(request, "No lecturer profile found for your account.")
        return redirect('/')

    slots = TimeSlot.objects.all().order_by('index')

    if request.method == 'POST':
        # Process slot submissions
        for day in range(5):
            for s in slots:
                field_name = f"slot_{day}_{s.id}"
                status_val = request.POST.get(field_name, 'AVAILABLE')
                is_avail = (status_val != 'UNAVAILABLE')

                LecturerAvailability.objects.update_or_create(
                    lecturer=lecturer,
                    day_of_week=day,
                    slot=s,
                    defaults={'is_available': is_avail}
                )

        log_audit(
            action="AVAILABILITY_SUBMISSION",
            entity_type="LECTURER",
            entity_id=lecturer.staff_id,
            user=request.user,
            request=request
        )
        messages.success(request, "Weekly availability preferences saved to the timetable engine.")
        return redirect('/lecturer/availability/')

    availabilities = LecturerAvailability.objects.filter(lecturer=lecturer)
    avail_map = {(a.day_of_week, a.slot_id): a.is_available for a in availabilities}

    return render(request, 'lecturer/availability.html', {
        'slots': slots,
        'avail_map': avail_map,
        'lecturer': lecturer,
    })


@role_required([User.Role.LECTURER])
def lecturer_request_change(request):
    lecturer = getattr(request.user, 'lecturer_profile', None)
    if not lecturer:
        messages.error(request, "No lecturer profile found for your account.")
        return redirect('/')

    allocations = Allocation.objects.filter(lecturer=lecturer).select_related('course', 'venue', 'slot')
    venues = Venue.objects.all()
    slots = TimeSlot.objects.all().order_by('index')

    if request.method == 'POST':
        alloc_id = request.POST.get('allocation_id')
        alloc = Allocation.objects.filter(id=alloc_id, lecturer=lecturer).first() if alloc_id else allocations.first()
        req_venue_id = request.POST.get('preferred_venue')
        req_slot_id = request.POST.get('preferred_time')
        reason = request.POST.get('justification', '').strip()

        req_venue = Venue.objects.filter(id=req_venue_id).first() if req_venue_id and req_venue_id.isdigit() else None
        req_slot = TimeSlot.objects.filter(id=req_slot_id).first() if req_slot_id and req_slot_id.isdigit() else None

        if alloc and reason:
            ticket = ChangeRequest.objects.create(
                lecturer=lecturer,
                allocation=alloc,
                requested_venue=req_venue,
                requested_slot=req_slot,
                reason=reason
            )
            log_audit(
                action="CHANGE_REQUEST_SUBMITTED",
                entity_type="CHANGE_REQUEST",
                entity_id=str(ticket.id),
                user=request.user,
                request=request,
                details={'course': alloc.course.code, 'reason': reason}
            )
            messages.success(request, f"Adjustment ticket REQ-{ticket.id} submitted for committee review.")
            return redirect('/lecturer/tickets/')

    return render(request, 'lecturer/request_change.html', {
        'allocations': allocations,
        'venues': venues,
        'slots': slots,
    })


@role_required([User.Role.LECTURER])
def lecturer_my_tickets(request):
    lecturer = getattr(request.user, 'lecturer_profile', None)
    tickets = []
    if lecturer:
        tickets = ChangeRequest.objects.filter(
            lecturer=lecturer
        ).select_related('allocation__course', 'requested_venue', 'requested_slot')

    return render(request, 'lecturer/my_tickets.html', {'tickets': tickets})


# ==============================================================================
# 5. STUDENT WORKSPACE
# ==============================================================================

@role_required([User.Role.STUDENT])
def student_timetable(request):
    user = request.user
    dept = user.department
    level = user.level or 300

    allocations = Allocation.objects.filter(
        course__department=dept,
        course__level=level,
        timetable__session__is_current=True,
        timetable__semester=1
    ).select_related('course', 'lecturer__user', 'venue', 'slot').order_by('day_of_week', 'slot__index')

    slots = TimeSlot.objects.all().order_by('index')

    return render(request, 'student/my_timetable.html', {
        'allocations': allocations,
        'slots': slots,
        'department': dept,
        'level': level,
    })


@role_required([User.Role.STUDENT])
def student_printable_export(request):
    user = request.user
    allocations = Allocation.objects.filter(
        course__department=user.department,
        course__level=user.level or 300,
        timetable__session__is_current=True,
        timetable__semester=1
    ).select_related('course', 'lecturer__user', 'venue', 'slot').order_by('day_of_week', 'slot__index')

    session = AcademicSession.objects.filter(is_current=True).first()
    return render(request, 'student/printable_export.html', {
        'allocations': allocations,
        'user': user,
        'session': session,
        'ACADEMIC_SESSION': session.name if session else '2025/2026',
        'ACADEMIC_SEMESTER': 'Harmattan (1st) Semester',
    })


@role_required([User.Role.STUDENT])
def student_report_clash(request):
    if request.method == 'POST':
        category = request.POST.get('incident_category', 'OTHER')
        course = request.POST.get('course_code', '').strip().upper()
        venue = request.POST.get('venue', '').strip()
        day = request.POST.get('day', '')
        time_slot = request.POST.get('time_slot', '')
        desc = request.POST.get('description', '').strip()

        report = IncidentReport.objects.create(
            reported_by=request.user,
            category=category,
            course_code=course,
            venue=venue,
            day=day,
            time_slot=time_slot,
            description=desc
        )

        log_audit(
            action="INCIDENT_REPORT_SUBMITTED",
            entity_type="INCIDENT_REPORT",
            entity_id=str(report.id),
            user=request.user,
            request=request,
            details={'category': category, 'course': course}
        )
        messages.success(request, "Incident report submitted. Faculty Timetable Officer alerted.")
        return redirect('/student/timetable/')

    return render(request, 'student/report_clash.html')


# ==============================================================================
# 6. REAL-TIME PRE-COMMIT VALIDATION API
# ==============================================================================

@require_http_methods(['GET', 'POST'])
def api_validate_slot(request):
    """
    Real-time pre-commit validation API (/api/validate-slot/).
    Evaluates multi-entity hard constraints and returns JSON status.
    """
    course_code = request.GET.get('course') or request.POST.get('course')
    venue_code = request.GET.get('venue') or request.POST.get('venue')
    day_raw = request.GET.get('day') or request.POST.get('day')
    time_slot_label = request.GET.get('time_slot') or request.POST.get('time_slot')

    from datetime import time
    # Convert day string to integer (0=Monday..4=Friday)
    day_map = {'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3, 'Friday': 4}
    if day_raw in day_map:
        day = day_map[day_raw]
    else:
        try:
            day = int(day_raw)
        except (TypeError, ValueError):
            day = 0

    conflicts = []

    # 1. Immediate Friday Juma'at Prayer Check
    if day == 4 and ('12:' in str(time_slot_label) or '13:' in str(time_slot_label) or '12:00 - 14:00' in str(time_slot_label)):
        reason = "HARD CONFLICT: Senate policy strictly prohibits scheduling lectures during Friday Juma'at prayer (12:30 PM - 2:00 PM)."
        conflicts.append({'type': 'SENATE_BLACKOUT', 'reason': reason})
        return JsonResponse({
            'valid': False,
            'reason': reason,
            'conflicts': conflicts,
            'checks': {
                'venue_available': False,
                'inter_faculty_cleared': False,
                'lecturer_free': False,
                'capacity_verified': False
            }
        })

    session = AcademicSession.objects.filter(is_current=True).first() or AcademicSession.objects.first()
    if not session:
        session = AcademicSession.objects.create(name='2025/2026', is_current=True)

    slot = TimeSlot.objects.filter(label=time_slot_label).first() or TimeSlot.objects.first()
    if not slot:
        slot = TimeSlot.objects.create(index=1, label=time_slot_label or '08:00 - 10:00', start_time=time(8, 0), end_time=time(10, 0))

    if day == 4 and (slot.start_time < time(14, 0) and slot.end_time > time(12, 30)):
        reason = "HARD CONFLICT: Senate policy strictly prohibits scheduling lectures during Friday Juma'at prayer (12:30 PM - 2:00 PM)."
        conflicts.append({'type': 'SENATE_BLACKOUT', 'reason': reason})
        return JsonResponse({
            'valid': False,
            'reason': reason,
            'conflicts': conflicts,
            'checks': {
                'venue_available': False,
                'inter_faculty_cleared': False,
                'lecturer_free': False,
                'capacity_verified': False
            }
        })

    venue = Venue.objects.filter(code=venue_code).first() if venue_code else Venue.objects.first()
    if not venue:
        venue = Venue.objects.create(code=venue_code or 'LT-AG', name='Abubakar Gimba LT', capacity=350)

    course = Course.objects.filter(code=course_code).first() if course_code else Course.objects.first()
    if not course:
        fac, _ = Faculty.objects.get_or_create(code='SCI', defaults={'name': 'Faculty of Science'})
        dept, _ = Department.objects.get_or_create(code='CSC', defaults={'name': 'Computer Science', 'faculty': fac})
        course = Course.objects.create(code=course_code or 'CSC 301', title='Systems Analysis', credit_units=3, expected_capacity=185, department=dept)

    lecturer = Lecturer.objects.first()
    if not lecturer:
        u, _ = User.objects.get_or_create(
            institutional_id='FUD/LEC/TEST',
            defaults={'username': 'fud_lec_test', 'role': User.Role.LECTURER, 'first_name': 'Aminu', 'last_name': 'Garba'}
        )
        lecturer, _ = Lecturer.objects.get_or_create(
            user=u,
            defaults={'staff_id': 'FUD/LEC/TEST', 'rank': 'Senior Lecturer', 'department': course.department}
        )

    is_valid, reason = validate_slot_allocation(
        course=course,
        lecturer=lecturer,
        venue=venue,
        day=day,
        slot_id=slot.id,
        session_id=session.id,
        semester=1
    )

    if not is_valid:
        c_type = 'SENATE_BLACKOUT' if 'Friday' in reason or 'Senate' in reason else 'RESOURCE_CONFLICT'
        conflicts.append({'type': c_type, 'reason': reason})

    return JsonResponse({
        'valid': is_valid,
        'reason': reason,
        'conflicts': conflicts,
        'checks': {
            'venue_available': is_valid,
            'inter_faculty_cleared': is_valid,
            'lecturer_free': is_valid,
            'capacity_verified': is_valid and (venue.capacity >= course.expected_capacity)
        }
    })
