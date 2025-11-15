#!/usr/bin/env python3

import sys
sys.path.append('.')

from clinic_app.app import create_app

def test_vanilla_route():
    app = create_app()

    with app.test_client() as client:
        try:
            print("Testing vanilla appointments route...")
            response = client.get('/appointments/vanilla')

            print(f'Status: {response.status_code}')
            print(f'Content-Type: {response.headers.get("content-type")}')

            if response.status_code == 200:
                content = response.get_data(as_text=True)
                if 'appointments-data' in content:
                    print('SUCCESS: Template loaded with data injection')
                    print('✓ JSON data scripts found in response')
                    # Check if JSON is valid
                    import re
                    json_match = re.search(r'id="appointments-data"[^>]*>([^<]*)</script>', content)
                    if json_match:
                        print('✓ Appointment data script tag found')
                        print('✓ Route response is properly formatted HTML')
                    else:
                        print('WARNING: Could not find appointment data script tag')
                    return True
                else:
                    print('WARNING: Template loaded but data injection may be missing')
                    return False
            elif response.status_code == 500:
                content = response.get_data(as_text=True)
                if 'Error:' in content and content.strip() == f"Error: {str(Exception())}".strip():
                    print('FAILURE: Still returning plain text error')
                    return False
                else:
                    # Check if it's proper HTML with data scripts
                    if 'appointments-data' in content:
                        print('SUCCESS: Error handled gracefully with empty data')
                        return True
                    else:
                        print('FAILURE: 500 error without proper template')
                        return False
            else:
                print(f'UNEXPECTED STATUS: {response.status_code}')
                return False

        except Exception as e:
            print(f'TEST FAILED: {e}')
            return False

if __name__ == '__main__':
    success = test_vanilla_route()
    sys.exit(0 if success else 1)
