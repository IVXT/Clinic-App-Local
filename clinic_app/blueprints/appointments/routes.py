from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import Blueprint, current_app, flash, g, redirect, request, url_for, jsonify

from clinic_app.services.appointments import (
    AppointmentError,
    AppointmentOverlap,
    AppointmentNotFound,
    create_appointment,
    doctor_choices,
    list_for_day,
    update_appointment,
    update_status,
    delete_appointment,
    get_appointment_by_id,
)
from clinic_app.services.doctor_colors import get_doctor_colors
from clinic_app.services.i18n import T
from clinic_app.services.security import require_permission
from clinic_app.services.ui import render_page
from clinic_app.services.errors import record_exception
from clinic_app.extensions import csrf
from clinic_app.services.csrf import ensure_csrf_token
from flask_wtf.csrf import validate_csrf
import json
from datetime import date, datetime, timedelta

bp = Blueprint("appointments", __name__)


def _selected_day() -> str:
    return request.args.get("day") or date.today().isoformat()


_RANGE_PRESETS = {
    "yesterday": -1,
    "today": 0,
    "tomorrow": 1,
    "next3": 3,
    "next7": 7,
    "all": None,
}

_SHOW_PRESETS = {"scheduled", "done", "all"}


def _resolve_range(day_str: str, key: str) -> tuple[str, str | None]:
    key = key if key in _RANGE_PRESETS else "today"
    span = _RANGE_PRESETS[key]
    if span is None:
        return key, None
    base = date.fromisoformat(day_str)
    end = base + timedelta(days=span)
    return key, end.isoformat()


def _search_query() -> str:
    return (request.args.get("q") or "").strip()


def _range_choices() -> list[tuple[str, str]]:
    return [
        ("yesterday", "Yesterday"),
        ("today", "Today"),
        ("tomorrow", "Tomorrow"),
        ("next3", "Next 3 Days"),
        ("next7", "Next 7 Days"),
        ("all", "All Dates"),
    ]


def _show_choices() -> list[tuple[str, str]]:
    return [
        ("scheduled", "Scheduled"),
        ("done", "Done"),
        ("all", "All Status"),
    ]


def _choice_label(value: str, choices: list[tuple[str, str]], fallback: str) -> str:
    for key, label in choices:
        if key == value:
            return label
    return fallback


_STATUS_ORDER = {
    "scheduled": 0,
    "checked_in": 1,
    "in_progress": 2,
    "done": 3,
    "no_show": 4,
    "cancelled": 5,
}


def _status_priority(status: str) -> int:
    return _STATUS_ORDER.get(status, 10)


def _group_table_appointments(appts: list[dict]) -> list[dict]:
    buckets: dict[str, dict] = {}
    for appt in appts:
        pid = appt.get("patient_id")
        key = pid or f"anon:{appt.get('patient_name')}:{appt.get('patient_phone') or ''}"
        bucket = buckets.setdefault(
            key,
            {
                "patient_id": pid,
                "patient_name": appt.get("patient_name") or "—",
                "patient_phone": appt.get("patient_phone"),
                "patient_short_id": appt.get("patient_short_id"),
                "appointments": [],
            },
        )
        bucket["appointments"].append(appt)

    groups: list[dict] = []
    for bucket in buckets.values():
        schedules = sorted(bucket["appointments"], key=lambda a: a["starts_at"])
        selected = min(
            schedules,
            key=lambda a: (_status_priority(a.get("status", "")), a["starts_at"]),
        )
        bucket["selected"] = selected
        time_display = selected.get("time_label") or format_time_range(selected["starts_at"], selected["ends_at"])
        bucket["time_display"] = time_display
        bucket["doctor_label"] = selected.get("doctor_label")
        bucket["extra_count"] = max(0, len(schedules) - 1)
        bucket["modal_payload"] = {
            "patient_name": bucket["patient_name"],
            "file_no": bucket["patient_short_id"] or "—",
            "phone": bucket["patient_phone"] or "—",
            "selected": {
                "doctor": bucket["doctor_label"],
                "time": time_display,
                "title": selected["title"],
                "status_label": T("appointment_status_" + selected["status"]),
                "notes": selected.get("notes") or "",
            },
            "schedules": [
                {
                    "id": ap["id"],
                    "title": ap["title"],
                    "doctor": ap["doctor_label"],
                    "time": ap.get("time_label") or format_time_range(ap["starts_at"], ap["ends_at"]),
                    "notes": ap.get("notes") or "",
                    "status": ap["status"],
                    "status_label": T("appointment_status_" + ap["status"]),
                    "edit_url": url_for("appointments.edit", appt_id=ap["id"]),
                }
                for ap in schedules
            ],
        }
        groups.append(bucket)

    groups.sort(key=lambda grp: grp["selected"]["starts_at"])
    return groups

@bp.route("/appointments", methods=["GET"], endpoint="index")
@require_permission("appointments:view")
def appointments_entrypoint():
    """Main appointments page - send users to the modern vanilla view."""
    try:
        return redirect(url_for("appointments.vanilla"))
    except Exception as exc:
        record_exception("appointments.index", exc)
        raise




@bp.route("/appointments/simple", methods=["GET"], endpoint="simple_view")
@require_permission("appointments:view")
def appointments_simple_view():
    """Simplified appointments view - single, clean interface."""
    try:
        print(f"DEBUG: Simple view called with args: {dict(request.args)}")
        day = _selected_day()
        doctor = request.args.get("doctor") or "all"
        search = _search_query()
        show_mode = (request.args.get("show") or "upcoming").lower()
        if show_mode not in _SHOW_PRESETS:
            show_mode = "upcoming"

        doctor_id = doctor if doctor != "all" else None
        print(f"DEBUG: day={day}, doctor={doctor}, doctor_id={doctor_id}, search={search}, show_mode={show_mode}")

        # Calculate navigation dates
        try:
            current_date = date.fromisoformat(day)
            previous_day = (current_date - timedelta(days=1)).isoformat()
            next_day = (current_date + timedelta(days=1)).isoformat()
            today = date.today().isoformat()
        except ValueError:
            # Invalid date format, use today
            current_date = date.today()
            day = current_date.isoformat()
            previous_day = (current_date - timedelta(days=1)).isoformat()
            next_day = (current_date + timedelta(days=1)).isoformat()
            today = day

        try:
            print("DEBUG: Calling list_for_day")
            appts = list_for_day(day, doctor_id=doctor_id, search=search or None, show=show_mode)
            print(f"DEBUG: list_for_day returned {len(appts)} appointments")
            status_counts: dict[str, int] = {}
            for appt in appts:
                status_counts[appt["status"]] = status_counts.get(appt["status"], 0) + 1
        except AppointmentError as exc:
            print(f"DEBUG: AppointmentError: {exc}")
            flash(T(str(exc)), "err")
            appts = []
        except Exception as exc:
            # Handle unexpected errors gracefully
            print(f"DEBUG: Exception in list_for_day: {exc}")
            import traceback
            traceback.print_exc()
            current_app.logger.error(f"Error listing appointments for day {day}: {exc}")
            flash("An error occurred while loading appointments. Please try again.", "err")
            appts = []

        try:
            doctors_list = doctor_choices()
            print(f"DEBUG: doctor_choices returned {len(doctors_list)} doctors")
        except Exception as exc:
            print(f"DEBUG: Exception in doctor_choices: {exc}")
            import traceback
            traceback.print_exc()
            current_app.logger.error(f"Error getting doctor choices: {exc}")
            doctors_list = []

        print("DEBUG: About to call render_page")
        return render_page(
            "appointments/simple_view.html",
            day=day,
            doctor=doctor,
            doctors=[("all", T("appointments_doctor_all"))] + doctors_list,
            appts=appts,
            selected_doctor=doctor,
            search=search,
            show=show_mode,
            previous_day=previous_day,
            next_day=next_day,
            today=today,
            end_day=None,  # Simple view shows single day
        )
    except Exception as exc:
        print(f"DEBUG: Exception in simple_view: {exc}")
        import traceback
        traceback.print_exc()
        record_exception("appointments.simple_view", exc)
        raise
@bp.route("/appointments/table", methods=["GET"], endpoint="table")
@require_permission("appointments:view")
def appointments_table():
    try:
        # Enhanced filtering and date grouping
        day = _selected_day()
        doctor = request.args.get("doctor") or "all"
        range_key = request.args.get("range") or "today"  # Default to today
        search = _search_query()
        show_mode = (request.args.get("show") or "all").lower()  # Default to all status
        date_from = request.args.get("date_from")
        date_to = request.args.get("date_to")
        is_range = request.args.get("is_range") == "true"

        if show_mode not in _SHOW_PRESETS:
            show_mode = "all"

        print(f"DEBUG: Table route - day={day}, doctor={doctor}, range={range_key}, search={search}, show={show_mode}")

        # Get doctors list and colors
        try:
            doctors_list = doctor_choices()
            doctor_colors = get_doctor_colors()
        except Exception as e:
            print(f"DEBUG: Error getting doctors: {e}")
            doctors_list = []
            doctor_colors = {}

        # Determine date range for filtering
        filter_start_date = None
        filter_end_date = None

        if range_key == "today":
            filter_start_date = day
            filter_end_date = day
        elif range_key == "yesterday":
            yesterday = (date.fromisoformat(day) - timedelta(days=1)).isoformat()
            filter_start_date = yesterday
            filter_end_date = yesterday
        elif range_key == "tomorrow":
            tomorrow = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
            filter_start_date = tomorrow
            filter_end_date = tomorrow
        elif range_key == "next3":
            filter_start_date = day
            filter_end_date = (date.fromisoformat(day) + timedelta(days=3)).isoformat()
        elif range_key == "next7":
            filter_start_date = day
            filter_end_date = (date.fromisoformat(day) + timedelta(days=7)).isoformat()
        elif range_key == "custom":
            if is_range and date_from and date_to:
                filter_start_date = date_from
                filter_end_date = date_to
            elif date_from:
                filter_start_date = date_from
                filter_end_date = date_from

        # Get appointments with enhanced filtering
        try:
            # Get appointments based on date range first
            if range_key == "all":
                # For "all dates", get all appointments without date filtering
                appts = list_for_day("2000-01-01", doctor_id=doctor if doctor != "all" else None,
                                   end_day="2030-12-31", search=search or None, show="all")
            else:
                appts = list_for_day(filter_start_date, doctor_id=doctor if doctor != "all" else None,
                                   end_day=filter_end_date, search=search or None, show="all")

            # Apply status filter manually (since list_for_day only supports time-based filtering)
            if show_mode == "scheduled":
                appts = [appt for appt in appts if appt.get("status") == "scheduled"]
            elif show_mode == "done":
                appts = [appt for appt in appts if appt.get("status") == "done"]
            # For "all", keep all appointments

            print(f"DEBUG: Got {len(appts)} appointments after filtering")
        except Exception as e:
            print(f"DEBUG: Error getting appointments: {e}")
            appts = []

        # Group appointments by date
        appointments_by_date = {}
        for appt in appts:
            if appt.get('starts_at'):
                date_key = appt['starts_at'][:10]  # YYYY-MM-DD
                if date_key not in appointments_by_date:
                    appointments_by_date[date_key] = []
                appointments_by_date[date_key].append(appt)

        # Sort dates and prepare date groups
        date_groups = []
        for date_key in sorted(appointments_by_date.keys()):
            appointments = appointments_by_date[date_key]

            # Sort appointments within each date by time (earliest to latest)
            # Use proper datetime parsing to ensure correct AM/PM handling
            def time_sort_key(appt):
                starts_at = appt.get('starts_at', '')
                if starts_at:
                    try:
                        # Parse the full datetime string for accurate sorting
                        dt = datetime.fromisoformat(starts_at.replace('Z', '+00:00'))
                        return dt.time()  # Sort by time of day only
                    except (ValueError, AttributeError):
                        return starts_at  # Fall back to string sorting
                return ''

            appointments.sort(key=time_sort_key)
            print(f"DEBUG: After sorting {len(appointments)} appointments for {date_key}:")
            for i, appt in enumerate(appointments):
                starts_at = appt.get('starts_at', '')
                time_display = starts_at[11:16] if len(starts_at) > 16 else starts_at
                hour = int(time_display[:2]) if time_display else 0
                ampm = 'AM' if hour < 12 else 'PM'
                display_hour = hour if hour == 0 else (hour - 12 if hour > 12 else hour)
                display_hour = 12 if display_hour == 0 else display_hour
                print(f"DEBUG:   {i+1}. {time_display} ({display_hour}:00 {ampm}) - {appt.get('title', 'No title')}")

            # Count by status
            status_counts = {'scheduled': 0, 'done': 0, 'total': len(appointments)}
            for appt in appointments:
                status = appt.get('status', 'scheduled')
                if status in status_counts:
                    status_counts[status] += 1

            # Format date display
            try:
                date_obj = date.fromisoformat(date_key)
                today = date.today()
                if date_key == today.isoformat():
                    date_display = "Today"
                elif date_key == (today - timedelta(days=1)).isoformat():
                    date_display = "Yesterday"
                elif date_key == (today + timedelta(days=1)).isoformat():
                    date_display = "Tomorrow"
                else:
                    date_display = date_obj.strftime("%B %d, %Y")
            except:
                date_display = date_key

            date_groups.append({
                'date': date_key,
                'display': date_display,
                'appointments': appointments,
                'counts': status_counts,
                'is_today': date_key == date.today().isoformat()
            })

        # Sort date groups chronologically (past to future) for all ranges
        date_groups.sort(key=lambda group: group['date'])

        # Generate stats for enhanced template
        stats = []
        total_appointments = len(appts)
        if total_appointments > 0:
            stats = [
                ("Total Appointments", total_appointments),
            ]

        # Generate selected doctor label
        selected_doctor_label = None
        for doc_id, doc_label in doctors_list:
            if str(doc_id) == str(doctor):
                selected_doctor_label = doc_label
                break

        # Prepare date groups for card view
        date_groups = []
        for date_key in sorted(appointments_by_date.keys()):
            appointments = appointments_by_date[date_key]
            appointments.sort(key=lambda appt: appt.get('starts_at', ''))

            # Count scheduled vs done
            scheduled_count = sum(1 for appt in appointments if appt.get('status') == 'scheduled')
            done_count = sum(1 for appt in appointments if appt.get('status') == 'done')

            try:
                date_obj = date.fromisoformat(date_key)
                today = date.today()
                if date_key == today.isoformat():
                    date_display = "Today"
                elif date_key == (today - timedelta(days=1)).isoformat():
                    date_display = "Yesterday"
                elif date_key == (today + timedelta(days=1)).isoformat():
                    date_display = "Tomorrow"
                else:
                    date_display = date_obj.strftime("%A, %B %d, %Y")
            except:
                date_display = date_key

            date_groups.append({
                'date': date_key,
                'display': date_display,
                'appointments': appointments,
                'scheduled_count': scheduled_count,
                'done_count': done_count,
                'total_count': len(appointments),
                'is_today': date_key == date.today().isoformat()
            })

        return render_page(
            "appointments/card_view.html",
            day=day,
            end_day=filter_end_date if filter_end_date != filter_start_date else None,
            doctors=[("all", T("appointments_doctor_all"))] + doctors_list,
            doctor_colors=doctor_colors,
            selected_doctor=doctor,
            selected_doctor_label=selected_doctor_label,
            show=show_mode,
            search=search,
            date_groups=date_groups,
            stats=stats,
        )
    except Exception as exc:
        print(f"DEBUG: Exception in table route: {exc}")
        import traceback
        traceback.print_exc()
        record_exception("appointments.table", exc)
        raise


@bp.route("/appointments/new", methods=["GET", "POST"], endpoint="new")
@require_permission("appointments:edit")
def new_appointment():
    try:
        day = request.args.get("day") or date.today().isoformat()
        doctor = request.args.get("doctor") or doctor_choices()[0][0]
        appointment_id = request.form.get("appointment_id") if request.method == "POST" else request.args.get("appointment_id")
        editing = bool(appointment_id)
        patient_card = None
        existing = None
        if editing:
            from clinic_app.services.appointments import get_appointment_by_id

            existing = get_appointment_by_id(appointment_id)
            if existing:
                day = existing["starts_at"][:10]
                doctor = existing["doctor_id"]
                patient_card = {
                    "id": existing.get("patient_id"),
                    "name": existing.get("patient_name"),
                    "phone": existing.get("patient_phone"),
                    "short_id": existing.get("patient_short_id"),
                }
            else:
                editing = False
                appointment_id = None
        if request.method == "POST":
            try:
                actor = getattr(g, "current_user", None)
                if appointment_id:
                    update_appointment(appointment_id, request.form.to_dict(), actor_id=getattr(actor, "id", None))
                else:
                    appointment_id = create_appointment(request.form.to_dict(), actor_id=getattr(actor, "id", None))
                flash(T("appointments_submit"), "ok")
                return redirect(url_for("appointments.index", day=request.form.get("day") or day))
            except AppointmentOverlap:
                flash(T("appointment_conflict"), "err")
                form_defaults = request.form.to_dict()
                card_ctx = patient_card
                if not card_ctx and form_defaults.get("patient_id"):
                    card_ctx = {
                        "id": form_defaults.get("patient_id"),
                        "name": form_defaults.get("patient_name"),
                        "phone": form_defaults.get("patient_phone"),
                        "short_id": form_defaults.get("patient_short_id"),
                    }
                return (
                    render_page(
                        "appointments/form.html",
                        doctors=doctor_choices(),
                        defaults=form_defaults,
                        editing=editing,
                        patient_card=card_ctx,
                        show_back=True,
                    ),
                    409,
                )
            except AppointmentError as exc:
                flash(T(str(exc)), "err")
                form_defaults = request.form.to_dict()
                card_ctx = patient_card
                if not card_ctx and form_defaults.get("patient_id"):
                    card_ctx = {
                        "id": form_defaults.get("patient_id"),
                        "name": form_defaults.get("patient_name"),
                        "phone": form_defaults.get("patient_phone"),
                        "short_id": form_defaults.get("patient_short_id"),
                    }
                return (
                    render_page(
                        "appointments/form.html",
                        doctors=doctor_choices(),
                        defaults=form_defaults,
                        editing=editing,
                        patient_card=card_ctx,
                        show_back=True,
                    ),
                    400,
                )
            except AppointmentNotFound:
                flash(T("appointment_not_found") if T("appointment_not_found") != "appointment_not_found" else "Appointment not found", "err")
                return redirect(url_for("appointments.index", day=day))
        defaults = {
            "day": day,
            "start_time": request.args.get("start_time") or "09:00",
            "doctor_id": doctor,
            "appointment_id": appointment_id,
        }
        if existing:
            defaults.update(
                {
                    "start_time": existing["starts_at"][11:16],
                    "doctor_id": existing["doctor_id"],
                    "title": existing.get("title"),
                    "notes": existing.get("notes"),
                    "patient_id": existing.get("patient_id"),
                    "patient_name": existing.get("patient_name"),
                    "patient_phone": existing.get("patient_phone"),
                    "patient_short_id": existing.get("patient_short_id"),
                }
            )
        if not patient_card and defaults.get("patient_id"):
            patient_card = {
                "id": defaults.get("patient_id"),
                "name": defaults.get("patient_name"),
                "phone": defaults.get("patient_phone"),
                "short_id": defaults.get("patient_short_id"),
            }
        return render_page(
            "appointments/form.html",
            doctors=doctor_choices(),
            defaults=defaults,
            editing=editing,
            patient_card=patient_card,
            show_back=True,
        )
    except Exception as exc:
        record_exception("appointments.new", exc)
        raise


@bp.route("/appointments/<appt_id>/status", methods=["POST"], endpoint="status")
@require_permission("appointments:edit")
def change_status(appt_id):
    try:
        print(f"DEBUG: Status change request for appointment {appt_id}")
        print(f"DEBUG: Request method: {request.method}")
        print(f"DEBUG: Request form data: {dict(request.form)}")

        new_status = request.form.get("status") or "scheduled"
        print(f"DEBUG: New status: {new_status}")

        try:
            update_status(appt_id, new_status)
            print(f"DEBUG: Status update successful")
            # JSON/Fetch clients
            wants_json = request.is_json or "application/json" in (request.headers.get("Accept") or "")
            if wants_json:
                return jsonify({"ok": True, "status": new_status})
            flash(T("appointment_status_" + new_status), "ok")
        except AppointmentError as exc:
            print(f"DEBUG: AppointmentError: {exc}")
            wants_json = request.is_json or "application/json" in (request.headers.get("Accept") or "")
            if wants_json:
                return jsonify({"ok": False, "error": str(exc)}), 400
            flash(T(str(exc)), "err")
        return redirect(request.form.get("next") or url_for("appointments.index"))
    except Exception as exc:
        print(f"DEBUG: Exception in status change: {exc}")
        import traceback
        traceback.print_exc()
        record_exception("appointments.status", exc)
        wants_json = request.is_json or "application/json" in (request.headers.get("Accept") or "")
        if wants_json:
            return jsonify({"ok": False, "error": "server_error"}), 500
        raise


@bp.route("/appointments/<appt_id>/delete", methods=["POST"], endpoint="delete")
@require_permission("appointments:edit")
def delete_appointment(appt_id):
    try:
        # Import here to avoid circular imports
        from clinic_app.services.appointments import get_appointment_by_id, delete_appointment as delete_appt
        
        appointment = get_appointment_by_id(appt_id)
        if not appointment:
            flash("Appointment not found", "err")
            return redirect(request.form.get("next") or url_for("appointments.index"))
        
        try:
            delete_appt(appt_id)
            flash(f"Appointment for {appointment['patient_name']} has been deleted", "ok")
        except AppointmentError as exc:
            flash(T(str(exc)), "err")
        return redirect(request.form.get("next") or url_for("appointments.index"))
    except Exception as exc:
        record_exception("appointments.delete", exc)
        flash("Failed to delete appointment", "err")
        return redirect(request.form.get("next") or url_for("appointments.index"))


@bp.route("/appointments/<appt_id>/edit", methods=["GET"], endpoint="edit")
@require_permission("appointments:edit")
def edit_appointment(appt_id):
    try:
        # Import here to avoid circular imports
        from clinic_app.services.appointments import get_appointment_by_id

        appointment = get_appointment_by_id(appt_id)
        if not appointment:
            flash("Appointment not found", "err")
            return redirect(url_for("appointments.index"))

        # Redirect to the existing form with pre-filled data
        return redirect(url_for("appointments.new",
                              day=appointment['starts_at'][:10],
                              doctor=appointment['doctor_id'],
                              appointment_id=appt_id))
    except Exception as exc:
        record_exception("appointments.edit", exc)
        flash("Failed to load appointment for editing", "err")
        return redirect(url_for("appointments.index"))





# Vanilla appointments template route
@bp.route("/appointments/vanilla", methods=["GET"], endpoint="vanilla")
@require_permission("appointments:view")
def appointments_vanilla():
    """Serve vanilla appointments template with data injection."""
    try:
        # Fetch appointments for a rolling 30-day window (past week through next 3 weeks)
        today = datetime.now().date()
        start_day = today - timedelta(days=7)
        end_day = today + timedelta(days=21)
        appointments = list_for_day(
            start_day.strftime("%Y-%m-%d"),
            end_day=end_day.strftime("%Y-%m-%d"),
            show="all",
        )
        doctors = doctor_choices()

        # Get patients for search using direct database query
        from clinic_app.services.database import db

        conn = db()
        try:
            patients_rows = conn.execute("""
                SELECT id, short_id, full_name, phone
                FROM patients
                ORDER BY full_name
                LIMIT 100
            """).fetchall()
            conn.close()
        except:
            patients_rows = []
            if 'conn' in locals():
                conn.close()

        # Format appointments for template
        status_map = {
            "scheduled": "Scheduled",
            "checked_in": "Pending",
            "in_progress": "Pending",
            "pending": "Pending",
            "cancelled": "Cancelled",
            "canceled": "Cancelled",
            "done": "Done",
            "complete": "Done",
        }

        formatted_appts = []
        for appt in appointments:
            status_code = (appt.get("status") or "scheduled").lower()
            formatted_appts.append({
                "id": appt["id"],
                "patientName": appt.get("patient_name") or "",
                "fileNumber": appt.get("patient_short_id") or "",
                "phoneNumber": appt.get("patient_phone") or "",
                "doctor": appt.get("doctor_label") or appt.get("doctor_id") or "",
                "startTime": appt.get("starts_at") or "",
                "endTime": appt.get("ends_at") or "",
                "status": status_map.get(status_code, "Scheduled"),
                "reason": appt.get("title") or "",
            })

        # Format patients for template
        formatted_patients = []
        for patient in patients_rows:
            formatted_patients.append({
                "fileNumber": patient["short_id"] or "",
                "name": patient["full_name"] or "",
                "phoneNumber": patient["phone"] or "",
                "id": patient["id"],
            })

        # Format doctors for template (simple list where index 0 is the "All Doctors" label).
        formatted_doctors = ["All Doctors"]
        for doc_id, doc_name in doctors:
            formatted_doctors.append(doc_name)

        # Render the template with injected data
        return render_page(
            "appointments/vanilla.html",
            appointments_json=json.dumps(formatted_appts),
            patients_json=json.dumps(formatted_patients),
            doctors_json=json.dumps(formatted_doctors),
        )

    except Exception as exc:
        record_exception("appointments.vanilla", exc)
        # Return template with empty data arrays so frontend can still load gracefully
        return render_page(
            "appointments/vanilla.html",
            appointments_json=json.dumps([]),
            patients_json=json.dumps([]),
            doctors_json=json.dumps(["All Doctors"]),
        ), 500


# API endpoints for vanilla template
@csrf.exempt
@bp.route("/api/patients/search", methods=["GET"])
@require_permission("patients:view")
def api_search_patients():
    """Search patients by name, file number or phone."""
    try:
        query = request.args.get('q', '').strip()
        if len(query) < 2:
            return jsonify([]), 200

        # Search in database
        from clinic_app.services.database import db

        conn = db()
        try:
            rows = conn.execute("""
                SELECT id, short_id, full_name, phone
                FROM patients
                WHERE LOWER(full_name) LIKE LOWER(?)
                   OR LOWER(short_id) LIKE LOWER(?)
                   OR phone LIKE ?
                ORDER BY full_name
                LIMIT 10
            """, (f'%{query}%', f'%{query}%', f'%{query}%')).fetchall()
            conn.close()
        except:
            if 'conn' in locals():
                conn.close()
            rows = []

        # Convert to JSON format expected by frontend
        results = []
        for row in rows:
            results.append({
                'id': row['id'],
                'name': row['full_name'],
                'fileNumber': row['short_id'],
                'phoneNumber': row['phone']
            })

        return jsonify(results), 200

    except Exception as exc:
        record_exception("api.patients.search", exc)
        return jsonify({"error": "Internal server error"}), 500

@csrf.exempt
@bp.route("/api/appointments/add", methods=["POST"])
@require_permission("appointments:edit")
def api_add_appointment():
    """API endpoint to add new appointment."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        # Map template fields to service fields
        form_data = {
            "day": data.get("startTime", datetime.now().strftime("%Y-%m-%d"))[:10],
            "start_time": data.get("startTime", "")[11:16] if len(data.get("startTime", "")) > 11 else "09:00",
            "doctor_id": data.get("doctor", ""),
            "title": data.get("reason", ""),
            "patient_id": data.get("patient_id"),
            "patient_name": data.get("patientName"),
            "patient_phone": data.get("phoneNumber"),
        }

        appt_id = create_appointment(form_data, actor_id=getattr(g.current_user, "id", None))
        return jsonify({"id": appt_id, "status": "created"}), 201

    except AppointmentOverlap as e:
        return jsonify({"error": "Time slot conflict"}), 409
    except AppointmentError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as exc:
        record_exception("api.appointments.add", exc)
        return jsonify({"error": "Internal server error"}), 500


@csrf.exempt
@bp.route("/api/appointments/edit/<appt_id>", methods=["PUT"])
@require_permission("appointments:edit")
def api_edit_appointment(appt_id):
    """API endpoint to edit existing appointment."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400

        # Map template fields to service fields
        form_data = {
            "day": data.get("startTime", "")[:10],
            "start_time": data.get("startTime", "")[11:16] if len(data.get("startTime", "")) > 11 else "09:00",
            "doctor_id": data.get("doctor", ""),
            "title": data.get("reason", ""),
            "notes": data.get("notes", ""),
            "status": data.get("status", "scheduled"),
        }

        update_appointment(appt_id, form_data, actor_id=getattr(g.current_user, "id", None))
        return jsonify({"id": appt_id, "status": "updated"}), 200

    except AppointmentOverlap as e:
        return jsonify({"error": "Time slot conflict"}), 409
    except AppointmentNotFound:
        return jsonify({"error": "Appointment not found"}), 404
    except AppointmentError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as exc:
        record_exception("api.appointments.edit", exc)
        return jsonify({"error": "Internal server error"}), 500


@csrf.exempt
@bp.route("/api/appointments/status/<appt_id>", methods=["PATCH"])
@require_permission("appointments:edit")
def api_update_status(appt_id):
    """API endpoint to update appointment status."""
    try:
        data = request.get_json()
        if not data or "status" not in data:
            return jsonify({"error": "Status required"}), 400

        update_status(appt_id, data["status"])
        return jsonify({"id": appt_id, "status": data["status"]}), 200

    except AppointmentNotFound:
        return jsonify({"error": "Appointment not found"}), 404
    except AppointmentError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as exc:
        record_exception("api.appointments.status", exc)
        return jsonify({"error": "Internal server error"}), 500


@csrf.exempt
@bp.route("/api/appointments/delete/<appt_id>", methods=["DELETE"])
@require_permission("appointments:edit")
def api_delete_appointment(appt_id):
    """API endpoint to delete appointment."""
    try:
        delete_appt(appt_id)
        return jsonify({"message": "Appointment deleted"}), 200

    except AppointmentNotFound:
        return jsonify({"error": "Appointment not found"}), 404
    except AppointmentError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as exc:
        record_exception("api.appointments.delete", exc)
        return jsonify({"error": "Internal server error"}), 500
