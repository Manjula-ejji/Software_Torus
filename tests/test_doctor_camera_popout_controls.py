import os
import re
import unittest

class TestDoctorCameraPopoutControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cls.app_js_path = os.path.join(cls.repo_root, "frontend", "app.js")
        with open(cls.app_js_path, "r", encoding="utf-8") as f:
            cls.app_js = f.read()

    def test_syncDoctorPopoutControls_does_not_override_fit_or_pin(self):
        """Ensure periodic sync loop does not overwrite popout window's independent Fit and Focus states."""
        # Find syncDoctorPopoutControls function
        match = re.search(r"function\s+syncDoctorPopoutControls\s*\(\)\s*\{([\s\S]*?)\n\}", self.app_js)
        self.assertIsNotNone(match, "syncDoctorPopoutControls function not found in app.js")
        func_body = match.group(1)

        # It should sync camera and mic, but NOT force fit-contain/fit-cover or pinned state from parent
        self.assertNotIn("childFitBtn.textContent =", func_body)
        self.assertNotIn("childPinBtn.textContent =", func_body)
        self.assertNotIn("popoutCard.classList.remove(\"fit-cover\")", func_body)
        self.assertNotIn("popoutCard.classList.remove(\"pinned\")", func_body)

    def test_openDoctorPopoutWindow_focus_handler_does_not_call_togglePin_parent(self):
        """Ensure clicking Focus/Unfocus in the popout window does not call togglePin(parentCard)."""
        match = re.search(r"function\s+openDoctorPopoutWindow\s*\(\)\s*\{([\s\S]*?)\n\}", self.app_js)
        self.assertIsNotNone(match, "openDoctorPopoutWindow function not found in app.js")
        func_body = match.group(1)

        self.assertNotIn("togglePin(parentCard)", func_body, "Doctor popout Focus handler must not toggle parent card pin state")

    def test_openDoctorPopoutWindow_has_independent_fit_handler(self):
        """Ensure popout window's Fit/Fill handler operates exclusively on the child window DOM and video."""
        match = re.search(r"function\s+openDoctorPopoutWindow\s*\(\)\s*\{([\s\S]*?)\n\}", self.app_js)
        self.assertIsNotNone(match, "openDoctorPopoutWindow function not found in app.js")
        func_body = match.group(1)

        self.assertIn("childFitBtn.addEventListener", func_body)
        self.assertIn("object-fit", func_body)
        self.assertIn("popoutVideo.style.setProperty", func_body)

    def test_openDoctorPopoutWindow_has_independent_focus_handler(self):
        """Ensure popout window's Focus/Unfocus handler toggles focus effect on child card and player."""
        match = re.search(r"function\s+openDoctorPopoutWindow\s*\(\)\s*\{([\s\S]*?)\n\}", self.app_js)
        self.assertIsNotNone(match, "openDoctorPopoutWindow function not found in app.js")
        func_body = match.group(1)

        self.assertIn("childPinBtn.addEventListener", func_body)
        self.assertIn("childPinBtn.textContent = \"Unfocus\"", func_body)
        self.assertIn("childPinBtn.textContent = \"Focus\"", func_body)
        self.assertIn("popoutCard.classList.add(\"pinned\")", func_body)
        self.assertIn("popoutCard.classList.remove(\"pinned\")", func_body)

    def test_syncDoctorPopoutPlayer_respects_popout_fit_mode(self):
        """Ensure syncDoctorPopoutPlayer sets object-fit according to popoutCard's independent fit mode."""
        match = re.search(r"function\s+syncDoctorPopoutPlayer\s*\(\)\s*\{([\s\S]*?)\n\}", self.app_js)
        self.assertIsNotNone(match, "syncDoctorPopoutPlayer function not found in app.js")
        func_body = match.group(1)

        self.assertIn("popoutCard.classList.contains(\"fit-cover\")", func_body)
        self.assertIn("childVideo.style.setProperty(\"object-fit\"", func_body)

    def test_parent_controls_remain_intact(self):
        """Verify main dashboard local controls (localFitBtn, localPinBtn, etc.) remain in place."""
        self.assertIn("localFitBtn.addEventListener", self.app_js)
        self.assertIn("localPinBtn.addEventListener", self.app_js)
        self.assertIn("toggleFit(localCard, localFitBtn)", self.app_js)
        self.assertIn("togglePin(localCard)", self.app_js)

if __name__ == "__main__":
    unittest.main()
