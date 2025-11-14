#!/usr/bin/env python3
"""
Comprehensive diagnostic test for admin settings CSRF and permission issues.
This test will identify exactly where the failures are occurring.
"""

import json
import requests
import sys

# Test configuration
BASE_URL = "http://127.0.0.1:8080"
ADMIN_LOGIN = {
    "username": "admin",
    "password": "admin123"  # Adjust based on your setup
}

class AdminCSRFDiagnostic:
    def __init__(self):
        self.session = requests.Session()
        self.csrf_token = None
        self.authenticated = False
        
    def test_csrf_token_generation(self):
        """Test 1: Verify CSRF token generation"""
        print("Test 1: CSRF Token Generation")
        print("=" * 50)
        
        # Get the main page to get CSRF token
        try:
            response = self.session.get(f"{BASE_URL}/admin/settings")
            print(f"GET /admin/settings - Status: {response.status_code}")
            
            # Extract CSRF token from meta tag
            content = response.text
            csrf_start = content.find('<meta name="csrf-token" content="')
            if csrf_start != -1:
                csrf_start += len('<meta name="csrf-token" content="')
                csrf_end = content.find('"', csrf_start)
                self.csrf_token = content[csrf_start:csrf_end]
                print(f"CSRF Token extracted: {self.csrf_token[:20]}...")
                print(f"Token length: {len(self.csrf_token)}")
            else:
                print("ERROR: No CSRF token found in page")
                return False
                
        except Exception as e:
            print(f"ERROR getting CSRF token: {e}")
            return False
            
        return True
    
    def test_authentication(self):
        """Test 2: Verify authentication works"""
        print("\nTest 2: Authentication")
        print("=" * 50)
        
        # Login
        try:
            login_data = {
                "username": ADMIN_LOGIN["username"],
                "password": ADMIN_LOGIN["password"]
            }
            
            response = self.session.post(f"{BASE_URL}/auth/login", data=login_data)
            print(f"POST /auth/login - Status: {response.status_code}")
            
            if response.status_code == 302:  # Redirect after successful login
                self.authenticated = True
                print("Authentication successful")
            else:
                print(f"Authentication failed - Status: {response.status_code}")
                print(f"Response: {response.text[:200]}")
                return False
                
        except Exception as e:
            print(f"ERROR during authentication: {e}")
            return False
            
        return True
    
    def test_direct_endpoint_access(self):
        """Test 3: Direct endpoint testing"""
        print("\nTest 3: Direct Endpoint Testing")
        print("=" * 50)
        
        if not self.csrf_token:
            print("ERROR: No CSRF token available")
            return False
            
        # Test 3a: Get roles list
        try:
            response = self.session.get(f"{BASE_URL}/admin/settings")
            print(f"GET /admin/settings (authenticated) - Status: {response.status_code}")
        except Exception as e:
            print(f"ERROR accessing admin settings: {e}")
        
        # Test 3b: Test role creation endpoint with CSRF token
        try:
            role_data = {
                "name": "Test Role",
                "description": "Diagnostic test role",
                "csrf_token": self.csrf_token
            }
            
            response = self.session.post(
                f"{BASE_URL}/admin/settings/roles/create",
                json=role_data,
                headers={"Content-Type": "application/json"}
            )
            print(f"POST /admin/settings/roles/create - Status: {response.status_code}")
            print(f"Response: {response.text[:500]}")
            
        except Exception as e:
            print(f"ERROR testing role creation: {e}")
            
        # Test 3c: Test user creation endpoint with CSRF token
        try:
            user_data = {
                "username": "testuser",
                "password": "testpass123",
                "full_name": "Test User",
                "csrf_token": self.csrf_token
            }
            
            response = self.session.post(
                f"{BASE_URL}/admin/settings/users/create",
                json=user_data,
                headers={"Content-Type": "application/json"}
            )
            print(f"POST /admin/settings/users/create - Status: {response.status_code}")
            print(f"Response: {response.text[:500]}")
            
        except Exception as e:
            print(f"ERROR testing user creation: {e}")
            
        return True
    
    def test_without_csrf_token(self):
        """Test 4: Test endpoints without CSRF token (should fail)"""
        print("\nTest 4: Testing Without CSRF Token")
        print("=" * 50)
        
        # Test role creation without CSRF token
        try:
            role_data = {
                "name": "Test Role No CSRF",
                "description": "This should fail"
            }
            
            response = self.session.post(
                f"{BASE_URL}/admin/settings/roles/create",
                json=role_data,
                headers={"Content-Type": "application/json"}
            )
            print(f"POST /admin/settings/roles/create (no CSRF) - Status: {response.status_code}")
            print(f"Response: {response.text[:500]}")
            
        except Exception as e:
            print(f"ERROR testing without CSRF: {e}")
            
        return True
    
    def test_csrf_token_validation_directly(self):
        """Test 5: Direct CSRF token validation test"""
        print("\nTest 5: Direct CSRF Token Validation")
        print("=" * 50)
        
        if not self.csrf_token:
            print("ERROR: No CSRF token available")
            return False
            
        # Test with valid CSRF token
        try:
            test_data = {"csrf_token": self.csrf_token, "test": "data"}
            
            response = self.session.post(
                f"{BASE_URL}/admin/settings/colors/reset",
                json=test_data,
                headers={"Content-Type": "application/json"}
            )
            print(f"POST /admin/settings/colors/reset (with CSRF) - Status: {response.status_code}")
            print(f"Response: {response.text[:500]}")
            
        except Exception as e:
            print(f"ERROR testing CSRF validation: {e}")
            
        return True
    
    def run_all_tests(self):
        """Run all diagnostic tests"""
        print("Starting Admin CSRF & Permission Diagnostic Tests")
        print("=" * 60)
        
        tests = [
            self.test_csrf_token_generation,
            self.test_authentication,
            self.test_direct_endpoint_access,
            self.test_without_csrf_token,
            self.test_csrf_token_validation_directly
        ]
        
        results = []
        for test in tests:
            try:
                result = test()
                results.append(result)
            except Exception as e:
                print(f"Test failed with exception: {e}")
                results.append(False)
        
        print("\n" + "=" * 60)
        print("TEST RESULTS SUMMARY")
        print("=" * 60)
        
        test_names = [
            "CSRF Token Generation",
            "Authentication",
            "Direct Endpoint Access",
            "Without CSRF Token",
            "CSRF Token Validation"
        ]
        
        for i, (name, result) in enumerate(zip(test_names, results)):
            status = "PASS" if result else "FAIL"
            print(f"{i+1}. {name}: {status}")
        
        print(f"\nAUTHENTICATION: {'WORKING' if self.authenticated else 'FAILED'}")
        print(f"CSRF TOKEN: {'AVAILABLE' if self.csrf_token else 'MISSING'}")
        
        return results

if __name__ == "__main__":
    diagnostic = AdminCSRFDiagnostic()
    diagnostic.run_all_tests()