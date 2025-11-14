from importlib import import_module

__all__ = ["register_blueprints"]


def register_blueprints(app) -> None:
    """Register project blueprints exactly once (idempotent)."""
    modules = [
        "clinic_app.blueprints.core",
        "clinic_app.blueprints.appointments.routes",
        "clinic_app.blueprints.appointments.multi_doctor",
        "clinic_app.blueprints.appointments.move_appointments",
        "clinic_app.blueprints.receipts.routes",
        "clinic_app.blueprints.admin_settings",
        "clinic_app.blueprints.images",
        "clinic_app.blueprints.patients.routes",
        "clinic_app.blueprints.payments.routes",
        "clinic_app.blueprints.reports.routes",
    ]
    
    # Add auth blueprint specifically (critical for login)
    try:
        module = import_module("clinic_app.blueprints.auth.routes")
        auth_bp = getattr(module, "bp", None)
        if auth_bp is not None:
            bp_name = getattr(auth_bp, "name", None) or "auth"
            if bp_name not in app.blueprints:
                app.register_blueprint(auth_bp, url_prefix="/auth")
                print(f"Successfully registered auth blueprint: {bp_name}")
        else:
            print("Warning: auth blueprint found but bp is None")
    except ImportError as e:
        print(f"Warning: Could not import auth blueprint: {e}")
    except Exception as e:
        print(f"Warning: Error registering auth blueprint: {e}")
    
    # Register main modules
    for mod_name in modules:
        try:
            module = import_module(mod_name)
            bp = getattr(module, "bp", None)
            if bp is None:
                continue
            bp_name = getattr(bp, "name", None) or "bp"
            if bp_name in app.blueprints:
                continue
            app.register_blueprint(bp)
        except ImportError:
            # Skip modules that don't exist yet
            continue
    
    # Register expenses blueprint with explicit handling
    try:
        module = import_module("clinic_app.blueprints.expenses")
        expenses_bp = getattr(module, "bp", None)
        if expenses_bp is not None:
            bp_name = getattr(expenses_bp, "name", None) or "expenses"
            if bp_name not in app.blueprints:
                app.register_blueprint(expenses_bp, url_prefix="/expenses")
                print(f"Successfully registered expenses blueprint: {bp_name}")
        else:
            print("Warning: expenses blueprint found but bp is None")
    except ImportError as e:
        print(f"Warning: Could not import expenses blueprint: {e}")
    except Exception as e:
        print(f"Warning: Error registering expenses blueprint: {e}")

    if "core.index" in app.view_functions and "index" not in app.view_functions:
        app.add_url_rule("/", endpoint="index", view_func=app.view_functions["core.index"])
