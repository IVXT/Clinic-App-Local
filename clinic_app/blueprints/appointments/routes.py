from __future__ import annotations

import datetime
from collections import defaultdict
from datetime import date, timedelta
from uuid import uuid4

from flask import Blueprint, current_app, flash, g, redirect, request, url_for, jsonify, abort
from sqlalchemy import or_, text, select
from sqlalchemy.orm import selectinload

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
from clinic_app.extensions import csrf, db
from clinic_app.services.csrf import ensure_csrf_token
from flask_wtf.csrf import validate_csrf
from clinic_app.models import Appointment as AppointmentModel, Patient as PatientModel, Doctor as DoctorModel
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
def _ensure_doctor_records() -> None:
    """Ensure doctors table exists and matches configured doctors."""
    engine = db.engine
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS doctors (
                    id TEXT PRIMARY KEY,
                    doctor_label TEXT NOT NULL,
                    color TEXT
                )
                """
            )
        )

    session = db.session()
    existing = {doc.id: doc for doc in session.query(DoctorModel).all()}
    colors = get_doctor_colors()

    for slug, label in doctor_choices():
        if not slug or slug == "all":
            continue
        doc = existing.get(slug)
        color = colors.get(slug)
        if doc:
            updated = False
            if doc.doctor_label != label:
                doc.doctor_label = label
                updated = True
            if color and doc.color != color:
                doc.color = color
                updated = True
            if updated:
                session.add(doc)
        else:
            session.add(DoctorModel(id=slug, doctor_label=label, color=color))

    # Backfill any doctor ids already referenced in appointments
    seen_ids = set(existing.keys())
    rows = session.execute(
        select(AppointmentModel.doctor_id, AppointmentModel.doctor_label).distinct()
    ).all()
    for doc_id, doc_label in rows:
        if not doc_id or doc_id == "all" or doc_id in seen_ids:
            continue
        session.add(
            DoctorModel(
                id=doc_id,
                doctor_label=doc_label or doc_id,
                color=colors.get(doc_id),
            )
        )
        seen_ids.add(doc_id)

    session.commit()


@bp.route("/appointments/vanilla", methods=["GET"], endpoint="vanilla")
@require_permission("appointments:view")
def appointments_vanilla():
    """Render the server-side appointments dashboard."""
    try:
        _ensure_doctor_records()

        today = datetime.date.today()
        today_str = today.isoformat()
        yesterday_str = (today - datetime.timedelta(days=1)).isoformat()
        tomorrow_str = (today + datetime.timedelta(days=1)).isoformat()

        use_range = request.args.get("use_range")
        search_term = (request.args.get("search_term") or "").strip()
        doctor_id = request.args.get("doctor_id")
        start_date_str = request.args.get("start_date")
        end_date_str = request.args.get("end_date")

        query = (
            AppointmentModel.query.options(
                selectinload(AppointmentModel.patient),
                selectinload(AppointmentModel.doctor),
            )
            .join(PatientModel)
            .outerjoin(DoctorModel)
        )

        if start_date_str:
            start_dt = datetime.datetime.fromisoformat(start_date_str)
            query = query.filter(AppointmentModel.start_time >= start_dt)
            if use_range == "on" and end_date_str:
                end_dt = datetime.datetime.fromisoformat(end_date_str) + datetime.timedelta(days=1)
            else:
                end_dt = datetime.datetime.fromisoformat(start_date_str) + datetime.timedelta(days=1)
            query = query.filter(AppointmentModel.start_time < end_dt)

        if doctor_id and doctor_id != "all":
            query = query.filter(AppointmentModel.doctor_id == doctor_id)

        if search_term:
            like = f"%{search_term}%"
            query = query.filter(
                or_(
                    PatientModel.full_name.ilike(like),
                    PatientModel.phone.ilike(like),
                    PatientModel.short_id.ilike(like),
                )
            )

        filtered_appts = query.order_by(AppointmentModel.start_time.asc()).all()

        grouped_appointments: dict[str, list[AppointmentModel]] = defaultdict(list)
        for appt in filtered_appts:
            if not appt.start_time:
                continue
            grouped_appointments[appt.start_time.date().isoformat()].append(appt)

        ordered_grouped = dict(sorted(grouped_appointments.items()))

        all_patients = PatientModel.query.order_by(PatientModel.full_name.asc()).all()
        all_doctors = DoctorModel.query.order_by(DoctorModel.doctor_label.asc()).all()

        return render_page(
            "appointments/vanilla.html",
            title="Appointments",
            grouped_appointments=ordered_grouped,
            doctors=all_doctors,
            all_patients=all_patients,
            today_str=today_str,
            yesterday_str=yesterday_str,
            tomorrow_str=tomorrow_str,
            use_range=use_range,
            selected_doctor=doctor_id or "all",
        )

    except Exception as exc:
        record_exception("appointments.vanilla", exc)
        today = datetime.date.today()
        return (
            render_page(
                "appointments/vanilla.html",
                title="Appointments",
                grouped_appointments={},
                doctors=[],
                all_patients=[],
                today_str=today.isoformat(),
                yesterday_str=(today - datetime.timedelta(days=1)).isoformat(),
                tomorrow_str=(today + datetime.timedelta(days=1)).isoformat(),
                use_range=request.args.get("use_range"),
                selected_doctor=request.args.get("doctor_id") or "all",
            ),
            500,
        )


# API endpoints for SSR template
@bp.route("/api/appointments/<int:appt_id>", methods=["GET"])
@bp.route("/api/appointments/<appt_id>", methods=["GET"])
@require_permission("appointments:view")
def api_get_appointment(appt_id):
    """Return appointment details for view/edit modals."""
    _ensure_doctor_records()
    appt_key = str(appt_id)
    appt = (
        AppointmentModel.query.options(
            selectinload(AppointmentModel.patient),
            selectinload(AppointmentModel.doctor),
        )
        .filter(AppointmentModel.id == appt_key)
        .first()
    )
    if not appt:
        abort(404)

    patient = appt.patient
    doctor = appt.doctor
    return jsonify(
        {
            "id": appt.id,
            "patient_id": patient.id if patient else appt.patient_id,
            "patient_name": patient.full_name if patient else appt.patient_name,
            "patient_short_id": patient.short_id if patient else None,
            "doctor_id": doctor.id if doctor else appt.doctor_id,
            "doctor_name": doctor.doctor_label if doctor else appt.doctor_label,
            "status": appt.status,
            "title": appt.title,
            "notes": appt.notes,
            "start_time": appt.start_time.isoformat() if appt.start_time else None,
            "end_time": appt.end_time.isoformat() if appt.end_time else None,
        }
    )


@csrf.exempt
@bp.route("/api/appointments/save", methods=["POST"])
@require_permission("appointments:edit")
def api_save_appointment():
    """Create or update an appointment."""
    _ensure_doctor_records()
    data = request.get_json() or {}
    appt_id = data.get("id")
    patient_id = data.get("patient_id")
    doctor_id = data.get("doctor_id")
    day = data.get("date")
    start_time_value = data.get("start_time")
    status = data.get("status") or "scheduled"
    title = data.get("title") or "Appointment"
    notes = data.get("notes")

    if not all([patient_id, doctor_id, day, start_time_value]):
        return jsonify({"success": False, "error": "Missing required fields."}), 400

    try:
        start_dt = datetime.datetime.fromisoformat(f"{day}T{start_time_value}")
    except ValueError:
        return jsonify({"success": False, "error": "Invalid date or time."}), 400
    end_dt = start_dt + datetime.timedelta(minutes=30)

    patient = PatientModel.query.filter_by(id=patient_id).first()
    if not patient:
        return jsonify({"success": False, "error": "Invalid patient."}), 400

    doctor = DoctorModel.query.filter_by(id=doctor_id).first()
    if not doctor:
        doctor_map = {slug: label for slug, label in doctor_choices()}
        doctor_label = doctor_map.get(doctor_id, doctor_id)
        doctor = DoctorModel(id=doctor_id, doctor_label=doctor_label)
        db.session.add(doctor)

    if appt_id:
        appt = AppointmentModel.query.filter_by(id=str(appt_id)).first()
        if not appt:
            return jsonify({"success": False, "error": "Appointment not found."}), 404
    else:
        appt = AppointmentModel(id=uuid4().hex)

    appt.patient = patient
    appt.patient_id = patient.id
    appt.patient_name = patient.full_name
    appt.patient_phone = patient.phone
    appt.doctor = doctor
    appt.doctor_id = doctor.id
    appt.doctor_label = doctor.doctor_label
    appt.title = title
    appt.status = status
    appt.notes = notes
    appt.start_time = start_dt
    appt.end_time = end_dt

    db.session.add(appt)
    db.session.commit()
    return jsonify({"success": True, "id": appt.id})


@csrf.exempt
@bp.route("/api/appointments/delete", methods=["POST"])
@require_permission("appointments:edit")
def api_delete_appointment():
    """Delete an appointment."""
    data = request.get_json() or {}
    appt_id = data.get("id")
    if not appt_id:
        return jsonify({"success": False, "error": "Missing appointment id."}), 400

    appt = AppointmentModel.query.filter_by(id=str(appt_id)).first()
    if not appt:
        return jsonify({"success": False, "error": "Appointment not found."}), 404

    db.session.delete(appt)
    db.session.commit()
    return jsonify({"success": True})


@csrf.exempt
@bp.route("/api/appointments/status", methods=["POST"])
@require_permission("appointments:edit")
def api_update_status():
    """Update appointment status."""
    data = request.get_json() or {}
    appt_id = data.get("id")
    status = data.get("status")
    if not appt_id or not status:
        return jsonify({"success": False, "error": "Missing id or status."}), 400

    appt = AppointmentModel.query.filter_by(id=str(appt_id)).first()
    if not appt:
        return jsonify({"success": False, "error": "Appointment not found."}), 404

    appt.status = status
    db.session.commit()
    return jsonify({"success": True})
