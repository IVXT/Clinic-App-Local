#!/usr/bin/env python3

from clinic_app import create_app
import json

app = create_app()
app.config['TESTING'] = True
app.config['LOGIN_DISABLED'] = True

def test_data_injection():
    """Test only the data injection logic without authentication."""
    with app.app_context():
        # Mock g.current_user for permission checks
        from flask import g
        g.current_user = None

        from clinic_app.blueprints.appointments.routes import appointments_vanilla

        print('Testing data injection...')

        # Test the data preparation part manually
        from datetime import datetime, timedelta

        try:
            # Fetch appointments for a rolling 30-day window (past week through next 3 weeks)
            today = datetime.now().date()
            start_day = today - timedelta(days=7)
            end_day = today + timedelta(days=21)
            appointments = []  # Mock for now
            doctors = []  # Mock for now

            # Test patients query
            from clinic_app.services.database import db
            conn = db()
            try:
                patients_rows = conn.execute("""
                    SELECT id, short_id, full_name, phone
                    FROM patients
                    ORDER BY full_name
                    LIMIT 5
                """).fetchall()
                conn.close()
                print(f'[OK] Found {len(patients_rows)} patients')
            except Exception as e:
                print(f'[ERROR] Patient query failed: {e}')
                patients_rows = []

            # Format appointments
            formatted_appts = []
            formatted_patients = []
            formatted_doctors = ["All Doctors"]

            # Test JSON serialization of each component
            test_data = {
                'appointments_json': json.dumps(formatted_appts),
                'patients_json': json.dumps(formatted_patients),
                'doctors_json': json.dumps(formatted_doctors)
            }

            print('[OK] JSON serialization test passed')

            # Test template rendering
            from flask import render_template
            try:
                template_result = render_template('appointments/vanilla.html', **test_data)
                print('[OK] Template rendered successfully')
                print('[OK] No Jinja2 syntax errors!')
            except Exception as e:
                print(f'[ERROR] Template rendering failed: {e}')
                if 'end of print statement' in str(e):
                    print('[SPECIFIC ERROR] This is the "end of print statement" error the user reported!')
                    # Let's examine the data being passed to the template
                    print('[DEBUG] Data being passed to template:')
                    for key, value in test_data.items():
                        print(f'  {key}: {value[:100]}...' if len(value) > 100 else f'  {key}: {value}')
                    print(f'[DEBUG] Data length - appointments_json: {len(test_data["appointments_json"])} chars')
                    print(f'[DEBUG] Data length - patients_json: {len(test_data["patients_json"])} chars')
                    print(f'[DEBUG] Data length - doctors_json: {len(test_data["doctors_json"])} chars')
                    return

        except Exception as e:
            print(f'[ERROR] Data preparation failed: {e}')
            import traceback
            traceback.print_exc()

def test_vanilla_route():
    """Test the vanilla appointments route."""
    print('Testing with request context...')
    test_data_injection()

if __name__ == '__main__':
    test_vanilla_route()
