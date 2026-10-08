import urllib.request
import re

def test_header_and_navigation():
    # 1. Fetch report-generation.html from Flask server
    html = urllib.request.urlopen('http://127.0.0.1:5000/report-generation.html?room=torus&role=doctor').read().decode('utf-8')

    # Extract <header class="topbar"> block
    header_match = re.search(r'<header class="topbar">(.*?)</header>', html, re.DOTALL)
    assert header_match is not None, 'Could not find <header class="topbar">'
    header_html = header_match.group(1)

    assert 'topbar-left' in header_html, 'Missing topbar-left in header'
    assert 'brand-wordmark' in header_html and 'TORUS' in header_html, 'Missing TORUS wordmark in header'
    assert 'brand-logo' in header_html and 'logo.png' in header_html, 'Missing TORUS logo in header'
    assert 'id="backBtn"' in header_html, 'Missing backBtn in header'
    assert 'id="menuToggle"' not in header_html, 'menuToggle should not be present in topbar'
    assert 'profile-pill' not in header_html, 'profile-pill should not be present in topbar'
    assert 'navigateBackFromReport' in html, 'Missing navigateBackFromReport'
    assert 'app-dashboard' in html, 'Missing app-dashboard return target'

    # 2. Fetch index.html
    index_html = urllib.request.urlopen('http://127.0.0.1:5000/').read().decode('utf-8')
    assert 'app-dashboard' in index_html, 'Missing app-dashboard screen in index.html'
    assert 'torus_return_from_report' in index_html, 'Missing torus_return_from_report in index.html'

    # 3. Fetch app.js
    app_js = urllib.request.urlopen('http://127.0.0.1:5000/app.js').read().decode('utf-8')
    assert 'torus_return_from_report' in app_js, 'Missing torus_return_from_report in app.js'
    assert 'navigateToReportGeneration' in app_js, 'Missing navigateToReportGeneration in app.js'

    # 4. Fetch report-generation.js
    rep_js = urllib.request.urlopen('http://127.0.0.1:5000/report-generation.js').read().decode('utf-8')
    assert 'navigateBackFromReport' in rep_js, 'Missing navigateBackFromReport in report-generation.js'
    assert 'app-dashboard' in rep_js, 'Missing app-dashboard in report-generation.js'

    # 5. Verify Persistent Navigation Stack Engine in app.js
    assert 'getTorusScreenStack' in app_js, 'Missing getTorusScreenStack in app.js'
    assert 'popTorusScreenFromStack' in app_js, 'Missing popTorusScreenFromStack in app.js'
    assert 'pushTorusScreenToStack' in app_js, 'Missing pushTorusScreenToStack in app.js'

    # 6. Verify Screen 3 (Doctor Login) -> Role selection is preserved
    assert 'id="doctor-login-back-btn"' in index_html, 'Missing doctor-login-back-btn on Screen 3'
    assert 'navigateBackToRoleSelection()' in index_html, 'Screen 3 Back button must preserve navigateBackToRoleSelection()'

    print("ALL 6 INTEGRATION CHECKS FOR TORUS BACK NAVIGATION ARCHITECTURE PASSED SUCCESSFULLY!")

if __name__ == '__main__':
    test_header_and_navigation()
