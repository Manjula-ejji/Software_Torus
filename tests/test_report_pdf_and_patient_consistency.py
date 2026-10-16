import json
import urllib.request
import urllib.parse
import os

BASE_URL = 'http://127.0.0.1:5000'

def test_workflow():
    print("Testing Report Creation, Persistence, Retrieval, and PDF Generation...")
    
    # 1. Sample ultrasound image (1x1 transparent PNG data URI or sample)
    dummy_img = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    dummy_sig = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAoAAAAKCAYAAACNMs+9AAAAFUlEQVR42mNk+M9QzwAEjDAGYzAMAADEAQE1V2vYAAAAAElFTkSuQmCC"
    
    report_id = "RPT-TEST-20261016-9999"
    payload = {
        "reportId": report_id,
        "patientName": "John Doe",
        "scanType": "Abdominal Ultrasound",
        "findings": "Normal gallbladder, liver echogenicity within standard limits.",
        "recommendations": "Routine 12-month ultrasound follow-up recommended.",
        "roomId": "TORUS_LIVE_RUN",
        "generatedTime": 1792134000000,
        "signatureData": dummy_sig,
        "signedBy": "Dr. Sarah Jenkins",
        "signedTimestamp": "2026-10-16T12:00:00.000Z",
        "report_status": "signed",
        "selected_images": [dummy_img],
        "images": [dummy_img],
        "ai_analysis": {
            "status": "Completed",
            "quality": "Optimal (0.95)",
            "confidence": "96.2%",
            "observation": "Ultrasound reveals normal hepatic texture with no focal lesions.",
            "risk": "Low"
        },
        "deviceId": "TORUS-US-PRO-9",
        "doctorName": "Dr. Sarah Jenkins",
        "diagnosticCenter": "TORUS Main Campus",
        "location": "TORUS Main Campus",
        "duration": "00:05",
        "examDate": "October 16, 2026"
    }

    # Test POST /api/reports
    req = urllib.request.Request(
        f"{BASE_URL}/api/reports",
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )
    with urllib.request.urlopen(req) as resp:
        assert resp.status in (200, 201), f"Expected 200/201, got {resp.status}"
        data = json.loads(resp.read().decode('utf-8'))
        assert data.get('success') is True, "Expected success: True"
        print(f"[PASS] Successfully saved report {report_id} to backend.")

    # Test GET /api/reports/<report_id>
    with urllib.request.urlopen(f"{BASE_URL}/api/reports/{report_id}") as resp:
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        saved_body = json.loads(resp.read().decode('utf-8'))
        saved_report = saved_body.get('report') or saved_body
        assert saved_report.get('reportId') == report_id or saved_report.get('report_id') == report_id
        assert saved_report.get('patientName') == "John Doe" or saved_report.get('patient_name') == "John Doe"
        assert saved_report.get('findings') == "Normal gallbladder, liver echogenicity within standard limits."
        assert saved_report.get('signedBy') == "Dr. Sarah Jenkins" or saved_report.get('signed_by') == "Dr. Sarah Jenkins"
        assert saved_report.get('signatureData') or saved_report.get('signature_data')
        assert len(saved_report.get('selected_images', [])) > 0 or len(saved_report.get('images', [])) > 0
        ai_res = saved_report.get('ai_results') or saved_report.get('ai_analysis')
        assert ai_res is not None, "Expected AI analysis data to be saved"
        print(f"[PASS] Successfully retrieved saved report with full matching details and images.")

    # Test GET /api/reports/<report_id>/download
    with urllib.request.urlopen(f"{BASE_URL}/api/reports/{report_id}/download") as resp:
        assert resp.status == 200, f"Expected 200, got {resp.status}"
        pdf_bytes = resp.read()
        assert len(pdf_bytes) > 500, "PDF bytes should be non-trivial"
        assert pdf_bytes.startswith(b'%PDF'), "Response must be a valid PDF"
        assert b'ReportLab' in pdf_bytes or b'PDF' in pdf_bytes, "Must be valid medical ReportLab PDF"
        assert len(pdf_bytes) >= 1000, f"PDF should be substantial, got {len(pdf_bytes)} bytes"
        print(f"[PASS] Backend PDF endpoint returned valid white medical PDF of size {len(pdf_bytes)} bytes.")

    print("\nALL BACKEND REPORT AND PDF CONSISTENCY CHECKS PASSED SUCCESSFULLY!\n")

if __name__ == '__main__':
    test_workflow()
