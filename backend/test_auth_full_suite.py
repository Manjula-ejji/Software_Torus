"""
Comprehensive Automated Test Suite for TORUS Authentication System
Validates Doctor, Patient, and Viewer roles according to all user requirements.
"""

import os
import sys
import sqlite3
import hashlib
import time

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database

def run_suite():
    print("=================================================================")
    print("STARTING TORUS AUTHENTICATION TEST SUITE")
    print("=================================================================")

    # 1. Clean and initialize database
    print("\n--- TEST 1: Clean Database & Initialize Default Accounts ---")
    database.clean_and_reinitialize_auth_db()
    
    # Check default accounts
    with database.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, uid, name, email, role FROM doctors WHERE email = 'admin@gmail.com'")
        doc = cursor.fetchone()
        assert doc is not None, "Default Doctor account missing!"
        print(f"[PASS] Default Doctor initialized: {doc['email']} (role: {doc['role']}, uid: {doc['uid']})")

        cursor.execute("SELECT id, uid, name, email, role FROM patients WHERE email = 'patient@gmail.com'")
        pat = cursor.fetchone()
        assert pat is not None, "Default Patient account missing!"
        print(f"[PASS] Default Patient initialized: {pat['email']} (role: {pat['role']}, uid: {pat['uid']})")

        cursor.execute("SELECT id, uid, name, email, role FROM viewers WHERE email = 'user@gmail.com'")
        view = cursor.fetchone()
        assert view is not None, "Default Viewer account missing!"
        print(f"[PASS] Default Viewer initialized: {view['email']} (role: {view['role']}, uid: {view['uid']})")

        # Ensure no other test accounts exist after clean init
        cursor.execute("SELECT COUNT(*) FROM doctors")
        assert cursor.fetchone()[0] == 1, "Doctors table should only have 1 default account initially"
        cursor.execute("SELECT COUNT(*) FROM patients")
        assert cursor.fetchone()[0] == 1, "Patients table should only have 1 default account initially"
        cursor.execute("SELECT COUNT(*) FROM viewers")
        assert cursor.fetchone()[0] == 1, "Viewers table should only have 1 default account initially"
        print("[PASS] Only the 3 required default accounts exist after clean init.")

    # 2. Test Doctor Registration, Login, Forgot Password, Reset
    print("\n--- TEST 2: Doctor Authentication Flow ---")
    test_email = "manjulaejji4@gmail.com"
    doc_pwd1 = "Manjula@123"
    doc_pwd2 = "Manjula@456"

    # Register Doctor
    reg_doc = database.register_doctor("Dr. Manjula", test_email, doc_pwd1, "+91 99887 76655")
    assert reg_doc["success"] is True, f"Doctor registration failed: {reg_doc}"
    print(f"[PASS] Doctor registered successfully: {test_email} (UID: {reg_doc['doctor']['uid']})")

    # Login Doctor with initial password
    login_doc = database.authenticate_doctor(test_email, doc_pwd1)
    assert login_doc["success"] is True, f"Doctor login failed: {login_doc}"
    print(f"[PASS] Doctor login with initial password successful.")

    # Request Doctor Reset OTP
    otp_doc_res = database.request_doctor_reset_otp(test_email)
    assert otp_doc_res["success"] is True, f"Doctor OTP request failed: {otp_doc_res}"
    print(f"[PASS] Doctor OTP generated: {otp_doc_res['message']}")

    # Get the OTP generated from DB
    with database.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT otp FROM password_reset_otps WHERE email = ? ORDER BY id DESC LIMIT 1", (test_email,))
        doc_otp = cursor.fetchone()[0]

    # Verify Doctor OTP
    verify_doc_res = database.verify_doctor_reset_otp(test_email, doc_otp)
    assert verify_doc_res["success"] is True, f"Doctor OTP verification failed: {verify_doc_res}"
    doc_reset_token = verify_doc_res["reset_token"]
    print(f"[PASS] Doctor OTP verified successfully. Reset token obtained.")

    # Reset Doctor Password with token
    reset_doc_res = database.reset_doctor_password_with_token(test_email, doc_reset_token, doc_pwd2)
    assert reset_doc_res["success"] is True, f"Doctor password reset failed: {reset_doc_res}"
    print(f"[PASS] Doctor password reset with verified token successful.")

    # Login with new password
    assert database.authenticate_doctor(test_email, doc_pwd2)["success"] is True, "Doctor login with new password failed!"
    assert database.authenticate_doctor(test_email, doc_pwd1)["success"] is False, "Doctor login with old password should fail!"
    print(f"[PASS] Doctor login with new password successful.")

    # 3. Test Patient Flow (Same Email)
    print("\n--- TEST 3: Patient Registration with SAME Email ---")
    pat_pwd1 = "ManjulaPat@123"
    pat_pwd2 = "ManjulaPat@456"

    # Register Patient with same email
    reg_pat = database.register_patient("Manjula Patient", test_email, pat_pwd1, "+91 99887 76655")
    assert reg_pat["success"] is True, f"Patient registration failed with same email: {reg_pat}"
    print(f"[PASS] Patient registered with same email successfully: {test_email} (UID: {reg_pat['patient']['uid']})")

    # Login Patient
    login_pat = database.authenticate_patient(test_email, pat_pwd1)
    assert login_pat["success"] is True, f"Patient login failed: {login_pat}"
    print(f"[PASS] Patient login successful.")

    # Request Patient Reset OTP
    otp_pat_res = database.request_patient_reset_otp(test_email)
    assert otp_pat_res["success"] is True, f"Patient OTP request failed: {otp_pat_res}"
    print(f"[PASS] Patient OTP generated: {otp_pat_res['message']}")

    # Get the Patient OTP generated from DB
    with database.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT otp FROM patient_password_reset_otps WHERE email = ? ORDER BY id DESC LIMIT 1", (test_email,))
        pat_otp = cursor.fetchone()[0]

    # Verify Patient OTP
    verify_pat_res = database.verify_patient_reset_otp(test_email, pat_otp)
    assert verify_pat_res["success"] is True, f"Patient OTP verification failed: {verify_pat_res}"
    pat_reset_token = verify_pat_res["reset_token"]
    print(f"[PASS] Patient OTP verified successfully. Reset token obtained.")

    # Reset Patient Password with token
    reset_pat_res = database.reset_patient_password_with_token(test_email, pat_reset_token, pat_pwd2)
    assert reset_pat_res["success"] is True, f"Patient password reset failed: {reset_pat_res}"
    print(f"[PASS] Patient password reset with verified token successful.")

    # Login with new password
    assert database.authenticate_patient(test_email, pat_pwd2)["success"] is True, "Patient login with new password failed!"
    assert database.authenticate_patient(test_email, pat_pwd1)["success"] is False, "Patient login with old password should fail!"
    print(f"[PASS] Patient login with new password successful.")

    # 4. Test Viewer Flow (Same Email)
    print("\n--- TEST 4: Viewer Registration with SAME Email ---")
    view_pwd1 = "ManjulaView@123"
    view_pwd2 = "ManjulaView@456"

    # Register Viewer with same email
    reg_view = database.register_viewer("Manjula Viewer", test_email, view_pwd1, "+91 99887 76655")
    assert reg_view["success"] is True, f"Viewer registration failed with same email: {reg_view}"
    print(f"[PASS] Viewer registered with same email successfully: {test_email} (UID: {reg_view['viewer']['uid']})")

    # Login Viewer
    login_view = database.authenticate_viewer(test_email, view_pwd1)
    assert login_view["success"] is True, f"Viewer login failed: {login_view}"
    print(f"[PASS] Viewer login successful.")

    # Request Viewer Reset OTP
    otp_view_res = database.request_viewer_reset_otp(test_email)
    assert otp_view_res["success"] is True, f"Viewer OTP request failed: {otp_view_res}"
    print(f"[PASS] Viewer OTP generated: {otp_view_res['message']}")

    # Get the Viewer OTP generated from DB
    with database.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT otp FROM viewer_password_reset_otps WHERE email = ? ORDER BY id DESC LIMIT 1", (test_email,))
        view_otp = cursor.fetchone()[0]

    # Verify Viewer OTP
    verify_view_res = database.verify_viewer_reset_otp(test_email, view_otp)
    assert verify_view_res["success"] is True, f"Viewer OTP verification failed: {verify_view_res}"
    view_reset_token = verify_view_res["reset_token"]
    print(f"[PASS] Viewer OTP verified successfully. Reset token obtained.")

    # Reset Viewer Password with token
    reset_view_res = database.reset_viewer_password_with_token(test_email, view_reset_token, view_pwd2)
    assert reset_view_res["success"] is True, f"Viewer password reset failed: {reset_view_res}"
    print(f"[PASS] Viewer password reset with verified token successful.")

    # Login with new password
    assert database.authenticate_viewer(test_email, view_pwd2)["success"] is True, "Viewer login with new password failed!"
    assert database.authenticate_viewer(test_email, view_pwd1)["success"] is False, "Viewer login with old password should fail!"
    print(f"[PASS] Viewer login with new password successful.")

    # 5. Duplicate Email within SAME Role Must Be BLOCKED
    print("\n--- TEST 5: Duplicate Registration Prevention Within Same Role ---")
    dup_doc = database.register_doctor("Duplicate Doctor", test_email, "AnyPass123!", "+91 99999 99999")
    assert dup_doc["success"] is False, "Duplicate Doctor registration must be blocked!"
    print(f"[PASS] Duplicate Doctor registration correctly blocked: {dup_doc['error']}")

    dup_pat = database.register_patient("Duplicate Patient", test_email, "AnyPass123!", "+91 99999 99999")
    assert dup_pat["success"] is False, "Duplicate Patient registration must be blocked!"
    print(f"[PASS] Duplicate Patient registration correctly blocked: {dup_pat['error']}")

    dup_view = database.register_viewer("Duplicate Viewer", test_email, "AnyPass123!", "+91 99999 99999")
    assert dup_view["success"] is False, "Duplicate Viewer registration must be blocked!"
    print(f"[PASS] Duplicate Viewer registration correctly blocked: {dup_view['error']}")

    # 6. Password Reset Isolation
    print("\n--- TEST 6: Password Isolation Across Roles ---")
    # Verify Doctor, Patient, and Viewer passwords are isolated
    assert database.authenticate_doctor(test_email, doc_pwd2)["success"] is True
    assert database.authenticate_patient(test_email, pat_pwd2)["success"] is True
    assert database.authenticate_viewer(test_email, view_pwd2)["success"] is True

    # Doctor doesn't accept Patient/Viewer password
    assert database.authenticate_doctor(test_email, pat_pwd2)["success"] is False
    assert database.authenticate_doctor(test_email, view_pwd2)["success"] is False

    # Patient doesn't accept Doctor/Viewer password
    assert database.authenticate_patient(test_email, doc_pwd2)["success"] is False
    assert database.authenticate_patient(test_email, view_pwd2)["success"] is False

    # Viewer doesn't accept Doctor/Patient password
    assert database.authenticate_viewer(test_email, doc_pwd2)["success"] is False
    assert database.authenticate_viewer(test_email, pat_pwd2)["success"] is False
    print("[PASS] Full password isolation verified across Doctor, Patient, and Viewer roles.")

    # 7. Unified Dispatcher Functions
    print("\n--- TEST 7: Unified Role-Based Dispatchers ---")
    assert database.unified_authenticate(test_email, doc_pwd2, "doctor")["success"] is True
    assert database.unified_authenticate(test_email, pat_pwd2, "patient")["success"] is True
    assert database.unified_authenticate(test_email, view_pwd2, "viewer")["success"] is True
    print("[PASS] Unified authentication dispatcher works seamlessly for all 3 roles.")

    # 8. Verify Default Accounts Are Still Intact
    print("\n--- TEST 8: Default Testing Accounts Retained ---")
    assert database.authenticate_doctor("admin@gmail.com", "admin123")["success"] is True
    assert database.authenticate_patient("patient@gmail.com", "patient123")["success"] is True
    assert database.authenticate_viewer("user@gmail.com", "user123")["success"] is True
    print("[PASS] All three default testing accounts remain active and functional.")

    # 9. Test Real SMTP OTP Dispatching
    print("\n--- TEST 9: Real SMTP Email Dispatch Test ---")
    test_otp_code = "849201"
    smtp_sent, smtp_msg = database.send_otp_email("plebctech@gmail.com", "Patient User", "4001", test_otp_code, "patient")
    print(f"[SMTP RESULT] send_otp_email sent={smtp_sent}, message={smtp_msg}")
    assert smtp_sent is True, f"SMTP OTP dispatch failed: {smtp_msg}"
    print("[PASS] Real SMTP OTP successfully transmitted to mail server.")

    # 10. Clean database to final state containing ONLY the 3 default testing accounts
    print("\n--- TEST 10: Resetting to Fresh Clean DB State with 3 Required Default Accounts ---")
    database.clean_and_reinitialize_auth_db()
    with database.get_db() as conn:
        c = conn.cursor()
        c.execute("SELECT email, role, uid FROM doctors")
        docs = c.fetchall()
        c.execute("SELECT email, role, uid FROM patients")
        pats = c.fetchall()
        c.execute("SELECT email, role, uid FROM viewers")
        views = c.fetchall()
        assert len(docs) == 1 and docs[0]["email"] == "admin@gmail.com"
        assert len(pats) == 1 and pats[0]["email"] == "patient@gmail.com"
        assert len(views) == 1 and views[0]["email"] == "user@gmail.com"
        print(f"[PASS] Final database contains ONLY Doctor ({docs[0]['email']}), Patient ({pats[0]['email']}), Viewer ({views[0]['email']}).")

    print("\n=================================================================")
    print("ALL TESTS PASSED SUCCESSFULLY! (100% PASS RATE)")
    print("=================================================================")

if __name__ == "__main__":
    run_suite()

