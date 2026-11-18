import os
import unittest
from backend import server, ultrasound

EXPECTED_APP_ID = "9f3eb0c721cf4d5e86fe506ccf085fa1"
EXPECTED_TOKEN = "007eJxTYHiVsU9y/vRch6WhumfWdwd/PNx6usd1i53e3LX/V9m2LDRXYLBMM05NMkg2NzJMTjNJMU21MEtLNTUwS05OM7AwTUs0/FH3N6shkJGBx5mJiZEBAkF8VoaS/KLSYgYGAAYoIb4="
EXPECTED_CLEAN_APP_ID = "9f3eb0c7"

OLD_APP_IDS = ["7fdf07a2b99140589bd0881b3ef8c380", "26da1ebca94b427b80177eff6d44ddfa", "af7e44fcb2fd40258594cb87ab4d8e86"]
OLD_TOKENS = [
    "007eJxTYPBkl33R0jnpt1Z/xdne7eJHjYWm3Xo84fDNWWelnf/7RgUqMJinpaQZmCcaJVlaGpoYmFpYJqUYWFgYJhmnplkkG1sYXLf+mtUQyMhwu1mXiZEBAkF8VoaS/KLSYgYGAMEvIVM=",
    "007eJxTYGj7mPtYXMyS142n+PTR/Wkbt/Itrft/Z59n46T1Yff9FhUoMBiZpSQapiYlJ1qaJJkYmSdZGBiam6empZmlmJikpKQlLpj3NashkJHhnpIJMyMDBIL4rAwl+UWlxQwMANo7IgM=",
    "007eJxTYCh6F+xsnhe+b63AYwmfOHFJH6HKiK6Unh9qOjtNCgtsqhUYEtPMU01M0pKTjNJSTAyMTC1MLU2SkyzME5NMUixSLcz+/fqd1RDIyKBxfioDIxSC+KwMJflFpcUMDADI0R7/"
]

class TestAgoraCredentialsUpdate(unittest.TestCase):
    def setUp(self):
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()

    def test_api_agora_config_returns_updated_credentials(self):
        resp = self.client.get("/api/agora/config")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertEqual(data.get("appId"), EXPECTED_APP_ID)
        self.assertEqual(data.get("token"), EXPECTED_TOKEN)
        self.assertEqual(data.get("channel"), "torus")

    def test_backend_ultrasound_defaults_use_updated_credentials(self):
        self.assertEqual(ultrasound.APP_ID, EXPECTED_APP_ID)
        self.assertEqual(ultrasound.TOKEN, EXPECTED_TOKEN)

    def test_files_contain_no_old_credentials(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        files_to_check = [
            os.path.join(repo_root, "backend", "server.py"),
            os.path.join(repo_root, "backend", "ultrasound.py"),
            os.path.join(repo_root, "frontend", "app.js"),
            os.path.join(repo_root, "frontend", "index.html"),
            os.path.join(repo_root, ".env.example"),
        ]
        for fpath in files_to_check:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
            for old_id in OLD_APP_IDS:
                self.assertNotIn(old_id, content, f"Found old App ID {old_id} in {fpath}")
            for old_tok in OLD_TOKENS:
                self.assertNotIn(old_tok, content, f"Found old token in {fpath}")

    def test_frontend_files_contain_updated_app_id(self):
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        index_path = os.path.join(repo_root, "frontend", "index.html")
        app_path = os.path.join(repo_root, "frontend", "app.js")

        with open(index_path, "r", encoding="utf-8") as f:
            index_content = f.read()
        self.assertIn(EXPECTED_APP_ID, index_content)

        with open(app_path, "r", encoding="utf-8") as f:
            app_content = f.read()
        self.assertIn(EXPECTED_APP_ID, app_content)
        self.assertIn(f"control-{EXPECTED_CLEAN_APP_ID}", app_content)

if __name__ == "__main__":
    unittest.main()
