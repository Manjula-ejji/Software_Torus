import json
import urllib.request
import urllib.error

BASE_URL = "http://127.0.0.1:5000"

def post_json(endpoint, data):
    url = f"{BASE_URL}{endpoint}"
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"raw": body}
        return e.code, parsed

def get_json(endpoint):
    url = f"{BASE_URL}{endpoint}"
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"raw": body}
        return e.code, parsed

import time

def test_full_signature_replacement_and_audit_workflow():
    test_rep_id = f"REP-TEST-SIG-{int(time.time())}"

    # Step 1: Initial Signing
    sig_payload = {
        "reportId": test_rep_id,
        "sessionId": "torus",
        "doctorName": "Dr. Admin Doctor",
        "doctorLicense": "TORUS-REG-3001",
        "doctorId": "3001",
        "signatureData": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
        "signatureHash": "TORUS-SIG-TEST-INITIAL-001",
        "signedAt": "2026-10-19T10:00:00Z",
        "findings": "Liver ultrasound unremarkable. Gallbladder wall 2.0 mm.",
        "recommendations": "Routine clinical follow-up.",
        "patientName": "Test Patient",
        "patientId": "P-9999",
        "scanType": "Abdominal Ultrasound",
        "status": "signed"
    }

    status, res = post_json("/api/reports/sign", sig_payload)
    assert status == 200, f"Sign failed: {res}"
    assert res["success"] is True

    # Verify report state
    status, rep_res = get_json(f"/api/reports/{test_rep_id}")
    assert status == 200
    report = rep_res["report"]
    assert report["report_status"] == "signed"
    assert report["signature_valid"] == 1
    assert report["report_version"] == 1
    assert report["content_hash"] != ""
    assert report["signature_data"] == sig_payload["signatureData"]

    # Step 2: Attempt Unauthorized Signature Replacement (Wrong Password)
    bad_replace_payload = {
        "reportId": test_rep_id,
        "doctorId": "admin@gmail.com",
        "password": "wrongpassword123",
        "reason": "Replacing with doctor signature",
        "signatureData": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAEklEQVR42mNk+M/AwMDAwMAAAAcAAv6tWwAAAAAElFTkSuQmCC"
    }
    status, bad_res = post_json("/api/reports/replace-signature", bad_replace_payload)
    assert status == 401, f"Expected 401 Unauthorized, got {status}: {bad_res}"
    assert bad_res["success"] is False
    assert "Re-authentication failed" in bad_res["error"]

    # Verify report was NOT modified
    status, rep_res = get_json(f"/api/reports/{test_rep_id}")
    assert rep_res["report"]["signature_data"] == sig_payload["signatureData"]
    assert rep_res["report"]["report_version"] == 1

    # Verify unauthorized attempt is logged in audit trail
    status, audit_res = get_json(f"/api/reports/{test_rep_id}/signature-history")
    assert status == 200
    history = audit_res["history"]
    assert len(history) >= 2
    actions = [h["action"] for h in history]
    outcomes = [h["outcome"] for h in history]
    assert "INITIAL_SIGN" in actions
    assert "REPLACE_SIGNATURE_ATTEMPT" in actions
    assert "UNAUTHORIZED_ATTEMPT" in outcomes

    # Step 3: Attempt Replacement with Missing / Short Reason
    short_reason_payload = {
        "reportId": test_rep_id,
        "doctorId": "admin@gmail.com",
        "password": "admin123",
        "reason": "bad",  # < 5 characters
        "signatureData": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAEklEQVR42mNk+M/AwMDAwMAAAAcAAv6tWwAAAAAElFTkSuQmCC"
    }
    status, short_res = post_json("/api/reports/replace-signature", short_reason_payload)
    assert status == 400
    assert "mandatory" in short_res["error"].lower()

    # Step 4: Authorized Signature Replacement
    new_sig = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAEklEQVR42mNk+M/AwMDAwMAAAAcAAv6tWwAAAAAElFTkSuQmCC"
    valid_replace_payload = {
        "reportId": test_rep_id,
        "doctorId": "admin@gmail.com",
        "password": "admin123",
        "reason": "Previous signature was skewed due to stylus calibration error. Replaced with corrected clinician signature.",
        "signatureData": new_sig,
        "signatureHash": "TORUS-SIG-CORRECTED-002"
    }
    status, rep_success = post_json("/api/reports/replace-signature", valid_replace_payload)
    assert status == 200, f"Authorized replacement failed: {rep_success}"
    assert rep_success["success"] is True
    assert rep_success["version"] == 2

    # Verify report reflects new signature and version 2
    status, rep_res = get_json(f"/api/reports/{test_rep_id}")
    report = rep_res["report"]
    assert report["signature_valid"] == 1
    assert report["report_version"] == 2
    assert report["signature_data"] == new_sig

    # Verify audit trail preserves both signatures and reasons
    status, audit_res = get_json(f"/api/reports/{test_rep_id}/signature-history")
    history = audit_res["history"]
    replace_events = [h for h in history if h["action"] == "REPLACE_SIGNATURE" and h["outcome"] == "SUCCESS"]
    assert len(replace_events) == 1
    ev = replace_events[0]
    assert ev["previous_signature_data"] == sig_payload["signatureData"]
    assert ev["new_signature_data"] == new_sig
    assert ev["doctor_id"] == "3001"
    assert "stylus calibration error" in ev["replacement_reason"]

    # Step 5: Content Change Invalidation
    # Doctor or user edits findings on the signed report
    update_payload = {
        "findings": "MODIFIED FINDINGS: New hepatic hemangioma 1.2 cm detected on review."
    }
    status, upd_res = post_json(f"/api/reports/{test_rep_id}/update", update_payload)
    assert status == 200
    assert upd_res.get("signatureInvalidated") is True

    # Check that report status is now signature_required and signature_valid is 0
    status, rep_res = get_json(f"/api/reports/{test_rep_id}")
    report = rep_res["report"]
    assert report["report_status"] == "signature_required"
    assert report["signature_valid"] == 0
    # Signature data should be hidden/null for invalid signature
    assert report["signature_data"] is None

    # Verify audit history records invalidation
    status, audit_res = get_json(f"/api/reports/{test_rep_id}/signature-history")
    history = audit_res["history"]
    inval_events = [h for h in history if h["action"] == "CONTENT_MODIFIED_INVALIDATION"]
    assert len(inval_events) == 1
    assert inval_events[0]["outcome"] == "SIGNATURE_INVALIDATED"

    # Step 6: Test PDF consistency
    # Download PDF when signature is invalidated
    pdf_req = urllib.request.Request(f"{BASE_URL}/api/reports/{test_rep_id}/download")
    with urllib.request.urlopen(pdf_req) as pdf_resp:
        assert pdf_resp.status == 200
        pdf_bytes = pdf_resp.read()
        assert len(pdf_bytes) > 1000

    print("All signature replacement and audit history tests passed successfully!")

if __name__ == "__main__":
    test_full_signature_replacement_and_audit_workflow()
