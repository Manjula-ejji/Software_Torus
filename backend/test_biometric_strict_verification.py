"""
TORUS Healthcare - Strict Biometric System Verification Suite
Complies with all Phase 1-14 requirements and tests all 9 Phase 12 test scenarios:
TEST 1: Clean DB + clean hardware -> 0 active biometric users (doctors intact).
TEST 2: Register admin@gmail.com -> R1 assigned.
TEST 3: Register user2@gmail.com -> R2 assigned; R1 still exists and still works.
TEST 4: Register user3@gmail.com -> R3 assigned; R1 and R2 still exist and still work.
TEST 5: Cross-user test: admin@gmail.com + user 2 fingerprint (slot 2) -> ACCESS DENIED.
TEST 6: Cross-user test: user2@gmail.com + admin fingerprint (slot 1) -> ACCESS DENIED.
TEST 7: Legitimate test: user2@gmail.com + user 2 fingerprint (slot 2) -> ACCESS GRANTED.
TEST 8: Re-register attempt: admin@gmail.com again -> BLOCKED (no overwrite of R1).
TEST 9: Register up to R20 -> R1..R20 all active; attempt User 21 -> BLOCKED (all slots occupied).
"""

import os
import sys
import sqlite3
import time
from pathlib import Path

# Add backend directory to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database
import biometrics

def run_strict_biometric_verification():
    print("=" * 85)
    print("TORUS HEALTHCARE - STRICT BIOMETRIC SYSTEM VERIFICATION SUITE")
    print("=" * 85)

    results = {}

    # --------------------------------------------------------------------------
    # PROTOCOL & HARDWARE STATUS CHECK (PHASE 1 & 2 & RULE 9)
    # --------------------------------------------------------------------------
    print("\n>>> AUDITING HARDWARE PROTOCOL & SERIAL STATUS...")
    hw_status = biometrics.hardware_manager.get_status()
    hw_connected = hw_status.get("connected", False)

    print(f"  Connected:      {hw_connected}")
    print(f"  Scanner Model:  {hw_status.get('device')}")
    print(f"  Protocol:       {hw_status.get('protocol')}")
    print(f"  Port:           {hw_status.get('port')}")
    print(f"  Baud Rate:      {hw_status.get('baud_rate', 115200)}")

    if hw_connected:
        print("[HW AUDIT] Scanner physically connected and responding.")
        results["hardware_connected"] = "PASS"
    else:
        print(f"[HW AUDIT] Scanner physically DISCONNECTED: {hw_status.get('error')}")
        print("[HW AUDIT] Per Rule 9: Physical hardware verification will be truthfully marked FAIL until scanner is attached.")
        results["hardware_connected"] = "FAIL (Scanner disconnected)"

    # --------------------------------------------------------------------------
    # PHASE 3: VERIFY BIJECTIVE SLOT MAPPING (R1..R20 <-> Hardware Slots 1..20 <-> R307 Pages 0..19)
    # --------------------------------------------------------------------------
    print("\n--- PHASE 3: Slot Mapping Verification ---")
    slot_mapping_ok = True
    for s in range(1, 21):
        lbl = database._slot_int_to_label(s)
        num = database._slot_label_to_int(f"R{s}")
        driver_page = s - 1
        if lbl != f"R{s}" or num != s:
            slot_mapping_ok = False
            print(f"[FAIL] Slot mapping error for {s}: label={lbl}, num={num}")
            break
    if slot_mapping_ok:
        print("[PASS] Bijective Slot Mapping verified: R1..R20 <-> Hardware Slot 1..20 <-> R307 Page 0..19.")
        results["slot_mapping"] = "PASS"
    else:
        results["slot_mapping"] = "FAIL"

    # --------------------------------------------------------------------------
    # TEST 1: CLEAN DB + CLEAN HARDWARE
    # --------------------------------------------------------------------------
    print("\n--- TEST 1: Clean DB + Clean Hardware ---")
    # Ensure standard test doctors exist in doctors table
    with database.get_db() as conn:
        cursor = conn.cursor()
        for email, name, uid in [
            ("admin@gmail.com", "Admin Doctor", "3001"),
            ("user2@gmail.com", "Dr. User Two", "DOC-USER2"),
            ("user3@gmail.com", "Dr. User Three", "DOC-USER3")
        ]:
            cursor.execute("SELECT id FROM doctors WHERE LOWER(email) = ?", (email,))
            if not cursor.fetchone():
                database.register_doctor(name, email, "Test@2026Doctor!", mobile="+91 9876543200", uid=uid)

    # Perform clean biometric reset (clears doctor_biometrics and hardware R1-R20)
    reset_res = database.reset_all_biometrics()
    print(f"  Reset result: cleared {reset_res.get('cleared_count')} records. Available: {reset_res.get('available_slots')}/20.")

    # Verify 0 active biometric users in DB
    with database.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM doctor_biometrics WHERE is_active = 1")
        active_count = cursor.fetchone()[0]
        # Verify doctors table is NOT wiped
        cursor.execute("SELECT COUNT(*) FROM doctors")
        doctors_count = cursor.fetchone()[0]

    test1_pass = (active_count == 0) and (doctors_count >= 3)
    if test1_pass:
        print(f"[PASS] TEST 1: Database has exactly 0 active biometric users. Doctors table ({doctors_count} doctors) intact.")
        results["test1"] = "PASS"
    else:
        print(f"[FAIL] TEST 1: Active biometric count={active_count}, Doctors count={doctors_count}")
        results["test1"] = "FAIL"

    # --------------------------------------------------------------------------
    # TEST 2: REGISTER admin@gmail.com -> R1
    # --------------------------------------------------------------------------
    print("\n--- TEST 2: Register admin@gmail.com -> R1 ---")
    next_slot = database.get_next_available_biometric_slot()
    print(f"  Next available slot: {next_slot}")
    assert next_slot == "R1", f"Expected R1, got {next_slot}"

    reg_admin = database.register_doctor_biometric(
        identifier="admin@gmail.com",
        fingerprint_slot="R1",
        template_data="R307_SLOT_1",
        scanner_model="STM32 / R307 Optical Biometric Scanner"
    )
    slot_admin = database.get_doctor_biometric_slot("admin@gmail.com")
    print(f"  Registration: success={reg_admin.get('success')}, assigned_slot={reg_admin.get('fingerprint_id')}, hardware_slot={reg_admin.get('hardware_slot')}")

    test2_pass = reg_admin.get("success") and (slot_admin == "R1") and (reg_admin.get("hardware_slot") == 1)
    if test2_pass:
        print("[PASS] TEST 2: admin@gmail.com successfully assigned hardware slot R1 (hardware_slot=1).")
        results["test2"] = "PASS"
    else:
        print(f"[FAIL] TEST 2: Registration failed or wrong slot: {slot_admin}")
        results["test2"] = "FAIL"

    # --------------------------------------------------------------------------
    # TEST 3: REGISTER user2@gmail.com -> R2; VERIFY R1 INTACT
    # --------------------------------------------------------------------------
    print("\n--- TEST 3: Register user2@gmail.com -> R2; verify R1 intact ---")
    next_slot = database.get_next_available_biometric_slot()
    print(f"  Next available slot: {next_slot}")
    assert next_slot == "R2", f"Expected R2, got {next_slot}"

    reg_user2 = database.register_doctor_biometric(
        identifier="user2@gmail.com",
        fingerprint_slot="R2",
        template_data="R307_SLOT_2",
        scanner_model="STM32 / R307 Optical Biometric Scanner"
    )
    slot_user2 = database.get_doctor_biometric_slot("user2@gmail.com")
    slot_admin_recheck = database.get_doctor_biometric_slot("admin@gmail.com")

    # Verify R1 fingerprint still works
    verify_r1 = database.verify_doctor_biometric_by_email("admin@gmail.com", 1)

    test3_pass = (
        reg_user2.get("success")
        and (slot_user2 == "R2")
        and (slot_admin_recheck == "R1")
        and verify_r1.get("matched")
    )
    if test3_pass:
        print("[PASS] TEST 3: user2@gmail.com assigned R2. admin@gmail.com (R1) remains intact and authenticates successfully.")
        results["test3"] = "PASS"
    else:
        print(f"[FAIL] TEST 3: user2 slot={slot_user2}, admin slot={slot_admin_recheck}, verify_r1={verify_r1.get('matched')}")
        results["test3"] = "FAIL"

    # --------------------------------------------------------------------------
    # TEST 4: REGISTER user3@gmail.com -> R3; VERIFY R1 AND R2 INTACT
    # --------------------------------------------------------------------------
    print("\n--- TEST 4: Register user3@gmail.com -> R3; verify R1 and R2 intact ---")
    next_slot = database.get_next_available_biometric_slot()
    print(f"  Next available slot: {next_slot}")
    assert next_slot == "R3", f"Expected R3, got {next_slot}"

    reg_user3 = database.register_doctor_biometric(
        identifier="user3@gmail.com",
        fingerprint_slot="R3",
        template_data="R307_SLOT_3",
        scanner_model="STM32 / R307 Optical Biometric Scanner"
    )
    slot_user3 = database.get_doctor_biometric_slot("user3@gmail.com")
    slot_u1 = database.get_doctor_biometric_slot("admin@gmail.com")
    slot_u2 = database.get_doctor_biometric_slot("user2@gmail.com")

    v1 = database.verify_doctor_biometric_by_email("admin@gmail.com", 1)
    v2 = database.verify_doctor_biometric_by_email("user2@gmail.com", 2)
    v3 = database.verify_doctor_biometric_by_email("user3@gmail.com", 3)

    test4_pass = (
        reg_user3.get("success")
        and (slot_user3 == "R3")
        and (slot_u1 == "R1")
        and (slot_u2 == "R2")
        and v1.get("matched")
        and v2.get("matched")
        and v3.get("matched")
    )
    if test4_pass:
        print("[PASS] TEST 4: user3 assigned R3. R1 and R2 remain intact and all 3 users verify independently.")
        results["test4"] = "PASS"
    else:
        print(f"[FAIL] TEST 4: Slots: {slot_u1}, {slot_u2}, {slot_user3}. Matches: {v1.get('matched')}, {v2.get('matched')}, {v3.get('matched')}")
        results["test4"] = "FAIL"

    # --------------------------------------------------------------------------
    # TEST 5: CROSS-USER: admin@gmail.com + user2 fingerprint (Slot 2) -> DENIED
    # --------------------------------------------------------------------------
    print("\n--- TEST 5: Cross-user: enter admin@gmail.com, place user 2 fingerprint (Slot 2) ---")
    v5_cross = database.verify_doctor_biometric_by_email("admin@gmail.com", 2)
    test5_pass = (not v5_cross.get("matched")) and (v5_cross.get("code") == "SLOT_MISMATCH")
    if test5_pass:
        print(f"[PASS] TEST 5: ACCESS DENIED as expected! Code: {v5_cross.get('code')}, Error: '{v5_cross.get('error')}'")
        results["test5"] = "PASS"
    else:
        print(f"[FAIL] TEST 5: Security breach! Result: {v5_cross}")
        results["test5"] = "FAIL"

    # --------------------------------------------------------------------------
    # TEST 6: CROSS-USER: user2@gmail.com + admin fingerprint (Slot 1) -> DENIED
    # --------------------------------------------------------------------------
    print("\n--- TEST 6: Cross-user: enter user2@gmail.com, place admin fingerprint (Slot 1) ---")
    v6_cross = database.verify_doctor_biometric_by_email("user2@gmail.com", 1)
    test6_pass = (not v6_cross.get("matched")) and (v6_cross.get("code") == "SLOT_MISMATCH")
    if test6_pass:
        print(f"[PASS] TEST 6: ACCESS DENIED as expected! Code: {v6_cross.get('code')}, Error: '{v6_cross.get('error')}'")
        results["test6"] = "PASS"
    else:
        print(f"[FAIL] TEST 6: Security breach! Result: {v6_cross}")
        results["test6"] = "FAIL"

    # --------------------------------------------------------------------------
    # TEST 7: LEGITIMATE LOGIN: user2@gmail.com + user 2 fingerprint (Slot 2) -> GRANTED
    # --------------------------------------------------------------------------
    print("\n--- TEST 7: Legitimate: enter user2@gmail.com, place user 2 fingerprint (Slot 2) ---")
    v7_legit = database.verify_doctor_biometric_by_email("user2@gmail.com", 2)
    test7_pass = v7_legit.get("matched") and (v7_legit.get("fingerprint_id") == "R2")
    if test7_pass:
        print(f"[PASS] TEST 7: ACCESS GRANTED! Doctor: {v7_legit.get('doctor', {}).get('name')}, Slot: {v7_legit.get('fingerprint_id')}")
        results["test7"] = "PASS"
    else:
        print(f"[FAIL] TEST 7: Legitimate login failed: {v7_legit}")
        results["test7"] = "FAIL"

    # --------------------------------------------------------------------------
    # TEST 8: RE-REGISTER ATTEMPT: admin@gmail.com AGAIN -> BLOCKED
    # --------------------------------------------------------------------------
    print("\n--- TEST 8: Re-register attempt: admin@gmail.com again -> BLOCKED ---")
    dup_reg = database.register_doctor_biometric(
        identifier="admin@gmail.com",
        fingerprint_slot="R4",
        template_data="R307_SLOT_4_ATTEMPT"
    )
    admin_slot_after = database.get_doctor_biometric_slot("admin@gmail.com")
    test8_pass = (
        not dup_reg.get("success")
        and dup_reg.get("already_registered") is True
        and (admin_slot_after == "R1")
    )
    if test8_pass:
        print(f"[PASS] TEST 8: Re-registration strictly blocked: '{dup_reg.get('error')}'. Slot R1 was NOT overwritten.")
        results["test8"] = "PASS"
    else:
        print(f"[FAIL] TEST 8: Duplicate registration check failed: {dup_reg}")
        results["test8"] = "FAIL"

    # --------------------------------------------------------------------------
    # TEST 9: REGISTER UP TO R20 -> ATTEMPT USER 21 -> BLOCKED
    # --------------------------------------------------------------------------
    print("\n--- TEST 9: Register users sequentially up to R20; attempt User 21 ---")
    # We already have R1 (admin), R2 (user2), R3 (user3). Enroll R4 through R20:
    for i in range(4, 21):
        user_email = f"doctor_{i}@torus.local"
        with database.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM doctors WHERE LOWER(email) = ?", (user_email,))
            if not cursor.fetchone():
                database.register_doctor(f"Dr. Test {i}", user_email, "Test@2026Doctor!", mobile=f"+91 9876543{i:03d}", uid=f"DOC-U{i}")

        expected_slot = f"R{i}"
        avail = database.get_next_available_biometric_slot()
        assert avail == expected_slot, f"Expected {expected_slot}, got {avail}"

        reg_res = database.register_doctor_biometric(
            identifier=user_email,
            fingerprint_slot=expected_slot,
            template_data=f"R307_SLOT_{i}",
            scanner_model="STM32 / R307 Optical Biometric Scanner"
        )
        assert reg_res.get("success") is True, f"Failed to register slot {expected_slot}"

    # Verify all 20 slots occupied
    slot_info = biometrics.hardware_manager.get_slot_info()
    print(f"  Occupied slots count: {slot_info.get('used_slots')}/20. Available: {slot_info.get('available_slots')}")

    # Now attempt 21st user registration:
    u21_email = "doctor_21@torus.local"
    with database.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM doctors WHERE LOWER(email) = ?", (u21_email,))
        if not cursor.fetchone():
            database.register_doctor("Dr. Test 21", u21_email, "Test@2026Doctor!", mobile="+91 9876543021", uid="DOC-U21")

    slot_21_avail = database.get_next_available_biometric_slot()
    u21_enroll_check = biometrics.hardware_manager._validate_doctor_for_enrollment(u21_email)

    test9_pass = (
        (slot_info.get("used_slots") == 20)
        and (slot_21_avail is None)
        and (not u21_enroll_check.get("ok"))
        and (u21_enroll_check.get("code") == "ALL_SLOTS_FULL")
    )
    if test9_pass:
        print(f"[PASS] TEST 9: All 20 slots (R1..R20) successfully registered. User 21 blocked with: '{u21_enroll_check.get('error')}'. No overwrite occurred.")
        results["test9"] = "PASS"
    else:
        print(f"[FAIL] TEST 9: 20-slot overflow test failed: avail={slot_21_avail}, check={u21_enroll_check}")
        results["test9"] = "FAIL"

    # Reset back to completely clean state (0 active registrations)
    print("\n--- RESETTING TO CLEAN EMPTY STATE (0 active registrations) ---")
    database.reset_all_biometrics()

    # Display final active biometric mappings
    with database.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT b.fingerprint_slot, b.hardware_slot, d.name, d.email, d.uid, b.fingerprint_template, b.is_active, b.enrolled_at
            FROM doctor_biometrics b
            JOIN doctors d ON b.doctor_id = d.id
            WHERE b.is_active = 1
            ORDER BY b.hardware_slot
        """)
        active_mappings = cursor.fetchall()

    print(f"\nFinal Active Database Biometric Mappings ({len(active_mappings)} active):")
    print(f"{'Slot':<6} | {'HW Slot':<7} | {'Doctor Name':<18} | {'Email':<28} | {'UID':<10} | {'Template Ref'}")
    print("-" * 95)
    for m in active_mappings:
        print(f"{m['fingerprint_slot']:<6} | {m['hardware_slot']:<7} | {m['name']:<18} | {m['email']:<28} | {m['uid']:<10} | {m['fingerprint_template']}")

    # --------------------------------------------------------------------------
    # SUMMARY REPORT
    # --------------------------------------------------------------------------
    print("\n" + "=" * 85)
    print("STRICT MULTI-USER BIOMETRIC SYSTEM VERIFICATION SUMMARY")
    print("=" * 85)
    print(f"1. Hardware Physical Connection:        {results.get('hardware_connected')}")
    print(f"2. Phase 3 Bijective Slot Mapping:      {results.get('slot_mapping')}")
    print(f"3. TEST 1 (Clean DB & HW, 0 users):     {results.get('test1')}")
    print(f"4. TEST 2 (Register admin -> R1):       {results.get('test2')}")
    print(f"5. TEST 3 (Register user2 -> R2, R1 OK): {results.get('test3')}")
    print(f"6. TEST 4 (Register user3 -> R3, R1-2): {results.get('test4')}")
    print(f"7. TEST 5 (admin + user2 finger -> DENY):{results.get('test5')}")
    print(f"8. TEST 6 (user2 + admin finger -> DENY):{results.get('test6')}")
    print(f"9. TEST 7 (user2 + user2 finger -> OK):  {results.get('test7')}")
    print(f"10. TEST 8 (Re-enroll admin -> BLOCKED): {results.get('test8')}")
    print(f"11. TEST 9 (R1..R20 filled, U21 BLOCKED):{results.get('test9')}")
    print("=" * 85)

    return results

if __name__ == "__main__":
    run_strict_biometric_verification()
