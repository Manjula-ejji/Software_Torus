import os
import sys
import json
import base64
import io
import urllib.request
import urllib.error
from PIL import Image, ImageDraw

BASE_URL = "http://127.0.0.1:5000"

def create_webpage_screenshot_base64():
    im = Image.new("RGB", (800, 600), color=(255, 255, 255))
    draw = ImageDraw.Draw(im)
    draw.rectangle([0, 0, 800, 50], fill=(240, 240, 240))
    draw.rectangle([20, 10, 100, 40], fill=(0, 120, 215))
    draw.text((30, 20), "Torus UI Screenshot", fill=(0, 0, 0))
    draw.rectangle([50, 100, 750, 550], outline=(200, 200, 200), fill=(250, 250, 250))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64}"

def get_sample_ultrasound_base64():
    path = os.path.join(os.path.dirname(__file__), "..", "frontend", "sample_ultrasound.jpg")
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"

def get_logo_base64():
    path = os.path.join(os.path.dirname(__file__), "..", "frontend", "assets", "doctor-logo.png")
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:image/png;base64,{b64}"

def run_tests():
    print("Testing Non-Ultrasound Image Validation & Filtering...")
    
    us_img = get_sample_ultrasound_base64()
    screenshot_img = create_webpage_screenshot_base64()
    logo_img = get_logo_base64()
    
    # 1. Genuine ultrasound image accepted
    payload_valid = {
        "images": [{"id": "img_us_1", "dataUrl": us_img}],
        "patientInfo": {"patientName": "Validation Subject", "scanType": "Abdominal Ultrasound"},
        "testMode": True
    }
    req = urllib.request.Request(
        f"{BASE_URL}/api/ai/analyze",
        data=json.dumps(payload_valid).encode(),
        headers={"Content-Type": "application/json"}
    )
    res = urllib.request.urlopen(req)
    assert res.status == 200, f"Expected 200, got {res.status}"
    body = json.loads(res.read().decode())
    assert body.get("success") is True
    assert body.get("analyzed_count") == 1
    assert body.get("excluded_count") == 0
    print("[PASS] Test 1: Genuine ultrasound image accepted (analyzed: 1, excluded: 0).")

    # 2. Webpage screenshot rejection
    payload_screenshot = {
        "images": [{"id": "img_ss_1", "dataUrl": screenshot_img}],
        "patientInfo": {"patientName": "Validation Subject"},
        "testMode": True
    }
    try:
        req = urllib.request.Request(
            f"{BASE_URL}/api/ai/analyze",
            data=json.dumps(payload_screenshot).encode(),
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req)
        assert False, "Expected 400 when sending UI screenshot"
    except urllib.error.HTTPError as e:
        assert e.code == 400, f"Expected 400, got {e.code}"
        err_body = json.loads(e.read().decode())
        assert err_body.get("success") is False
        assert "No valid ultrasound images selected for analysis" in err_body.get("error", "")
        assert err_body.get("valid_count") == 0
        assert err_body.get("excluded_count") == 1
        print(f"[PASS] Test 2: UI screenshot rejected correctly with 400: {err_body['error']}")

    # 3. Color logo / photo rejection
    payload_logo = {
        "images": [{"id": "img_logo_1", "dataUrl": logo_img}],
        "patientInfo": {"patientName": "Validation Subject"},
        "testMode": True
    }
    try:
        req = urllib.request.Request(
            f"{BASE_URL}/api/ai/analyze",
            data=json.dumps(payload_logo).encode(),
            headers={"Content-Type": "application/json"}
        )
        urllib.request.urlopen(req)
        assert False, "Expected 400 when sending color graphic / logo"
    except urllib.error.HTTPError as e:
        assert e.code == 400, f"Expected 400, got {e.code}"
        err_body = json.loads(e.read().decode())
        assert err_body.get("success") is False
        assert "No valid ultrasound images selected for analysis" in err_body.get("error", "")
        print(f"[PASS] Test 3: Color graphic/logo rejected correctly with 400: {err_body['error']}")

    # 4. Mixed candidate images: 1 valid ultrasound + 1 UI screenshot + 1 logo
    payload_mixed = {
        "images": [
            {"id": "img_us_1", "dataUrl": us_img},
            {"id": "img_ss_1", "dataUrl": screenshot_img},
            {"id": "img_logo_1", "dataUrl": logo_img}
        ],
        "patientInfo": {"patientName": "Validation Subject", "scanType": "Abdominal Ultrasound"},
        "testMode": True
    }
    req = urllib.request.Request(
        f"{BASE_URL}/api/ai/analyze",
        data=json.dumps(payload_mixed).encode(),
        headers={"Content-Type": "application/json"}
    )
    res = urllib.request.urlopen(req)
    assert res.status == 200, f"Expected 200 for mixed analysis, got {res.status}"
    mixed_body = json.loads(res.read().decode())
    assert mixed_body.get("success") is True
    assert mixed_body.get("analyzed_count") == 1
    assert mixed_body.get("excluded_count") == 2
    excluded = mixed_body.get("excluded_images", [])
    assert len(excluded) == 2
    ex_ids = [item["id"] for item in excluded]
    assert "img_ss_1" in ex_ids and "img_logo_1" in ex_ids
    summary = mixed_body.get("results", {}).get("summary", [])
    summary_text = " ".join(summary)
    assert "excluded" in summary_text.lower()
    print(f"[PASS] Test 4: Mixed images correctly partitioned: 1 analyzed, 2 excluded ({ex_ids}).")

    print("\nALL IMAGE VALIDATION TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    run_tests()
