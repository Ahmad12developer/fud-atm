# Federal University Dutse (FUD) &bull; Automated Timetable Management System (ATMS)

[![Django](https://img.shields.io/badge/Django-5.0+-0C4B33?style=for-the-badge&logo=django&logoColor=white)](https://www.djangoproject.com/)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![TailwindCSS](https://img.shields.io/badge/Tailwind_CSS-3.4+-38B2AC?style=for-the-badge&logo=tailwind-css&logoColor=white)](https://tailwindcss.com/)
[![Tests](https://img.shields.io/badge/Tests-61%20Passed-1B4D3E?style=for-the-badge&logo=pytest&logoColor=white)](#automated-test-suite)
[![Security](https://img.shields.io/badge/Security-OWASP%20Hardened-5C4033?style=for-the-badge&logo=shield&logoColor=white)](#security-architecture)

> **Official Timetable Management & Bounded CSP Scheduling Platform**  
> Developed for the **Directorate of Academic Planning (DAP)** and **Faculty Timetable Committees**, Federal University Dutse (FUD), Jigawa State, Nigeria.  
> *"Knowledge, Excellence & Service"*

---

## 🏛️ System Overview

The **Automated Timetable Management System (ATMS)** is an institutional-grade, multi-tenant scheduling platform engineered for Federal University Dutse. Designed according to the Secure Software Development Lifecycle (SSDLC) and OWASP Top 10 principles, it automates conflict-free timetable generation across all university faculties, enforces strict Senate scheduling policies, and provides dedicated portals for administrators, academic staff, and students.

### Institutional Brand Architecture
- **Primary / Action**: FUD Institutional Forest Green (`#1B4D3E`)
- **Secondary / Accent**: Earthy Warm Brown (`#5C4033`)
- **Base Background**: Clean Off-White (`#F8F9FA`)
- **Borders & Dividers**: Slate Gray (`#E2E8F0`)

---

## ✨ Key Capabilities & Features

### 1. Multi-Tenant Role-Based Workspaces
- **University Central Admin (DAP)**:
  - University-wide dashboard tracking timetables, venue capacities, and faculty readiness across all faculties.
  - Institutional Senate optimization tuner for soft-constraint weights (student gap penalties, lecturer preference weights, travel distance minimization).
  - Official inter-admin dispatch communications channel with faculty officers.
  - Institutional immutable audit log viewer with category and severity filters.
  - Mass publish/rollback controls with status synchronization.
- **Faculty Admin (Timetable Officer)**:
  - Faculty-specific dashboard managing faculty resource pools (lecture halls, theatres, laboratories, courses, lecturers).
  - Multi-step timetable generation wizard with live constraint parameter tuning.
  - Interactive schedule matrix supporting dynamic cohort level filtering (`100L` to `500L` and `ALL`).
  - Pessimistic slot override modal with real-time pre-commit conflict feedback.
  - Lecturer schedule adjustment request inbox with atomic approval/rejection workflows.
- **Lecturer Portal**:
  - Personalized weekly teaching commitment matrix across all 6 operational days.
  - Dynamic contact hour metrics tracking compliance with the Senate 12-hour weekly teaching ceiling.
  - Weekly slot availability preference submission matrix.
  - Structured schedule change request submission and ticket status tracking.
- **Student Portal**:
  - Clean, read-only personal timetable matrix and mobile-first agenda stream.
  - Dynamic cohort level filter (`100L`, `200L`, `300L`, `400L`, `500L`).
  - Conflict reporting form alerting Faculty Timetable Officers of emergency issues.
  - **A4 Landscape Print View**: High-contrast, single-page printout with official FUD letterhead, metadata strip, and authorized sign-off blocks.

---

### 2. Algorithmic Solver & Scheduling Engine
- **Bounded Heuristic CSP Engine**:
  - Implements **Backtracking Search with Forward Checking** and **Minimum Remaining Values (MRV)** heuristic ordering.
  - **DoS Protection & Computational Bounds**: Hard caps on search tree exploration (`MAX_NODES = 25,000`) and execution duration (`TIME_BUDGET_SECONDS = 15.0s`), cleanly rolling back transactions without hanging worker processes.
- **Senate Policy Hard Constraints**:
  - **Full 6-Day Operating Week**: Schedules courses across Monday (0) through Saturday (5).
  - **Friday Juma'at Prayer Blackout**: Strict 12:30 PM – 2:00 PM blackout window enforced in heuristic domains, validation API, and manual overrides.
  - **Venue Capacity Guard**: Rejects allocations where `venue.capacity < course.expected_capacity`.
  - **Collision Elimination**: Prevents double-booking of venues, lecturers, or student cohorts across all faculties.

---

### 3. Concurrency & TOCTOU Elimination
- **Pessimistic Database Row Locking**:
  - Manual overrides in `scheduling/services.py` acquire row-level locks via `select_for_update()` on target `Timetable`, `Allocation`, and `Venue` records inside `with transaction.atomic():`.
  - Hard invariants re-evaluated atomically on the server before mutating state.
- **Persistence Layer UniqueConstraints**:
  - `unique_timetable_venue_slot`: Guarantees no venue double-booking.
  - `unique_timetable_lecturer_slot`: Guarantees no simultaneous lecturer assignment.
  - `unique_timetable_course_slot`: Guarantees no course double-allocation.

---

### 4. Security Architecture (OWASP Top 10 Hardened)
- **Authorization & Tenancy Scoping (BOLA/IDOR)**:
  - Zero client-side role toggling: roles are exclusively governed by server-authenticated `request.user.role`.
  - `@role_required` and `@faculty_scoped_required` decorators restrict faculty officers strictly to `request.user.faculty_id`.
  - Lookups in inbox actions (`faculty_inbox_approve`, `faculty_inbox_reject`) are scoped to `allocation__timetable__faculty=request.user.faculty`.
- **Constant-Time Authentication & Anti-Enumeration**:
  - PBKDF2 dummy hash calculation executed on non-existent or locked accounts to equalize response latency against timing attacks.
  - Strict uniform response: `"Invalid credentials."` across all authentication failure modes.
  - Sliding-window IP rate limiting: hard cap of 20 attempts per 60 seconds in Django cache.
  - Account lockout: 5 consecutive failed login attempts locks account for 15 minutes.
  - Zero test credentials, passwords, or tokens in template markup or comments.
- **CSRF & State Mutation**:
  - All state-changing actions (`/logout/`, overrides, generation, tickets, resets) enforce `POST` with `{% csrf_token %}`.
  - Global JavaScript fetch interceptor in `base.html` automatically injects `X-CSRFToken` header on all AJAX calls.
- **XSS & Template Escaping**:
  - Verified 0 instances of `|safe` on user-controlled inputs.
  - Django automatic HTML escaping active across all rendered contexts.
- **Browser Defense Headers**:
  - `Content-Security-Policy (CSP)`
  - `X-Frame-Options: DENY`
  - `X-Content-Type-Options: nosniff`
  - Secure, HttpOnly, SameSite session and CSRF cookies.

---

## 🛠️ Technology Stack

| Layer | Technologies |
|:---|:---|
| **Backend Framework** | Django 5.x (Python 3.12+) |
| **Database** | SQLite (Development) / PostgreSQL-compatible (Production) |
| **Frontend UI** | Django Server-Side Rendered (SSR) HTML5 |
| **Styling** | Tailwind CSS (FUD Institutional Theme) |
| **Typography** | Inter (Google Fonts) |
| **Scheduling Algorithm** | Constraint Satisfaction Problem (CSP) with MRV & Forward Checking |
| **Cache & Throttling** | Django LocMemCache / Redis |
| **Accessibility** | WCAG 2.1 AA Compliant (Skip links, accessible `<dialog>`, ARIA live regions) |

---

## 🚀 Quick Start & Installation Guide

### Prerequisites
- Python 3.12 or higher
- Git

### 1. Clone the Repository
```bash
git clone https://github.com/Ahmad12developer/fud-atm.git
cd fud-atm
```

### 2. Set Up Virtual Environment
```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install django
```

### 4. Apply Database Migrations
```bash
python manage.py migrate
```

### 5. Seed Institutional Data
Populates the database with faculties, departments, venues, time slots, 100L–500L courses, lecturers, and 35 conflict-free sample allocations:
```bash
python manage.py seed_fud_data
```

### 6. Run the Test Suite
Verify that all 61 automated tests pass:
```bash
python manage.py test
```

### 7. Start the Development Server
```bash
python manage.py runserver
```
Visit **[http://127.0.0.1:8000/](http://127.0.0.1:8000/)** in your browser.

---

## 👥 Seeded Institutional User Accounts

For local evaluation and testing, the database includes pre-provisioned institutional roles:

| Role | Institutional ID / Username | Department / Faculty | Scope & Capabilities |
|:---|:---|:---|:---|
| **Central Admin** | `FUD/ADM/2024/001` | Directorate of Academic Planning (DAP) | University-wide overview, Senate tuner, audit logs, mass publish |
| **Faculty Admin** | `FUD/SCI/2024/014` | Faculty of Computing & Information Tech | Resource pools, timetable generation, matrix overrides, ticket inbox |
| **Lecturer** | `FUD/LEC/2024/088` | Computer Science | 6-day teaching schedule, availability submission, ticket requests |
| **Student** | `FUD/CST/21/0456` | Computer Science (300L) | Read-only timetable matrix, level filter (100L-500L), A4 export |

---

## 🧪 Automated Test Suite

The test suite covers schema invariants, authentication, authorization, BOLA mitigation, race conditions, scheduler bounds, and template rendering:

```bash
$ python manage.py test
Found 61 test(s).
Creating test database for alias 'default'...
System check identified no issues (0 silenced).
.............................................................
----------------------------------------------------------------------
Ran 61 tests in 5.102s

OK
Destroying test database for alias 'default'...
```

### Key Test Categories:
- **`FudInstitutionalModelTests`**: Verifies relational integrity, foreign key protections, and user scoping constraints.
- **`FudSecurityAndAuthServiceTests`**: Validates constant-time dummy hashing, account lockout after 5 attempts, sliding-window IP throttling, and audit logging.
- **`FudRbacAccessControlTests`**: Verifies role decorators and tenant isolation across all endpoints.
- **`FudSlotPreCommitValidationEngineTests`**: Tests Friday Juma'at prayer lockout, room capacity deficit rejection, and cohort clash detection.
- **`FudBoundedSchedulerTests`**: Tests MRV heuristic solver and DoS timeout guard execution.
- **`FudZeroCompromiseSecurityTests`**: Validates pessimistic locking (`select_for_update`), BOLA cross-faculty rejection, and security headers.
- **`FudRemediationAndHardeningTests`**: Validates 6-day schedule grid, dynamic level filtering (100L–500L), database `UniqueConstraint`s, POST-only state changes, and read-only student views.

---

## 📁 Repository Directory Structure

```text
fud-atm/
├── accounts/                  # Authentication service alias exports
│   └── auth_service.py
├── core/                      # Core authorization and permissions alias
│   └── permissions.py
├── scheduling/                # Timetable scheduling service aliases
│   ├── scheduler.py
│   └── services.py
├── fud_atms/                  # Django project configuration & WSGI
│   ├── settings.py            # Security headers, CSP, cookie policies
│   ├── urls.py                # Root URL dispatcher
│   └── wsgi.py
├── templates/                 # Server-Side Rendered Django Templates
│   ├── base.html              # Shell, WCAG 2.1 AA skip links, global CSRF fetch interceptor
│   ├── auth/                  # Login portal
│   ├── central_admin/         # DAP university dashboard, tuner, audit, comms
│   ├── faculty_admin/         # Matrix, resources, generator stepper, inbox
│   ├── lecturer/              # Teaching schedule, availability, ticket forms
│   ├── student/               # Student timetable, level filter, A4 print export
│   └── components/            # Topbar, sidebar, audit badges, confirmation modal
├── timetable/                 # Primary Django application module
│   ├── models.py              # Relational data schema & UniqueConstraints
│   ├── views.py               # Authenticated, tenant-scoped controller endpoints
│   ├── auth_service.py        # Constant-time authentication & anti-enumeration
│   ├── middleware.py          # SecurityHeadersMiddleware & sliding-window throttle
│   ├── audit.py               # Immutable institutional audit logging
│   ├── urls.py                # Route definitions & REST validation endpoints
│   ├── tests.py               # 61 comprehensive automated test cases
│   ├── management/commands/   # seed_fud_data command
│   └── scheduling/            # Bounded heuristic solver & atomic allocation services
├── static/                    # CSS stylesheets and institutional assets
├── manage.py                  # Django CLI management entrypoint
└── README.md                  # Project documentation & reference guide
```

---

## 📄 License & Institutional Copyright

Copyright &copy; 2026 **Federal University Dutse (FUD)**, Jigawa State, Nigeria.  
All rights reserved. Directorate of Academic Planning (DAP).