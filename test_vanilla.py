#!/usr/bin/env python3
"""Test script to check if vanilla appointments route works."""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from clinic_app.app import create_app

def test_vanilla_route():
    """Test the vanilla appointments route."""
    app = create_app()

    with app.test_request_context():
        try:
            from clinic_app.blueprints.appointments.routes import appointments_vanilla
            result = appointments_vanilla()
            print("SUCCESS: Route executed successfully!")
            print("First 500 characters of response:")
            print(str(result)[:500])
            print("\nLooking for JSON data injection...")
            if 'appointments_json' in str(result) and 'patients_json' in str(result):
                print("SUCCESS: JSON data injection found!")
            else:
                print("ERROR: JSON data injection NOT found!")
            return True
        except Exception as e:
            print(f"ERROR: Route failed: {e}")
            import traceback
            traceback.print_exc()
            return False

if __name__ == '__main__':
    test_vanilla_route()
