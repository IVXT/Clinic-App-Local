"""Admin settings page with tabs for users, roles, and doctor colors."""

from collections.abc import Iterable, Mapping
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from flask import Blueprint, flash, jsonify, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import selectinload

from clinic_app.services.security import require_permission
from clinic_app.services.csrf import ensure_csrf_token
from clinic_app.services.doctor_colors import (
    DEFAULT_COLORS,
    delete_doctor_color,
    get_all_doctors_with_colors,
    init_doctor_colors_table,
    set_doctor_color,
)
from clinic_app.extensions import db, csrf
from clinic_app.models_rbac import Permission, Role, User, user_roles

bp = Blueprint("admin_settings", __name__, url_prefix="/admin/settings")
csrf.exempt(bp)


def _all_roles(session) -> list[Role]:
    """Return all roles ordered by name."""
    return session.execute(select(Role).order_by(Role.name)).unique().scalars().all()


def _roles_from_form(session, form_data) -> list[Role]:
    """Resolve role ids from the submitted form into ORM objects."""
    role_values: Iterable[object]
    if hasattr(form_data, "getlist"):
        role_values = form_data.getlist("roles")  # type: ignore[call-arg]
    elif isinstance(form_data, Mapping):
        role_values = form_data.get("roles", [])  # type: ignore[assignment]
    elif isinstance(form_data, Iterable):
        role_values = form_data
    else:
        role_values = []

    role_ids: list[int] = []
    for raw in role_values:
        if raw in (None, ""):
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        role_ids.append(value)

    if not role_ids:
        return []
    stmt = select(Role).where(Role.id.in_(role_ids))
    return session.execute(stmt).unique().scalars().all()


def _fallback_user_id(session, exclude_user_id: str) -> str | None:
    """Pick another user id for reassignment (prefer current user)."""
    if current_user.is_authenticated and current_user.id != exclude_user_id:
        return current_user.id

    fallback = session.execute(
        select(User.id)
        .where(User.id != exclude_user_id)
        .order_by(User.created_at.asc())
        .limit(1)
    ).scalar_one_or_none()
    return fallback


def _reassign_linked_records(session, source_user_id: str, target_user_id: str | None) -> bool:
    """Reassign FK references that block deletion."""
    if not target_user_id:
        return False
    try:
        # Reassign expense_receipts.created_by
        session.execute(
            text("UPDATE expense_receipts SET created_by=:target WHERE created_by=:source"),
            {"target": target_user_id, "source": source_user_id},
        )
    except OperationalError:
        # Expense receipts table not present; skip
        pass
    
    try:
        # Reassign receipts.issued_by_user_id
        session.execute(
            text("UPDATE receipts SET issued_by_user_id=:target WHERE issued_by_user_id=:source"),
            {"target": target_user_id, "source": source_user_id},
        )
    except OperationalError:
        # Receipts table not present or column doesn't exist; skip
        pass
    
    try:
        # Reassign receipt_reprints.user_id
        session.execute(
            text("UPDATE receipt_reprints SET user_id=:target WHERE user_id=:source"),
            {"target": target_user_id, "source": source_user_id},
        )
    except OperationalError:
        # Receipt reprints table not present; skip
        pass
    
    return True


def _admin_role(session) -> Role | None:
    return session.execute(select(Role).where(Role.name == "Admin")).unique().scalars().one_or_none()


def _has_other_admins(session, admin_role_id: int | None, exclude_user_id: str) -> bool:
    legacy_count = session.scalar(
        select(func.count())
        .select_from(User)
        .where(func.lower(User.role) == "admin", User.id != exclude_user_id)
    )
    if legacy_count:
        return True
    if admin_role_id is None:
        return False
    assigned = session.scalar(
        select(func.count())
        .select_from(user_roles)
        .where(user_roles.c.role_id == admin_role_id, user_roles.c.user_id != exclude_user_id)
    )
    return bool(assigned)


def _grouped_permissions(session) -> dict[str, list[Permission]]:
    """Group permissions into logical categories."""
    permissions = session.execute(select(Permission).order_by(Permission.code)).unique().scalars().all()

    groups = {
        "👥 User Management": [],
        "📅 Appointments": [],
        "🏥 Patients": [],
        "💰 Payments & Receipts": [],
        "📊 Reports & Exports": [],
        "⚙️ System Administration": [],
        "🖼️ Images & Media": [],
        "💼 Expenses": [],
    }

    for perm in permissions:
        code = perm.code.lower()
        if any(keyword in code for keyword in ['user', 'role', 'admin']):
            groups["👥 User Management"].append(perm)
        elif any(keyword in code for keyword in ['appointment', 'schedule']):
            groups["📅 Appointments"].append(perm)
        elif any(keyword in code for keyword in ['patient']):
            groups["🏥 Patients"].append(perm)
        elif any(keyword in code for keyword in ['payment', 'receipt']):
            groups["💰 Payments & Receipts"].append(perm)
        elif any(keyword in code for keyword in ['report', 'export', 'collection']):
            groups["📊 Reports & Exports"].append(perm)
        elif any(keyword in code for keyword in ['doctor', 'color', 'system']):
            groups["⚙️ System Administration"].append(perm)
        elif any(keyword in code for keyword in ['image', 'media']):
            groups["🖼️ Images & Media"].append(perm)
        elif any(keyword in code for keyword in ['expense']):
            groups["💼 Expenses"].append(perm)
        else:
            groups["⚙️ System Administration"].append(perm)  # Default group

    # Remove empty groups
    return {k: v for k, v in groups.items() if v}


@bp.route("/", methods=["GET"])
@require_permission("admin.user.manage")
def index():
    """Main admin settings page with tabs."""
    session = db.session()

    try:
        # Get all users with their roles
        stmt = select(User).options(selectinload(User.roles)).order_by(User.created_at.desc())
        users = session.execute(stmt).unique().scalars().all()

        # Get all roles with their permissions
        roles_stmt = select(Role).options(selectinload(Role.permissions)).order_by(Role.name)
        roles = session.execute(roles_stmt).unique().scalars().all()

        # Get grouped permissions
        permissions = _grouped_permissions(session)

        # Get doctor colors
        doctors = get_all_doctors_with_colors()

        return render_template("admin/settings/index.html",
                             users=users,
                             roles=roles,
                             permissions=permissions,
                             doctors=doctors)
    finally:
        session.close()


@bp.route("/users/create", methods=["POST"])
@csrf.exempt
@require_permission("admin.user.manage")
def create_user():
    """Create a new user via AJAX."""
    session = db.session()
    try:
        # Validate CSRF token
        data = request.get_json()
        ensure_csrf_token(data)
        
        print(f"DEBUG CREATE: Raw request data: {data}")
        
        username = (data.get("username") or "").strip()
        password = (data.get("password") or "").strip()
        full_name = (data.get("full_name") or "").strip() or username
        phone = (data.get("phone") or "").strip() or None
        is_active = data.get("is_active", True)
        selected_roles = _roles_from_form(session, SimpleNamespace(getlist=lambda k: data.get("roles", [])))

        errors = []
        if len(username) < 3:
            errors.append("Username must be at least 3 characters.")
        if not password:
            errors.append("Password is required.")
        if session.scalar(select(User.id).where(User.username == username)):
            errors.append("Username already exists.")

        if errors:
            return jsonify({"success": False, "errors": errors}), 400

        now = datetime.now(timezone.utc).isoformat()
        new_user = User(
            id=str(uuid4()),
            username=username,
            full_name=full_name,
            phone=phone,
            is_active=is_active,
            created_at=now,
            updated_at=now,
        )
        new_user.set_password(password)
        new_user.roles = selected_roles
        new_user.sync_legacy_role()
        session.add(new_user)
        session.commit()

        return jsonify({
            "success": True,
            "user": {
                "id": new_user.id,
                "username": new_user.username,
                "full_name": new_user.full_name,
                "phone": new_user.phone,
                "is_active": new_user.is_active,
                "roles": [role.name for role in new_user.roles]
            }
        })
    except Exception as e:
        session.rollback()
        return jsonify({"success": False, "errors": [str(e)]}), 500
    finally:
        session.close()


@bp.route("/users/<user_id>/update", methods=["POST"])
@csrf.exempt
@require_permission("admin.user.manage")
def update_user(user_id: str):
    """Update a user via AJAX."""
    session = db.session()
    try:
        # Validate CSRF token
        data = request.get_json()
        ensure_csrf_token(data)
        
        print(f"DEBUG UPDATE: Raw request data: {data}")
        
        user = session.get(User, user_id)
        if not user:
            return jsonify({"success": False, "errors": ["User not found"]}), 404

        new_username = (data.get("username") or "").strip()
        full_name = (data.get("full_name") or "").strip()
        phone = (data.get("phone") or "").strip() or None
        is_active = data.get("is_active", True)
        password = (data.get("password") or "").strip()
        selected_roles = _roles_from_form(session, SimpleNamespace(getlist=lambda k: data.get("roles", [])))

        print(f"DEBUG: Parsed data - username: '{new_username}', roles: {data.get('roles', [])}, is_active: {is_active}")

        admin_role = _admin_role(session)
        will_be_admin = bool(
            admin_role and any(role.id == admin_role.id for role in selected_roles)
        )
        protected_admin = user.username == "admin" or (user.id or "").startswith("admin-")

        # Last admin protection
        if not will_be_admin:
            if not _has_other_admins(session, getattr(admin_role, "id", None), user.id):
                print("DEBUG: Last admin protection triggered")
                return jsonify({"success": False, "errors": ["At least one admin account must remain. Assign another Admin before changing this user."]}), 400
            if protected_admin:
                print("DEBUG: Protected admin check triggered")
                return jsonify({"success": False, "errors": ["The primary admin account must remain an Admin."]}), 400

        if len(new_username) < 3:
            print(f"DEBUG: Username too short: '{new_username}'")
            return jsonify({"success": False, "errors": ["Username must be at least 3 characters."]}), 400

        duplicate = session.scalar(
            select(User.id).where(User.username == new_username, User.id != user.id)
        )
        if duplicate:
            print(f"DEBUG: Username already exists: '{new_username}'")
            return jsonify({"success": False, "errors": ["Username already exists."]}), 400

        user.username = new_username
        user.full_name = full_name or user.full_name or new_username
        user.phone = phone
        user.is_active = is_active
        user.updated_at = datetime.now(timezone.utc).isoformat()

        if password:
            user.set_password(password)

        user.roles = selected_roles
        user.sync_legacy_role()
        session.commit()

        print("DEBUG: User updated successfully")
        return jsonify({
            "success": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "full_name": user.full_name,
                "phone": user.phone,
                "is_active": user.is_active,
                "roles": [role.name for role in user.roles]
            }
        })
    except Exception as e:
        session.rollback()
        print(f"DEBUG: Exception occurred: {e}")
        return jsonify({"success": False, "errors": [str(e)]}), 500
    finally:
        session.close()


@bp.route("/users/<user_id>/delete", methods=["POST"])
@csrf.exempt
@require_permission("admin.user.manage")
def delete_user(user_id: str):
    """Delete a user via AJAX."""
    session = db.session()
    try:
        # Validate CSRF token
        data = request.get_json() or {}
        ensure_csrf_token(data)
        
        print(f"DEBUG DELETE USER: Raw request data: {data}")
        
        user = session.get(User, user_id)
        if not user:
            return jsonify({"success": False, "errors": ["User not found"]}), 404

        if current_user.is_authenticated and current_user.id == user.id:
            return jsonify({"success": False, "errors": ["You cannot delete the account you are currently using."]}), 400

        admin_role = _admin_role(session)
        is_admin = (user.role or "").lower() == "admin" or (
            admin_role and any(role.id == admin_role.id for role in user.roles)
        )
        protected_admin = user.username == "admin" or (user.id or "").startswith("admin-")

        if protected_admin:
            return jsonify({"success": False, "errors": ["The primary admin account cannot be deleted."]}), 400

        if is_admin and not _has_other_admins(session, getattr(admin_role, "id", None), user.id):
            return jsonify({"success": False, "errors": ["At least one admin account must remain. Assign another Admin before deleting this user."]}), 400

        # Reassign linked records that enforce FK constraints
        fallback_id = _fallback_user_id(session, user.id)
        if not fallback_id:
            return jsonify({"success": False, "errors": ["Cannot delete user: no other user available to reassign linked records. Create another user first."]}), 400
        
        reassigned = _reassign_linked_records(session, user.id, fallback_id)

        # Clean up user relationships before deletion
        session.execute(user_roles.delete().where(user_roles.c.user_id == user.id))
        
        # Flush to apply reassignments before deletion
        session.flush()

        try:
            session.delete(user)
            session.commit()
        except IntegrityError as e:
            session.rollback()
            print(f"DEBUG DELETE USER: IntegrityError - {e}")
            message = (
                "This account is linked to existing records and could not be deleted. "
                "The system attempted to reassign records but a foreign key constraint is preventing deletion. "
                "Please contact support if this issue persists."
            )
            return jsonify({"success": False, "errors": [message]}), 400

        return jsonify({"success": True})
    except Exception as e:
        session.rollback()
        print(f"DEBUG DELETE USER: Exception - {e}")
        return jsonify({"success": False, "errors": [str(e)]}), 500
    finally:
        session.close()


@bp.route("/roles/create", methods=["POST"])
@csrf.exempt
@require_permission("admin.user.manage")
def create_role():
    """Create a new role via AJAX."""
    session = db.session()
    try:
        # Validate CSRF token
        data = request.get_json()
        ensure_csrf_token(data)
        
        print(f"DEBUG CREATE ROLE: Raw request data: {data}")
        
        name = (data.get("name") or "").strip()
        description = (data.get("description") or "").strip() or None
        permission_ids = data.get("permissions", [])

        if len(name) < 2:
            return jsonify({"success": False, "errors": ["Role name must be at least 2 characters."]}), 400

        if session.scalar(select(Role.id).where(Role.name == name)):
            return jsonify({"success": False, "errors": ["Role name already exists."]}), 400

        role = Role(name=name, description=description)

        if permission_ids:
            permissions = session.execute(
                select(Permission).where(Permission.id.in_(permission_ids))
            ).unique().scalars().all()
            role.permissions = permissions

        session.add(role)
        session.commit()

        return jsonify({
            "success": True,
            "role": {
                "id": role.id,
                "name": role.name,
                "description": role.description,
                "permissions": [{"id": p.id, "code": p.code, "name": p.code} for p in role.permissions]
            }
        })
    except Exception as e:
        session.rollback()
        return jsonify({"success": False, "errors": [str(e)]}), 500
    finally:
        session.close()


@bp.route("/roles/<int:role_id>/update", methods=["POST"])
@csrf.exempt
@require_permission("admin.user.manage")
def update_role(role_id: int):
    """Update a role via AJAX."""
    session = db.session()
    try:
        # Validate CSRF token
        data = request.get_json()
        ensure_csrf_token(data)
        
        print(f"DEBUG UPDATE ROLE: Raw request data: {data}")
        
        role = session.get(Role, role_id)
        if not role:
            return jsonify({"success": False, "errors": ["Role not found"]}), 404

        new_name = (data.get("name") or "").strip()
        description = (data.get("description") or "").strip() or None
        permission_ids = data.get("permissions", [])

        if len(new_name) < 2:
            return jsonify({"success": False, "errors": ["Role name must be at least 2 characters."]}), 400

        duplicate = session.scalar(
            select(Role.id).where(Role.name == new_name, Role.id != role.id)
        )
        if duplicate:
            return jsonify({"success": False, "errors": ["Role name already exists."]}), 400

        role.name = new_name
        role.description = description

        if permission_ids:
            permissions = session.execute(
                select(Permission).where(Permission.id.in_(permission_ids))
            ).unique().scalars().all()
            role.permissions = permissions
        else:
            role.permissions = []

        session.commit()

        return jsonify({
            "success": True,
            "role": {
                "id": role.id,
                "name": role.name,
                "description": role.description,
                "permissions": [{"id": p.id, "code": p.code, "name": p.code} for p in role.permissions]
            }
        })
    except Exception as e:
        session.rollback()
        return jsonify({"success": False, "errors": [str(e)]}), 500
    finally:
        session.close()


@bp.route("/roles/<int:role_id>/delete", methods=["POST"])
@csrf.exempt
@require_permission("admin.user.manage")
def delete_role(role_id: int):
    """Delete a role via AJAX."""
    session = db.session()
    try:
        # Validate CSRF token
        data = request.get_json() or {}
        ensure_csrf_token(data)
        
        print(f"DEBUG DELETE ROLE: Raw request data: {data}")
        
        role = session.get(Role, role_id)
        if not role:
            return jsonify({"success": False, "errors": ["Role not found"]}), 404

        assigned = session.scalar(
            select(func.count())
            .select_from(user_roles)
            .where(user_roles.c.role_id == role_id)
        )
        if assigned:
            return jsonify({"success": False, "errors": ["Role is assigned to users and cannot be deleted."]}), 400

        session.delete(role)
        session.commit()

        return jsonify({"success": True})
    except Exception as e:
        session.rollback()
        return jsonify({"success": False, "errors": [str(e)]}), 500
    finally:
        session.close()


@bp.route("/colors/update", methods=["POST"])
@csrf.exempt
@require_permission("admin.user.manage")
def update_color():
    """Update doctor color via AJAX."""
    try:
        # Validate CSRF token
        data = request.get_json()
        ensure_csrf_token(data)
        
        print(f"DEBUG UPDATE COLOR: Raw request data: {data}")
        
        doctor_id = data.get("doctor_id")
        color = data.get("color")

        if not doctor_id or not color:
            return jsonify({"success": False, "errors": ["Doctor ID and color are required"]}), 400

        init_doctor_colors_table()
        set_doctor_color(doctor_id, color)

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "errors": [str(e)]}), 500


@bp.route("/colors/reset", methods=["POST"])
@csrf.exempt
@require_permission("admin.user.manage")
def reset_colors():
    """Reset all doctor colors to defaults via AJAX."""
    try:
        # Validate CSRF token
        data = request.get_json() or {}
        ensure_csrf_token(data)
        
        print(f"DEBUG RESET COLORS: Raw request data: {data}")
        
        from clinic_app.services.appointments import doctor_choices

        doctors = {slug: label for slug, label in doctor_choices()}
        for doctor_id, color in DEFAULT_COLORS.items():
            if doctor_id in doctors:
                set_doctor_color(doctor_id, color)

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "errors": [str(e)]}), 500


@bp.route("/users/<user_id>", methods=["GET"])
@require_permission("admin.user.manage")
def get_user(user_id: str):
    """Get user data for editing via AJAX."""
    session = db.session()
    try:
        # Load user with roles relationship
        user = session.execute(
            select(User).options(selectinload(User.roles)).where(User.id == user_id)
        ).unique().scalars().one_or_none()
        
        if not user:
            return jsonify({"success": False, "errors": ["User not found"]}), 404

        print(f"DEBUG GET USER: Loaded user {user.username} with {len(user.roles)} roles: {[role.id for role in user.roles]}")

        return jsonify({
            "success": True,
            "user": {
                "id": user.id,
                "username": user.username,
                "full_name": user.full_name,
                "phone": user.phone,
                "is_active": user.is_active,
                "roles": [role.id for role in user.roles]
            }
        })
    finally:
        session.close()


@bp.route("/roles/<int:role_id>", methods=["GET"])
@require_permission("admin.user.manage")
def get_role(role_id: int):
    """Get role data for editing via AJAX."""
    session = db.session()
    try:
        # Load role with permissions relationship
        role = session.execute(
            select(Role).options(selectinload(Role.permissions)).where(Role.id == role_id)
        ).unique().scalars().one_or_none()
        
        if not role:
            return jsonify({"success": False, "errors": ["Role not found"]}), 404

        print(f"DEBUG GET ROLE: Loaded role {role.name} with {len(role.permissions)} permissions: {[p.id for p in role.permissions]}")

        return jsonify({
            "success": True,
            "role": {
                "id": role.id,
                "name": role.name,
                "description": role.description,
                "permissions": [perm.id for perm in role.permissions]
            }
        })
    finally:
        session.close()
