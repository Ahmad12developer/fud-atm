"""
Management command to seed Federal University Dutse (FUD) ATMS with realistic production data.
"""
from datetime import time
from django.core.management.base import BaseCommand
from django.db import transaction
from timetable.models import (
    AcademicSession, Faculty, Department, User, TimeSlot,
    Venue, Course, Lecturer, LecturerAvailability, Timetable,
    Allocation, OptimizationSetting, InterAdminMessage, AuditLog,
    ChangeRequest
)


class Command(BaseCommand):
    help = "Seeds FUD ATMS database with institutional academic schemas and seed accounts."

    def handle(self, *args, **options):
        self.stdout.write("Seeding Federal University Dutse (FUD) ATMS data...")

        with transaction.atomic():
            # 1. Academic Session
            session, _ = AcademicSession.objects.get_or_create(
                name="2025/2026",
                defaults={'is_current': True}
            )

            # 2. Canonical TimeSlots
            slots_data = [
                (1, time(8, 0), time(10, 0), "08:00 - 10:00"),
                (2, time(10, 0), time(12, 0), "10:00 - 12:00"),
                (3, time(12, 0), time(14, 0), "12:00 - 14:00"),
                (4, time(14, 0), time(16, 0), "14:00 - 16:00"),
                (5, time(16, 0), time(18, 0), "16:00 - 18:00"),
            ]
            slots = {}
            for idx, st, et, lbl in slots_data:
                ts, _ = TimeSlot.objects.get_or_create(
                    index=idx,
                    defaults={'start_time': st, 'end_time': et, 'label': lbl}
                )
                slots[idx] = ts

            # 3. Faculties
            f_comp, _ = Faculty.objects.get_or_create(code="COMP", defaults={'name': "Faculty of Computing & Information Technology"})
            f_sci, _ = Faculty.objects.get_or_create(code="SCI", defaults={'name': "Faculty of Science"})
            f_agr, _ = Faculty.objects.get_or_create(code="AGR", defaults={'name': "Faculty of Agriculture"})
            f_arts, _ = Faculty.objects.get_or_create(code="ARTS", defaults={'name': "Faculty of Arts & Social Sciences"})
            f_mgt, _ = Faculty.objects.get_or_create(code="MGT", defaults={'name': "Faculty of Management Sciences"})

            # 4. Departments
            d_csc, _ = Department.objects.get_or_create(faculty=f_comp, code="CSC", defaults={'name': "Computer Science"})
            d_se, _ = Department.objects.get_or_create(faculty=f_comp, code="SE", defaults={'name': "Software Engineering"})
            d_cyb, _ = Department.objects.get_or_create(faculty=f_comp, code="CYB", defaults={'name': "Cybersecurity"})
            d_it, _ = Department.objects.get_or_create(faculty=f_comp, code="IT", defaults={'name': "Information Technology"})

            # 5. Venues
            v_ag, _ = Venue.objects.get_or_create(
                code="LT-AG",
                defaults={'name': "Abubakar Gimba Lecture Theatre", 'capacity': 350, 'faculty': None, 'is_active': True}
            )
            v_ta, _ = Venue.objects.get_or_create(
                code="TWIN-A",
                defaults={'name': "Faculty Twin Lecture Theatre A", 'capacity': 200, 'faculty': f_comp, 'is_active': True}
            )
            v_tb, _ = Venue.objects.get_or_create(
                code="TWIN-B",
                defaults={'name': "Faculty Twin Lecture Theatre B", 'capacity': 200, 'faculty': f_comp, 'is_active': True}
            )
            v_lab, _ = Venue.objects.get_or_create(
                code="LAB-PTDF",
                defaults={'name': "PTDF Software Engineering Lab", 'capacity': 80, 'faculty': f_comp, 'is_active': True}
            )
            v_h4, _ = Venue.objects.get_or_create(
                code="HALL-4",
                defaults={'name': "Faculty Lecture Hall 4", 'capacity': 100, 'faculty': f_comp, 'is_active': True}
            )

            # 6. Users (Central Admin, Faculty Admin, Lecturer, Student)
            password = "FudPass@2025"

            # Central Admin
            u_central, _ = User.objects.get_or_create(
                institutional_id="FUD/ADM/2024/001",
                defaults={
                    'first_name': "Engr. Dr. A. S.",
                    'last_name': "Dutse",
                    'email': "admin.central@fud.edu.ng",
                    'role': User.Role.CENTRAL_ADMIN
                }
            )
            u_central.set_password(password)
            u_central.save()

            # Faculty Admin
            u_fac_admin, _ = User.objects.get_or_create(
                institutional_id="FUD/SCI/2024/014",
                defaults={
                    'first_name': "Dr. Aminu Sani",
                    'last_name': "Dutse",
                    'email': "fcl.computing@fud.edu.ng",
                    'role': User.Role.FACULTY_ADMIN,
                    'faculty': f_comp
                }
            )
            u_fac_admin.set_password(password)
            u_fac_admin.save()

            # Lecturer 1 (Dr. Aminu Sani Dutse)
            u_lec_aminu, _ = User.objects.get_or_create(
                institutional_id="FUD/LEC/2024/088",
                defaults={
                    'first_name': "Dr. Aminu Sani",
                    'last_name': "Dutse",
                    'email': "aminu.dutse@fud.edu.ng",
                    'role': User.Role.LECTURER,
                    'faculty': f_comp,
                    'department': d_csc
                }
            )
            u_lec_aminu.set_password(password)
            u_lec_aminu.save()

            # Lecturer 2 (Mal. Kabiru Haruna)
            u_lec_kabiru, _ = User.objects.get_or_create(
                institutional_id="FUD/LEC/2024/104",
                defaults={
                    'first_name': "Mal. Kabiru",
                    'last_name': "Haruna",
                    'email': "k.haruna@fud.edu.ng",
                    'role': User.Role.LECTURER,
                    'faculty': f_comp,
                    'department': d_se
                }
            )
            u_lec_kabiru.set_password(password)
            u_lec_kabiru.save()

            # Lecturer 3 (Prof. Bello Dutse)
            u_lec_bello, _ = User.objects.get_or_create(
                institutional_id="FUD/LEC/2024/012",
                defaults={
                    'first_name': "Prof. Bello",
                    'last_name': "Dutse",
                    'email': "b.dutse@fud.edu.ng",
                    'role': User.Role.LECTURER,
                    'faculty': f_comp,
                    'department': d_csc
                }
            )
            u_lec_bello.set_password(password)
            u_lec_bello.save()

            # Lecturer Profiles
            l_aminu, _ = Lecturer.objects.get_or_create(
                user=u_lec_aminu,
                defaults={'staff_id': "FUD/STAFF/088", 'department': d_csc, 'max_hours_per_week': 12}
            )
            l_kabiru, _ = Lecturer.objects.get_or_create(
                user=u_lec_kabiru,
                defaults={'staff_id': "FUD/STAFF/104", 'department': d_se, 'max_hours_per_week': 12}
            )
            l_bello, _ = Lecturer.objects.get_or_create(
                user=u_lec_bello,
                defaults={'staff_id': "FUD/STAFF/012", 'department': d_csc, 'max_hours_per_week': 8}
            )

            # Student
            u_student, _ = User.objects.get_or_create(
                institutional_id="FUD/CST/21/0456",
                defaults={
                    'first_name': "Fatima",
                    'last_name': "Bello",
                    'email': "f.bello@fud.edu.ng",
                    'role': User.Role.STUDENT,
                    'faculty': f_comp,
                    'department': d_csc,
                    'level': 300
                }
            )
            u_student.set_password(password)
            u_student.save()

            # 7. Courses
            c_301, _ = Course.objects.get_or_create(
                code="CSC 301",
                defaults={'title': "Structured Systems Analysis & Design", 'credit_units': 3, 'contact_hours': 2, 'department': d_csc, 'level': 300, 'semester': 1, 'expected_capacity': 185}
            )
            c_305, _ = Course.objects.get_or_create(
                code="CSC 305",
                defaults={'title': "Database Systems Architecture", 'credit_units': 3, 'contact_hours': 2, 'department': d_csc, 'level': 300, 'semester': 1, 'expected_capacity': 190}
            )
            c_307, _ = Course.objects.get_or_create(
                code="CSC 307",
                defaults={'title': "Algorithms & Complexity Analysis", 'credit_units': 3, 'contact_hours': 2, 'department': d_csc, 'level': 300, 'semester': 1, 'expected_capacity': 180}
            )
            c_309, _ = Course.objects.get_or_create(
                code="CSC 309",
                defaults={'title': "Artificial Intelligence & Expert Systems", 'credit_units': 3, 'contact_hours': 2, 'department': d_csc, 'level': 300, 'semester': 1, 'expected_capacity': 170}
            )
            c_311, _ = Course.objects.get_or_create(
                code="CSC 311",
                defaults={'title': "Operating Systems Practical Lab", 'credit_units': 2, 'contact_hours': 2, 'department': d_csc, 'level': 300, 'semester': 1, 'expected_capacity': 80}
            )
            c_se301, _ = Course.objects.get_or_create(
                code="SE 301",
                defaults={'title': "Software Architecture & Design Patterns", 'credit_units': 3, 'contact_hours': 2, 'department': d_se, 'level': 300, 'semester': 1, 'expected_capacity': 140}
            )
            c_cyb301, _ = Course.objects.get_or_create(
                code="CYB 301",
                defaults={'title': "Network Security & Cryptography", 'credit_units': 3, 'contact_hours': 2, 'department': d_cyb, 'level': 300, 'semester': 1, 'expected_capacity': 150}
            )

            # 8. Timetable for Faculty of Computing
            tt, _ = Timetable.objects.get_or_create(
                session=session,
                semester=1,
                faculty=f_comp,
                defaults={'status': Timetable.Status.FACULTY_APPROVED}
            )

            # 9. Baseline 0-Conflict Allocations
            # Clear and create clean sample allocations
            Allocation.objects.filter(timetable=tt).delete()
            allocations_data = [
                # Mon 08:00 - 10:00 (slot 1): CSC 301 @ LT-AG (Dr. Aminu)
                (c_301, l_aminu, v_ag, 0, slots[1]),
                # Mon 10:00 - 12:00 (slot 2): CSC 305 @ TWIN-A (Mal. Kabiru)
                (c_305, l_kabiru, v_ta, 0, slots[2]),
                # Mon 14:00 - 16:00 (slot 4): CSC 311 @ LAB-PTDF (Mal. Kabiru)
                (c_311, l_kabiru, v_lab, 0, slots[4]),
                # Tue 08:00 - 10:00 (slot 1): SE 301 @ TWIN-B (Mal. Kabiru)
                (c_se301, l_kabiru, v_tb, 1, slots[1]),
                # Tue 14:00 - 16:00 (slot 4): CSC 307 @ TWIN-A (Dr. Aminu)
                (c_307, l_aminu, v_ta, 1, slots[4]),
                # Thu 10:00 - 12:00 (slot 2): CYB 301 @ LT-AG (Dr. Aminu)
                (c_cyb301, l_aminu, v_ag, 3, slots[2]),
                # Fri 08:00 - 10:00 (slot 1): CSC 309 @ TWIN-B (Prof. Bello)
                (c_309, l_bello, v_tb, 4, slots[1]),
            ]
            for c, l, v, day, s in allocations_data:
                Allocation.objects.create(
                    timetable=tt,
                    course=c,
                    lecturer=l,
                    venue=v,
                    day_of_week=day,
                    slot=s
                )

            # 10. Lecturer Availabilities
            for d in range(5):
                for s_idx in range(1, 6):
                    # Default available except Friday prayer (slot 3)
                    is_avail = not (d == 4 and s_idx == 3)
                    LecturerAvailability.objects.get_or_create(
                        lecturer=l_aminu,
                        day_of_week=d,
                        slot=slots[s_idx],
                        defaults={'is_available': is_avail}
                    )

            # 11. Optimization Setting
            OptimizationSetting.objects.get_or_create(
                id=1,
                defaults={
                    'weight_student_gap': 85,
                    'weight_lecturer_pref': 90,
                    'weight_travel_dist': 75,
                    'weight_load_dist': 80,
                    'friday_hard_lock': True
                }
            )

            # 12. Inter-Admin Communications
            InterAdminMessage.objects.get_or_create(
                sender=u_fac_admin,
                faculty=f_comp,
                message="Submitted 2025/2026 Harmattan schedule matrix for Computing. Zero hard conflicts detected across all level cohorts.",
                defaults={'priority': 'ROUTINE'}
            )
            InterAdminMessage.objects.get_or_create(
                sender=u_central,
                faculty=f_comp,
                message="Abubakar Gimba Theatre allocation verified. Faculty schedule approved for central university publication.",
                defaults={'priority': 'ROUTINE'}
            )

            # 13. Audit Log Entries
            AuditLog.objects.create(
                user=u_central,
                action="TIMETABLE_SEED",
                entity_type="SYSTEM",
                entity_id="FUD-ATMS-INIT",
                ip_address="127.0.0.1",
                details={'event': "Institutional baseline entities seeded successfully."}
            )

        self.stdout.write(self.style.SUCCESS("Successfully seeded FUD ATMS database."))
