import os
import re

def test_report_generation_markup_and_logic():
    html_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "report-generation.html")
    assert os.path.exists(html_path), "report-generation.html must exist"
    
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    # 1. Captured Images Section
    # Check that imageCountPill does not have duplicate "0 / 0 images" in initial markup
    assert '<div class="pill-count" id="imageCountPill">0 Captured</div>' in html, "imageCountPill should show '0 Captured'"
    assert '<div class="value" id="selectedCount">0 / 0 Selected</div>' in html, "selectedCount should show '0 / 0 Selected'"
    assert 'dom.imageCountPill.textContent = `${total} Captured`' in html, "syncCounts should format imageCountPill as total Captured"
    assert 'dom.selectedCount.textContent = `${selected} / ${total} Selected`' in html, "syncCounts should format selectedCount as selected / total Selected"

    # 2. Patient Information and Report Details
    # Check that initial markup does not hardcode demo values
    assert '<div class="value" id="patientName">--</div>' in html, "patientName should initialize with fallback '--'"
    assert '<div class="value" id="examDate">--</div>' in html, "examDate should initialize with fallback '--'"
    assert '<div class="value" id="scanType">--</div>' in html, "scanType should initialize with fallback '--'"
    assert '<div class="value" id="deviceName">--</div>' in html, "deviceName should initialize with fallback '--'"
    assert '<div class="detail-value" id="examDuration">--</div>' in html, "examDuration should initialize with fallback '--'"
    assert '<div class="detail-value" id="doctorName">--</div>' in html, "doctorName should initialize with fallback '--'"
    assert '<div class="detail-value" id="locationName">--</div>' in html, "locationName should initialize with fallback '--'"
    assert '<div class="detail-value" id="reportId">--</div>' in html, "reportId should initialize with fallback '--'"

    # 3. AI Preliminary Analysis
    assert '<span id="aiStatusText">Ready to Analyze</span>' in html, "aiStatusText should initialize to 'Ready to Analyze'"
    assert '<span class="ai-insight-value" id="aiInsightQuality">--</span>' in html, "aiInsightQuality should initialize to '--'"
    assert '<span class="ai-insight-value" id="aiInsightConfidence">--</span>' in html, "aiInsightConfidence should initialize to '--'"
    assert '<span class="ai-insight-value" id="aiInsightStructures">--</span>' in html, "aiInsightStructures should initialize to '--'"
    assert '<span class="ai-insight-value" id="aiInsightObservation">Awaiting Analysis</span>' in html, "aiInsightObservation should initialize to 'Awaiting Analysis'"
    assert '<span class="ai-insight-value" id="aiInsightRisk">--</span>' in html, "aiInsightRisk should initialize to '--'"
    assert 'id="toggleAiDetails" disabled' in html, "toggleAiDetails should be disabled until analysis completed"

    # 4. Accidental test text sanitized
    assert 'sanitizeClinicalText' in html, "sanitizeClinicalText function must be present"
    assert 'hhhhhhhhhhhh' not in html, "accident test text 'hhhhhhhhhhhh' must not be in report-generation.html"
    assert 'fffffffffff' not in html, "accident test text 'fffffffffff' must not be in report-generation.html"

    # 5. Digital Signature
    assert 'updateSignatureUI(\'Signing\')' in html, "Signing status must be set during signing"
    assert 'updateSignatureUI(\'Failed\')' in html, "Failed status must be set on error"

    # 6. Medical Report Accuracy & Clinical Notice
    assert 'AI Preliminary Analysis is an automated assistive interpretation tool' in html, "Clinical notice must be present in report preview"

    print("All Report Generation Page checks passed successfully!")

if __name__ == "__main__":
    test_report_generation_markup_and_logic()
