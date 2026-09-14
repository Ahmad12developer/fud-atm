"""
URL Routing for Federal University Dutse (FUD) ATMS Application.
"""
from django.urls import path
from . import views

urlpatterns = [
    # Root & Deterministic Auth
    path('', views.root_dispatch, name='root_dispatch'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # Central Admin Operations
    path('central/dashboard/', views.central_dashboard, name='central_dashboard'),
    path('central/optimization/', views.central_optimization_tuner, name='central_optimization'),
    path('central/optimization/reset/', views.central_optimization_reset, name='central_optimization_reset'),
    path('central/comms/', views.central_inter_admin_comms, name='central_comms'),
    path('central/comms/send/', views.central_send_message, name='central_send_message'),
    path('central/audit/', views.central_institutional_audit, name='central_audit'),
    path('central/publish-all/', views.central_publish_all, name='central_publish_all'),

    # Faculty Admin Operations
    path('faculty/dashboard/', views.faculty_dashboard, name='faculty_dashboard'),
    path('faculty/resources/', views.faculty_resources, name='faculty_resources'),
    path('faculty/resources/add/', views.faculty_add_resource, name='faculty_add_resource'),
    path('faculty/generate/', views.faculty_generate_stepper, name='faculty_generate'),
    path('faculty/generate/submit/', views.faculty_generate_submit, name='faculty_generate_submit'),
    path('faculty/submit-to-central/', views.faculty_generate_submit, name='faculty_submit_to_central'),
    path('faculty/matrix/', views.faculty_timetable_matrix, name='faculty_matrix'),
    path('faculty/matrix/override/', views.faculty_matrix_override, name='faculty_matrix_override'),
    path('timetable/commit-override/', views.timetable_commit_override, name='timetable_commit_override'),
    path('faculty/inbox/', views.faculty_request_inbox, name='faculty_inbox'),
    path('faculty/inbox/approve/', views.faculty_inbox_approve, name='faculty_inbox_approve'),
    path('faculty/inbox/reject/', views.faculty_inbox_reject, name='faculty_inbox_reject'),

    # Lecturer Self-Service Portal
    path('lecturer/schedule/', views.lecturer_schedule, name='lecturer_schedule'),
    path('lecturer/availability/', views.lecturer_availability, name='lecturer_availability'),
    path('lecturer/request-change/', views.lecturer_request_change, name='lecturer_request_change'),
    path('lecturer/tickets/', views.lecturer_my_tickets, name='lecturer_tickets'),

    # Student Public & Cohort Timetable
    path('student/timetable/', views.student_timetable, name='student_timetable'),
    path('student/export/', views.student_printable_export, name='student_export'),
    path('student/report-clash/', views.student_report_clash, name='student_report_clash'),

    # Real-Time Validation API
    path('api/validate-slot/', views.api_validate_slot, name='api_validate_slot'),
]
