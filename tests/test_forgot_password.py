import sys
import os
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(backend_dir))

import database

def test_full_forgot_password_flow():
    print("--- 1. Initializing Database ---")
    database.init_db()

    print("\n--- 2. Registering Test Doctor Jack ---")
    reg_res = database.register_doctor(
        name="Jack Test",
        email="jack_test@gmail.com",
        password="Doctor@Password123",
        mobile="+91 98765 43210",
        uid="DOC-JCK99"
    )
    print(f"Registration Result: {reg_res}")
    assert reg_res["success"] or "already exists" in reg_res.get("error", "").lower()

    print("\n--- 3. Testing Non-existent Identifier ---")
    bad_res = database.generate_and_store_reset_otp("nonexistent@domain.com")
    print(f"Non-existent Request: {bad_res}")
    assert bad_res["success"] is False
    assert "No account found" in bad_res["error"]

    print("\n--- 4. Testing OTP Generation with SMTP Delivery ---")
    # Temporarily mock send_otp_email to simulate successful live delivery
    original_send = database.send_otp_email
    database.send_otp_email = lambda email, name, uid, otp: (True, "Delivered")

    otp_res = database.generate_and_store_reset_otp("jack_test@gmail.com")
    print(f"Request OTP Result: {otp_res}")
    assert otp_res["success"] is True
    assert "OTP has been sent" in otp_res["message"]
    # Check that OTP itself is NOT returned to frontend
    assert "otp" not in otp_res

    # Retrieve OTP directly from database to test verification
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM password_reset_otps WHERE email = 'jack_test@gmail.com' AND used = 0 ORDER BY id DESC LIMIT 1")
    otp_row = cursor.fetchone()
    conn.close()
    assert otp_row is not None
    real_otp = otp_row["otp"]
    print(f"Found generated OTP in DB: {real_otp}")

    print("\n--- 5. Testing Invalid OTP Verification ---")
    bad_otp_res = database.verify_reset_otp("jack_test@gmail.com", "000000")
    print(f"Invalid OTP Result: {bad_otp_res}")
    assert bad_otp_res["success"] is False
    assert "Invalid OTP" in bad_otp_res["error"]

    print("\n--- 6. Testing Valid OTP Verification with User ID identifier ---")
    valid_otp_res = database.verify_reset_otp("DOC-JCK99", real_otp)
    print(f"Valid OTP Result: {valid_otp_res}")
    assert valid_otp_res["success"] is True
    assert "reset_token" in valid_otp_res
    reset_token = valid_otp_res["reset_token"]

    print("\n--- 7. Testing Reset with Weak Password ---")
    weak_res = database.reset_doctor_password_with_token("DOC-JCK99", reset_token, "short")
    print(f"Weak Password Result: {weak_res}")
    assert weak_res["success"] is False

    print("\n--- 8. Testing Successful Password Reset ---")
    new_pass = "Doctor@NewSecret2026!"
    success_res = database.reset_doctor_password_with_token("jack_test@gmail.com", reset_token, new_pass)
    print(f"Reset Password Result: {success_res}")
    assert success_res["success"] is True

    print("\n--- 9. Verifying Login with Old Password Fails ---")
    old_login = database.authenticate_doctor("jack_test@gmail.com", "Doctor@Password123")
    print(f"Old Password Login: {old_login}")
    assert old_login["success"] is False

    print("\n--- 10. Verifying Login with New Password Succeeds ---")
    new_login = database.authenticate_doctor("DOC-JCK99", new_pass)
    print(f"New Password Login by UID: {new_login}")
    assert new_login["success"] is True
    assert new_login["doctor"]["email"] == "jack_test@gmail.com"

    new_login_email = database.authenticate_doctor("jack_test@gmail.com", new_pass)
    print(f"New Password Login by Email: {new_login_email}")
    assert new_login_email["success"] is True

    print("\n--- 11. Verifying Token Cannot Be Reused ---")
    reused_res = database.reset_doctor_password_with_token("jack_test@gmail.com", reset_token, "Doctor@AnotherPass123!")
    print(f"Reused Token Result: {reused_res}")
    assert reused_res["success"] is False

    print("=== ALL FORGOT PASSWORD BACKEND TESTS PASSED! ===")
    print("==========================================")

if __name__ == "__main__":
    test_full_forgot_password_flow()
