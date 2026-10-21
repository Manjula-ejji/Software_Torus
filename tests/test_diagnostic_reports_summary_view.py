import os

def test_diagnostic_reports_summary_view():
    index_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    css_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "css", "styles.css")
    js_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "app.js")

    assert os.path.exists(index_path), "frontend/index.html must exist"
    assert os.path.exists(css_path), "frontend/css/styles.css must exist"
    assert os.path.exists(js_path), "frontend/app.js must exist"

    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()

    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()

    with open(js_path, "r", encoding="utf-8") as f:
        js = f.read()

    # 1. HTML Verification: Doctor Diagnostic Reports Summary Header (overview card removed)
    assert 'id="doctorReportsHeaderCard"' in html, "doctorReportsHeaderCard ID must exist"
    assert 'class="drep-collapse-btn"' in html, "drep-collapse-btn class must exist"
    assert 'class="drep-collapse-icon-minus"' in html, "Minus icon must exist"
    assert 'class="drep-collapse-icon-plus"' in html, "Plus icon must exist"
    assert 'id="patientDiagnosticReportsHeaderCard"' not in html, "patientDiagnosticReportsHeaderCard was removed"

    # 2. CSS Verification: Expanded and Compact View Styles
    assert '.dact-header-card' in css, ".dact-header-card must be defined in CSS"
    assert '.dact-header-card.is-compact' in css, ".dact-header-card.is-compact must be defined in CSS"
    assert '.dact-header-text' in css, ".dact-header-text styling must exist"
    assert 'padding: 8px 22px' in css, "Reduced padding must be present in compact view"
    assert 'display: none !important' in css, "Minus icon hidden in compact state"

    # 3. JavaScript Verification: Toggle and State Management
    assert 'function toggleDiagnosticReportsSummaryView' in js, "toggleDiagnosticReportsSummaryView must be defined"
    assert 'function setDiagnosticReportsSummaryView' in js, "setDiagnosticReportsSummaryView must be defined"
    assert 'function initDiagnosticReportsSummaryViews' in js, "initDiagnosticReportsSummaryViews must be defined"
    assert 'window.toggleDiagnosticReportsSummaryView = toggleDiagnosticReportsSummaryView' in js, "toggleDiagnosticReportsSummaryView must be exported to window"

    print("All Diagnostic Reports summary view tests passed successfully!")

if __name__ == "__main__":
    test_diagnostic_reports_summary_view()
