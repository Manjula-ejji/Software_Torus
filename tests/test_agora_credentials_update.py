import os
import unittest
from backend import server, ultrasound

EXPECTED_APP_ID = "59dc3449de824523a83fba05047c73ad"
EXPECTED_TOKEN = "007eJxTYJigXCfCqpndnJz4xuSdhoJcYoqQ+Z2OqkVmCvcfJB9qYFVgMLVMSTY2MbFMSbUwMjE1Mk60ME5LSjQwNTAxTzY3TkzZdpM9uyGQkUFqgx0zIwMEgvisDCX5RaXFDAwAZZMcrg=="
EXPECTED_CLEAN_APP_ID = "59dc3449"

OLD_APP_IDS = ["6b706196744b487ea1402d829b714459", "e38b9a28f0f24fd7839939af97361cb2", "cf136a322cf74d449aba8c6695441d3b", "f6a036d79c9b4d669bb076d61047528e", "9f3eb0c721cf4d5e86fe506ccf085fa1", "7fdf07a2b99140589bd0881b3ef8c380", "26da1ebca94b427b80177eff6d44ddfa", "af7e44fcb2fd40258594cb87ab4d8e86"]
OLD_TOKENS = [
    "007eJxTYNDbY9GkZdZ699mxi949n7fsevvo1xZXjanTp7kfWpPz68ZEBQZTy5RkYxMTy5RUCyMTUyPjRAvjtKREA1MDE/Nkc+PElA8b2LMbAhkZRPIEWBgZIBDEZ2UoyS8qLWZgAABzLCKv",
    "007eJxTYHh9xy71ZWn/r4nNvGwZ1ytesNjvPHshTmXHaiU7z4L771kUGMySzA3MDC3NzE1MkkwszFMTDU0MjFIsjCyTzA1NTEwt/2WyZTcEMjLY7trCwAiFID4rQ0l+UWkxAwMAk/0f2w==",
    "007eJxTYEiW1lO9fP3h97L+yP4nKtEnJbNOupqY/tklrTPF1t81o1+BIdXYIsky0cgizSDNyCQtxdzC2NLS2DIxzdLc2MwwOcmIS4g1uyGQkUFuTjALIwMEgvisDCX5RaXFDAwA98IdMQ==",
    "007eJxTYPB48Lmka53u8lduGbpuB2W2L9XVKNzd/yPp48N7842Elq1XYDBIsTSxNDc3NjM3STKxNDNOtDBMtUw1TEoxN0kzT01OXGq6LqshkJFh9vwbzIwMEAjiszKU5BeVFjMwAADsfiIM",
    "007eJxTYFi84eApj/OTQj70XTCaXT5tSsvElAus6s57pu39eUpZyZVFgSE5zdDYLNHYyCg5zdwkxcTEMjEp0SLZzMzS1MTEMMU4af3l/1kNgYwMbquWsDIyQCCIz8pQkl9UWszAAAAF7CId",
    "007eJxTYFDqOnCaQVjrQXv3o6q2c+0/g9fe/Wy0s+O95kIXBnNV5WsKDGlmiQbGZinmlsmWSSYpZmaWSUkG5mYpZoYGJuamRhapW6//y2oIZGT4/fAJMyMDBIL4rAwl+UWlxQwMAM4RIl8=",
    "007eJxTYHiVsU9y/vRch6WhumfWdwd/PNx6usd1i53e3LX/V9m2LDRXYLBMM05NMkg2NzJMTjNJMU21MEtLNTUwS05OM7AwTUs0/FH3N6shkJGBx5mJiZEBAkF8VoaS/KLSYgYGAAYoIb4=",
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

    def test_api_agora_config_rejects_mismatched_environment_token(self):
        """Verify that when a token generated for an old/different App ID exists in env (e.g. on Render), it falls back to EXPECTED_TOKEN."""
        bad_token = OLD_TOKENS[1]
        orig_agora_tok = os.environ.get("AGORA_TOKEN")
        orig_open_tok = os.environ.get("OPENSONICS_TOKEN")
        try:
            os.environ["AGORA_TOKEN"] = bad_token
            os.environ["OPENSONICS_TOKEN"] = bad_token
            resp = self.client.get("/api/agora/config")
            self.assertEqual(resp.status_code, 200)
            data = resp.get_json()
            self.assertEqual(data.get("appId"), EXPECTED_APP_ID)
            self.assertEqual(data.get("token"), EXPECTED_TOKEN)
        finally:
            if orig_agora_tok is not None:
                os.environ["AGORA_TOKEN"] = orig_agora_tok
            else:
                os.environ.pop("AGORA_TOKEN", None)
            if orig_open_tok is not None:
                os.environ["OPENSONICS_TOKEN"] = orig_open_tok
            else:
                os.environ.pop("OPENSONICS_TOKEN", None)

    def test_is_valid_agora_token_for_appid_helper(self):
        """Verify the helper accurately validates token signatures matching App ID."""
        self.assertTrue(server.is_valid_agora_token_for_appid(EXPECTED_TOKEN, EXPECTED_APP_ID))
        self.assertFalse(server.is_valid_agora_token_for_appid(OLD_TOKENS[1], EXPECTED_APP_ID))
        self.assertFalse(server.is_valid_agora_token_for_appid("", EXPECTED_APP_ID))
        self.assertFalse(server.is_valid_agora_token_for_appid("invalid_token", EXPECTED_APP_ID))

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

    def test_frontend_files_do_not_hardcode_tokens(self):
        """Verify that frontend app.js and index.html do not hardcode secret Agora tokens."""
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        index_path = os.path.join(repo_root, "frontend", "index.html")
        app_path = os.path.join(repo_root, "frontend", "app.js")

        with open(index_path, "r", encoding="utf-8") as f:
            index_content = f.read()
        self.assertNotIn("007eJxTY", index_content)

        with open(app_path, "r", encoding="utf-8") as f:
            app_content = f.read()
        self.assertNotIn("007eJxTY", app_content)
        self.assertNotIn("CANONICAL_TOKEN_VALUE", app_content)

if __name__ == "__main__":
    unittest.main()
