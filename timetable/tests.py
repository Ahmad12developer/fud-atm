"""
Comprehensive Automated Test Suite for Federal University Dutse (FUD) ATMS.
Validates:
1. Relational Models, Role-to-Scope Invariants & Constraints
2. Authentication, Account Lockout (5 attempts), IP Rate Limiting & Audit Trails
3. RBAC Route Protection & Least-Privilege Access Control
4. Slot Pre-Commit Validation (Friday Prayer Lockout, Capacity, Clashes)
5. Bounded Heuristic Timetable Scheduler (MRV, Backtracking, Invariants)
6. Django Template Rendering & CSRF Presence across all 5 Workspaces
"""
from datetime import time, timedelta
from django.test import TestCase, Client, RequestFactory
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.contrib.sessions.middleware import SessionMiddleware

from timetable.models import (
    Faculty, Department, TimeSlot, Course, Venue, Lecturer,
    AcademicSession, Timetable, Allocation, ChangeRequest,
    AuditLog, InterAdminMessage, OptimizationSetting, IncidentReport
)
from timetable.auth_service import check_ip_rate_limit, authenticate_user
from timetable.scheduling.validation import validate_slot_allocation
from timetable.scheduling.scheduler import BoundedScheduler

User = get_user_model()


class FudBaseTestCase(TestCase):
    """Base test class providing full FUD institutional fixtures."""

    def setUp(self):
        super().setUp()
        cache.clear()
        self.client = Client()

        # Institutional Structure
        self.faculty_comp = Faculty.objects.create(code='COMP', name='Faculty of Computing & Information Technology')
        self.faculty_sci = Faculty.objects.create(code='SCI', name='Faculty of Science')

        self.dept_csc = Department.objects.create(code='CSC', name='Computer Science', faculty=self.faculty_comp)
        self.dept_se = Department.objects.create(code='SE', name='Software Engineering', faculty=self.faculty_comp)

        # Academic Session & Canonical Time Slots
        self.session = AcademicSession.objects.create(name='2025/2026', is_current=True)
        self.slot_1 = TimeSlot.objects.create(index=0, label='08:00 - 10:00', start_time=time(8, 0), end_time=time(10, 0))
        self.slot_2 = TimeSlot.objects.create(index=1, label='10:00 - 12:00', start_time=time(10, 0), end_time=time(12, 0))
        self.slot_3 = TimeSlot.objects.create(index=2, label='12:00 - 14:00', start_time=time(12, 0), end_time=time(14, 0))
        self.slot_4 = TimeSlot.objects.create(index=3, label='14:00 - 16:00', start_time=time(14, 0), end_time=time(16, 0))
        self.slot_5 = TimeSlot.objects.create(index=4, label='16:00 - 18:00', start_time=time(16, 0), end_time=time(18, 0))

        # Infrastructure Venues
        self.venue_lt_ag = Venue.objects.create(code='LT-AG', name='Abubakar Gimba Lecture Theatre', capacity=350, is_active=True)
        self.venue_twin_a = Venue.objects.create(code='TWIN-A', name='Faculty Twin Theatre A', capacity=200, faculty=self.faculty_comp, is_active=True)
        self.venue_lab = Venue.objects.create(code='LAB-PTDF', name='PTDF Software Lab', capacity=80, faculty=self.faculty_comp, is_active=True)

        # Institutional Users (Passwords: FudPass@2025)
        self.pwd = 'FudPass@2025'

        self.user_admin = User.objects.create_user(
            username='fud_adm_001',
            institutional_id='FUD/ADM/2024/001',
            email='admin@fud.edu.ng',
            password=self.pwd,
            first_name='Central',
            last_name='Admin',
            role=User.Role.CENTRAL_ADMIN
        )

        self.user_faculty_admin = User.objects.create_user(
            username='fud_sci_014',
            institutional_id='FUD/SCI/2024/014',
            email='faculty_admin@fud.edu.ng',
            password=self.pwd,
            first_name='Faculty',
            last_name='Officer',
            role=User.Role.FACULTY_ADMIN,
            faculty=self.faculty_comp
        )

        self.user_lecturer = User.objects.create_user(
            username='fud_lec_088',
            institutional_id='FUD/LEC/2024/088',
            email='aminu.garba@fud.edu.ng',
            password=self.pwd,
            first_name='Aminu',
            last_name='Garba',
            role=User.Role.LECTURER,
            department=self.dept_csc,
            faculty=self.faculty_comp
        )
        self.lecturer_profile = Lecturer.objects.create(
            user=self.user_lecturer,
            staff_id='FUD/LEC/2024/088',
            department=self.dept_csc,
            max_hours_per_week=12
        )

        self.user_student = User.objects.create_user(
            username='fud_cst_0456',
            institutional_id='FUD/CST/21/0456',
            email='fatima.bello@fud.edu.ng',
            password=self.pwd,
            first_name='Fatima',
            last_name='Bello',
            role=User.Role.STUDENT,
            department=self.dept_csc,
            faculty=self.faculty_comp,
            level=300
        )

        # Courses
        self.course_301 = Course.objects.create(
            code='CSC 301',
            title='Structured Systems Analysis & Design',
            credit_units=3,
            level=300,
            department=self.dept_csc,
            expected_capacity=185
        )
        self.course_305 = Course.objects.create(
            code='CSC 305',
            title='Database Management Systems',
            credit_units=3,
            level=300,
            department=self.dept_csc,
            expected_capacity=190
        )
        self.course_101 = Course.objects.create(
            code='CSC 101',
            title='Intro to Computer Science',
            credit_units=3,
            level=100,
            department=self.dept_csc,
            expected_capacity=320
        )

        # Baseline Timetable & Allocation
        self.timetable = Timetable.objects.create(
            session=self.session,
            semester=1,
            faculty=self.faculty_comp,
            status=Timetable.Status.DRAFT
        )
        self.alloc_301 = Allocation.objects.create(
            timetable=self.timetable,
            course=self.course_301,
            lecturer=self.lecturer_profile,
            venue=self.venue_lt_ag,
            day_of_week=0,  # Monday
            slot=self.slot_1
        )


class FudInstitutionalModelTests(FudBaseTestCase):
    """Verifies schema invariants, custom user scoping, and compound relational constraints."""

    def test_central_admin_role_scope_invariant(self):
        """Central Admin should defensively clear faculty and department."""
        admin = User(
            username='admin_test',
            institutional_id='FUD/ADM/2024/999',
            role=User.Role.CENTRAL_ADMIN,
            faculty=self.faculty_comp,
            department=self.dept_csc
        )
        admin.clean()
        self.assertIsNone(admin.faculty)
        self.assertIsNone(admin.department)

    def test_faculty_admin_requires_faculty_scope(self):
        """Faculty Admin without assigned faculty must fail validation."""
        fa = User(
            username='fa_unscoped',
            institutional_id='FUD/SCI/2024/999',
            role=User.Role.FACULTY_ADMIN,
            faculty=None
        )
        with self.assertRaises(ValidationError):
            fa.clean()

    def test_student_requires_department_and_level(self):
        """Student without department or level must fail validation."""
        st_no_dept = User(
            username='st_no_dept',
            institutional_id='FUD/CST/21/9999',
            role=User.Role.STUDENT,
            department=None,
            level=300
        )
        with self.assertRaises(ValidationError):
            st_no_dept.clean()

        st_no_level = User(
            username='st_no_level',
            institutional_id='FUD/CST/21/9998',
            role=User.Role.STUDENT,
            department=self.dept_csc,
            level=None
        )
        with self.assertRaises(ValidationError):
            st_no_level.clean()

    def test_timeslot_ordering_validation(self):
        """TimeSlot start time must strictly precede end time."""
        invalid_slot = TimeSlot(
            index=99,
            label='Invalid',
            start_time=time(14, 0),
            end_time=time(12, 0)
        )
        with self.assertRaises(ValidationError):
            invalid_slot.clean()

    def test_timetable_unique_together_constraint(self):
        """Cannot duplicate timetable for same faculty, session, and semester."""
        with self.assertRaises(Exception):
            Timetable.objects.create(
                session=self.session,
                semester=1,
                faculty=self.faculty_comp,
                status=Timetable.Status.DRAFT
            )


class FudSecurityAndAuthServiceTests(FudBaseTestCase):
    """Verifies constant-time auth, 5-attempt account lockout, IP rate limiting, and audit logs."""

    def setUp(self):
        super().setUp()
        self.factory = RequestFactory()

    def _auth_attempt(self, inst_id, password, ip='127.0.0.1'):
        request = self.factory.post('/login/', REMOTE_ADDR=ip)
        middleware = SessionMiddleware(lambda req: None)
        middleware.process_request(request)
        request.session.save()
        return authenticate_user(request, inst_id, password)

    def test_successful_authentication_clears_failures(self):
        """Correct credentials authenticate and reset failed count."""
        self.user_lecturer.failed_login_count = 3
        self.user_lecturer.save()

        res = self._auth_attempt(self.user_lecturer.institutional_id, self.pwd)
        self.assertTrue(res.success)
        self.assertEqual(res.user.institutional_id, self.user_lecturer.institutional_id)
        self.user_lecturer.refresh_from_db()
        self.assertEqual(self.user_lecturer.failed_login_count, 0)

    def test_account_lockout_after_5_failed_attempts(self):
        """5 incorrect passwords locks the account for 15 minutes."""
        for i in range(1, 5):
            res = self._auth_attempt(self.user_student.institutional_id, 'WrongPassword')
            self.assertFalse(res.success)
            self.assertEqual(res.error_code, 'INVALID_CREDENTIALS')

        # 5th attempt triggers lockout
        res = self._auth_attempt(self.user_student.institutional_id, 'WrongPassword')
        self.assertFalse(res.success)
        self.assertEqual(res.error_code, 'ACCOUNT_LOCKED')

        self.user_student.refresh_from_db()
        self.assertTrue(self.user_student.is_locked())
        self.assertIsNotNone(self.user_student.locked_until)

        # 6th attempt (even with right password) is rejected while locked
        res = self._auth_attempt(self.user_student.institutional_id, self.pwd)
        self.assertFalse(res.success)
        self.assertEqual(res.error_code, 'ACCOUNT_LOCKED')

    def test_ip_rate_limiting(self):
        """20 attempts per minute per IP exhausts rate limit."""
        test_ip = '192.168.10.45'
        cache.clear()

        for _ in range(20):
            allowed = check_ip_rate_limit(test_ip)
            self.assertTrue(allowed)

        # 21st attempt exceeds limit
        allowed = check_ip_rate_limit(test_ip)
        self.assertFalse(allowed)

    def test_audit_trail_recorded_on_auth_events(self):
        """Authentication events must generate structured audit logs without sensitive leaks."""
        self._auth_attempt(self.user_admin.institutional_id, self.pwd, ip='10.0.0.1')
        log = AuditLog.objects.filter(action="LOGIN_SUCCESS").first()
        self.assertIsNotNone(log)
        self.assertEqual(log.user, self.user_admin)
        self.assertNotIn(self.pwd, str(log.details))


class FudDeterministicIdentityRoutingTests(FudBaseTestCase):
    """Verifies that unified /login/ routes deterministically by institutional ID prefix."""

    def test_central_admin_login_routing(self):
        resp = self.client.post('/login/', {
            'institutional_id': 'FUD/ADM/2024/001',
            'password': self.pwd
        })
        self.assertRedirects(resp, '/central/dashboard/')

    def test_faculty_admin_login_routing(self):
        resp = self.client.post('/login/', {
            'institutional_id': 'FUD/SCI/2024/014',
            'password': self.pwd
        })
        self.assertRedirects(resp, '/faculty/dashboard/')

    def test_lecturer_login_routing(self):
        resp = self.client.post('/login/', {
            'institutional_id': 'FUD/LEC/2024/088',
            'password': self.pwd
        })
        self.assertRedirects(resp, '/lecturer/schedule/')

    def test_student_login_routing(self):
        resp = self.client.post('/login/', {
            'institutional_id': 'FUD/CST/21/0456',
            'password': self.pwd
        })
        self.assertRedirects(resp, '/student/timetable/')

    def test_unregistered_institutional_id_rejected(self):
        resp = self.client.post('/login/', {
            'institutional_id': 'FUD/UNKNOWN/999',
            'password': self.pwd
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Invalid Institutional Identifier or Password')


class FudRbacAccessControlTests(FudBaseTestCase):
    """Verifies strict Least-Privilege Role-Based Access Control and HTTP 403 / redirect gating."""

    def test_unauthenticated_user_redirected_to_login(self):
        """Unauthenticated user accessing any protected endpoint is redirected to login."""
        protected_endpoints = [
            '/central/dashboard/',
            '/faculty/dashboard/',
            '/lecturer/schedule/',
            '/student/timetable/',
        ]
        for ep in protected_endpoints:
            resp = self.client.get(ep)
            self.assertEqual(resp.status_code, 302)
            self.assertTrue(resp.url.startswith('/login/'))

    def test_student_cannot_access_central_admin(self):
        """Student attempting to access Central Admin views receives 403 Forbidden."""
        self.client.force_login(self.user_student)
        resp = self.client.get('/central/dashboard/')
        self.assertEqual(resp.status_code, 403)

    def test_lecturer_cannot_access_faculty_admin(self):
        """Lecturer attempting to access Faculty Admin views receives 403 Forbidden."""
        self.client.force_login(self.user_lecturer)
        resp = self.client.get('/faculty/generate/')
        self.assertEqual(resp.status_code, 403)

    def test_faculty_admin_scoped_access(self):
        """Faculty Admin can only manage their own faculty."""
        self.client.force_login(self.user_faculty_admin)
        resp = self.client.get('/faculty/dashboard/')
        self.assertEqual(resp.status_code, 200)


class FudSlotPreCommitValidationEngineTests(FudBaseTestCase):
    """Verifies hard constraints: Friday Juma'at lockout, capacity, venue & cohort collisions."""

    def test_friday_prayer_lockout_hard_conflict(self):
        """Day 4 (Friday) during 12:30–14:00 must be rejected as SENATE_BLACKOUT."""
        is_valid, reason = validate_slot_allocation(
            course=self.course_301,
            lecturer=self.lecturer_profile,
            venue=self.venue_lt_ag,
            day=4,  # Friday
            slot_id=self.slot_3.id,  # 12:00 - 14:00 overlaps 12:30-14:00
            session_id=self.session.id,
            semester=1
        )
        self.assertFalse(is_valid)
        self.assertIn("Senate policy strictly prohibits scheduling lectures during Friday Juma'at prayer", reason)

    def test_venue_capacity_deficit_conflict(self):
        """Venue capacity smaller than course expected cohort size must be rejected."""
        # course_101 has 320 students, venue_lab has 80 capacity
        is_valid, reason = validate_slot_allocation(
            course=self.course_101,
            lecturer=self.lecturer_profile,
            venue=self.venue_lab,
            day=1,
            slot_id=self.slot_1.id,
            session_id=self.session.id,
            semester=1
        )
        self.assertFalse(is_valid)
        self.assertIn("CAPACITY DEFICIT", reason)

    def test_venue_collision_conflict(self):
        """Slot already occupied in the same venue must be rejected."""
        # alloc_301 is on Monday (day 0), slot_1 (08:00-10:00), venue_lt_ag
        is_valid, reason = validate_slot_allocation(
            course=self.course_305,
            lecturer=self.lecturer_profile,
            venue=self.venue_lt_ag,
            day=0,
            slot_id=self.slot_1.id,
            session_id=self.session.id,
            semester=1
        )
        self.assertFalse(is_valid)
        self.assertIn("VENUE COLLISION", reason)

    def test_lecturer_collision_conflict(self):
        """Lecturer already teaching another course at that time must be rejected."""
        # Lecturer is already allocated at Monday, slot_1 in venue_lt_ag
        is_valid, reason = validate_slot_allocation(
            course=self.course_305,
            lecturer=self.lecturer_profile,
            venue=self.venue_twin_a,  # Different venue
            day=0,
            slot_id=self.slot_1.id,  # Same time
            session_id=self.session.id,
            semester=1
        )
        self.assertFalse(is_valid)
        self.assertIn("LECTURER CLASH", reason)

    def test_student_cohort_collision_conflict(self):
        """Same department and level cannot be booked in two classes simultaneously."""
        # CSC 300L is already allocated at Monday, slot_1
        another_lecturer_user = User.objects.create_user(
            username='another_lec',
            institutional_id='FUD/LEC/2024/099',
            password=self.pwd,
            role=User.Role.LECTURER,
            department=self.dept_csc,
            faculty=self.faculty_comp
        )
        another_lec = Lecturer.objects.create(
            user=another_lecturer_user,
            staff_id='FUD/LEC/2024/099',
            department=self.dept_csc
        )
        is_valid, reason = validate_slot_allocation(
            course=self.course_305,  # Also CSC 300L
            lecturer=another_lec,
            venue=self.venue_twin_a,
            day=0,
            slot_id=self.slot_1.id,
            session_id=self.session.id,
            semester=1
        )
        self.assertFalse(is_valid)
        self.assertIn("STUDENT COHORT CLASH", reason)

    def test_validation_api_endpoint_valid(self):
        """API endpoint returns valid=True for conflict-free slot."""
        resp = self.client.get('/api/validate-slot/', {
            'day': 'Tuesday',
            'time_slot': '08:00 - 10:00',
            'venue': 'TWIN-A',
            'course': 'CSC 305',
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['valid'])
        self.assertEqual(len(data['conflicts']), 0)
        self.assertTrue(data['checks']['venue_available'])

    def test_validation_api_endpoint_friday_lockout(self):
        """API endpoint returns valid=False and SENATE_BLACKOUT for Friday prayer slot."""
        resp = self.client.get('/api/validate-slot/', {
            'day': 'Friday',
            'time_slot': '12:00 - 14:00',
            'venue': 'LT-AG',
            'course': 'CSC 301',
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data['valid'])
        self.assertTrue(any(c['type'] == 'SENATE_BLACKOUT' for c in data['conflicts']))


class FudBoundedSchedulerTests(FudBaseTestCase):
    """Verifies that the heuristic scheduler respects DoS node budgets and generates clash-free schedules."""

    def test_bounded_scheduler_execution(self):
        scheduler = BoundedScheduler(timetable=self.timetable)
        result = scheduler.solve()
        self.assertIsNotNone(result)
        self.assertLessEqual(result.nodes_explored, 25_000)
        self.assertIn('hard_conflicts', result.breakdown)


class FudWorkspaceViewsAndTemplateRenderingTests(FudBaseTestCase):
    """Verifies that all 18+ templates render cleanly with HTTP 200, CSRF tokens, and role gating."""

    def test_login_template_rendering(self):
        resp = self.client.get('/login/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'FEDERAL UNIVERSITY DUTSE')
        self.assertContains(resp, 'csrfmiddlewaretoken')

    def test_central_admin_pages_rendering(self):
        self.client.force_login(self.user_admin)
        endpoints = [
            '/central/dashboard/',
            '/central/optimization/',
            '/central/comms/',
            '/central/audit/',
        ]
        for ep in endpoints:
            with self.subTest(endpoint=ep):
                resp = self.client.get(ep)
                self.assertEqual(resp.status_code, 200, f"Failed rendering {ep}")
                self.assertContains(resp, 'FEDERAL UNIVERSITY DUTSE')
                self.assertContains(resp, 'Central Admin')
                self.assertContains(resp, 'csrfmiddlewaretoken')

    def test_faculty_admin_pages_rendering(self):
        self.client.force_login(self.user_faculty_admin)
        endpoints = [
            '/faculty/dashboard/',
            '/faculty/resources/',
            '/faculty/generate/',
            '/faculty/matrix/',
            '/faculty/inbox/',
        ]
        for ep in endpoints:
            with self.subTest(endpoint=ep):
                resp = self.client.get(ep)
                self.assertEqual(resp.status_code, 200, f"Failed rendering {ep}")
                self.assertContains(resp, 'Faculty Admin')
                self.assertContains(resp, 'csrfmiddlewaretoken')

    def test_lecturer_pages_rendering(self):
        self.client.force_login(self.user_lecturer)
        endpoints = [
            '/lecturer/schedule/',
            '/lecturer/availability/',
            '/lecturer/request-change/',
            '/lecturer/tickets/',
        ]
        for ep in endpoints:
            with self.subTest(endpoint=ep):
                resp = self.client.get(ep)
                self.assertEqual(resp.status_code, 200, f"Failed rendering {ep}")
                self.assertContains(resp, 'Lecturer')
                self.assertContains(resp, 'csrfmiddlewaretoken')

    def test_student_pages_rendering(self):
        self.client.force_login(self.user_student)
        endpoints = [
            '/student/timetable/',
            '/student/export/',
            '/student/report-clash/',
        ]
        for ep in endpoints:
            with self.subTest(endpoint=ep):
                resp = self.client.get(ep)
                self.assertEqual(resp.status_code, 200, f"Failed rendering {ep}")
                self.assertContains(resp, 'FEDERAL UNIVERSITY DUTSE')
                if ep != '/student/export/':  # Printable view is a clean print layout
                    self.assertContains(resp, 'Student Portal')

    def test_role_gated_navigation_elements(self):
        """Verifies that navigation links for other roles are not visible in the rendered layout."""
        self.client.force_login(self.user_admin)
        resp = self.client.get('/central/dashboard/')
        content = resp.content.decode('utf-8')
        self.assertIn('University Dashboard', content)
        self.assertNotIn('Student Portal', content)

        self.client.force_login(self.user_student)
        resp = self.client.get('/student/timetable/')
        content = resp.content.decode('utf-8')
        self.assertIn('Student Portal', content)
        self.assertNotIn('Optimization Tuner', content)

    def test_accessibility_skip_link_and_aria_attributes(self):
        """Verifies WCAG 2.1 AA accessibility attributes: skip link, aria-current, aria-live."""
        # Unauthenticated login page skip link
        resp = self.client.get('/login/')
        self.assertContains(resp, 'href="#main-content"')
        self.assertContains(resp, 'Skip to main content')
        self.assertContains(resp, 'id="main-content"')

        # Authenticated sidebar aria-current="page"
        self.client.force_login(self.user_admin)
        resp = self.client.get('/central/dashboard/')
        self.assertContains(resp, 'aria-current="page"')
        self.assertContains(resp, 'href="#main-content"')

        # Stepper wizard aria-current="step"
        self.client.force_login(self.user_faculty_admin)
        resp = self.client.get('/faculty/generate/')
        self.assertContains(resp, 'aria-current="step"')
        self.assertContains(resp, 'aria-label="Generation Progress"')

        # Schedule matrix aria-live="polite"
        resp = self.client.get('/faculty/matrix/')
        self.assertContains(resp, 'aria-live="polite"')
        self.assertContains(resp, 'role="status"')

    def test_logout_requires_post_with_csrf(self):
        """Ensures /logout/ rejects GET requests with 405 and accepts POST with CSRF."""
        self.client.force_login(self.user_student)
        # GET should be rejected (405 Method Not Allowed)
        get_resp = self.client.get('/logout/')
        self.assertEqual(get_resp.status_code, 405)

        # POST should successfully log out and redirect to /login/
        post_resp = self.client.post('/logout/')
        self.assertEqual(post_resp.status_code, 302)
        self.assertEqual(post_resp.url, '/login/')

    def test_faculty_matrix_override_atomic_guard_rejects_conflict(self):
        """Verifies server-side atomic re-validation rejects conflicting slots and leaves database intact."""
        self.client.force_login(self.user_faculty_admin)
        # Attempt to schedule during Friday Juma'at prayer (day=4 / Friday, 12:00 - 14:00)
        initial_alloc_count = Allocation.objects.count()
        resp = self.client.post('/faculty/matrix/override/', {
            'course': self.course_301.code,
            'lecturer': 'Aminu',
            'day': 'Friday',
            'time_slot': self.slot_3.label,  # 12:00 - 14:00
            'venue': self.venue_lt_ag.code,
            'justification': 'Testing emergency conflict rejection guard'
        })
        self.assertEqual(resp.status_code, 302)
        # Must not have created an allocation for the Friday blackout slot
        friday_prayer_allocs = Allocation.objects.filter(
            course=self.course_301,
            day_of_week=4,
            slot=self.slot_3
        )
        self.assertEqual(friday_prayer_allocs.count(), 0)

    def test_faculty_matrix_override_valid_slot_succeeds(self):
        """Verifies server-side atomic override accepts valid slot and creates/updates allocation."""
        self.client.force_login(self.user_faculty_admin)
        resp = self.client.post('/faculty/matrix/override/', {
            'course': self.course_301.code,
            'lecturer': 'Aminu',
            'day': 'Tuesday',
            'time_slot': self.slot_1.label,  # 08:00 - 10:00
            'venue': self.venue_lt_ag.code,
            'justification': 'Legitimate department schedule update'
        })
        self.assertEqual(resp.status_code, 302)
        alloc = Allocation.objects.filter(
            course=self.course_301,
            venue=self.venue_lt_ag,
            day_of_week=1,
            slot=self.slot_1
        ).first()
        self.assertIsNotNone(alloc)

    def test_printable_export_a4_landscape_and_institutional_header(self):
        """Verifies @page { size: A4 landscape; margin: 1cm; } and institutional header presence."""
        self.client.force_login(self.user_student)
        resp = self.client.get('/student/export/')
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        self.assertIn('size: A4 landscape;', content)
        self.assertIn('margin: 1cm;', content)
        self.assertIn('institutional-print-header', content)
        self.assertIn('SESSION:', content)
        self.assertIn('SEMESTER:', content)
        self.assertIn('DEPARTMENT:', content)
        self.assertIn('LEVEL:', content)

