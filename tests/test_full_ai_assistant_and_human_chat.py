import unittest
import json
import urllib.request
import urllib.error
import time

BASE_URL = "http://127.0.0.1:5000"

class TestFullAiAssistantAndHumanChat(unittest.TestCase):
    """
    Comprehensive End-to-End Test Suite for Phase 13:
    - Conversational queries via Gemini LLM
    - TORUS Operational queries grounded in verified database records
    - Multi-turn follow-up conversations
    - Quick-prompt button simulations
    - Two-way Human Chat between doctors and patients/attenders
    - Security and error handling
    """

    def test_01_conversational_questions(self):
        """Phase 13.A: Tests all 10 conversational questions individually against /api/ai-assistant/chat."""
        questions = [
            "Hi",
            "Hello",
            "How are you?",
            "What is your name?",
            "Who are you?",
            "What can you do?",
            "Can you help me?",
            "Thank you.",
            "What is artificial intelligence?",
            "Explain machine learning simply."
        ]
        for q in questions:
            payload = json.dumps({
                "question": q,
                "user_id": "3001",
                "role": "doctor"
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{BASE_URL}/api/ai-assistant/chat",
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            res = urllib.request.urlopen(req, timeout=20)
            self.assertEqual(res.status, 200, f"Expected 200 for question: {q}")
            data = json.loads(res.read().decode())
            self.assertTrue(data.get("success"), f"Failed for question '{q}': {data.get('error')}")
            answer = (data.get("answer") or data.get("response") or "").strip()
            self.assertTrue(len(answer) > 5, f"Answer too short for '{q}': {answer}")
            self.assertIn("message", data)
            self.assertEqual(data["message"]["role"], "assistant")

    def test_02_operational_questions(self):
        """Phase 13.B: Tests operational questions grounded in verified TORUS records."""
        operational_queries = [
            "Which patients have pending reports?",
            "Which report emails failed today?",
            "Show my upcoming appointments.",
            "Why did this report delivery fail?",
            "What is the status of this report?"
        ]
        for q in operational_queries:
            payload = json.dumps({
                "question": q,
                "user_id": "3001",
                "role": "doctor"
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{BASE_URL}/api/ai-assistant/chat",
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            res = urllib.request.urlopen(req, timeout=20)
            self.assertEqual(res.status, 200)
            data = json.loads(res.read().decode())
            self.assertTrue(data.get("success"), f"Failed operational query '{q}': {data.get('error')}")
            answer = data.get("answer") or data.get("response") or ""
            self.assertTrue(len(answer) > 10, f"Empty answer for operational query '{q}'")
            # Operational queries must return verified records context
            self.assertTrue(isinstance(data.get("data"), dict))

    def test_03_multiturn_followup_conversation(self):
        """Phase 13.C: Multi-turn conversation preserving context across follow-ups."""
        cid = f"test_e2e_conv_{int(time.time())}"
        
        # Turn 1
        p1 = json.dumps({
            "question": "Which report emails failed today?",
            "conversationId": cid,
            "user_id": "3001",
            "role": "doctor"
        }).encode("utf-8")
        req1 = urllib.request.Request(
            f"{BASE_URL}/api/ai-assistant/chat",
            data=p1,
            headers={"Content-Type": "application/json"}
        )
        res1 = json.loads(urllib.request.urlopen(req1, timeout=20).read().decode())
        self.assertTrue(res1.get("success"))
        self.assertEqual(res1.get("conversationId"), cid)

        # Turn 2: Follow-up question referencing turn 1 results
        p2 = json.dumps({
            "question": "Why did the first report fail?",
            "conversationId": cid,
            "user_id": "3001",
            "role": "doctor"
        }).encode("utf-8")
        req2 = urllib.request.Request(
            f"{BASE_URL}/api/ai-assistant/chat",
            data=p2,
            headers={"Content-Type": "application/json"}
        )
        res2 = json.loads(urllib.request.urlopen(req2, timeout=20).read().decode())
        self.assertTrue(res2.get("success"))
        answer2 = res2.get("answer", "").lower()
        # Should reference mailbox / quota / email failure reasons
        self.assertTrue(any(w in answer2 for w in ["inbox", "quota", "space", "delivery", "fail", "rpt"]))

    def test_04_quick_prompts(self):
        """Phase 13.D: Tests all 4 doctor quick-prompt buttons."""
        quick_chips = [
            "Which patients have pending reports?",
            "Which report emails failed today?",
            "Show my upcoming appointments.",
            "Why did this report delivery fail?"
        ]
        for chip in quick_chips:
            payload = json.dumps({
                "question": chip,
                "user_id": "3001",
                "role": "doctor"
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{BASE_URL}/api/ai-assistant/chat",
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            res = urllib.request.urlopen(req, timeout=20)
            data = json.loads(res.read().decode())
            self.assertTrue(data.get("success"))
            self.assertFalse(data.get("error"))

    def test_05_human_chat_twoway(self):
        """Phase 13.E: Real Two-Way Human Chat between Doctor and Patient."""
        conv_id = "conv_3001_4001"
        test_content_doc = f"Doctor message at {int(time.time())}"
        test_content_pat = f"Patient reply at {int(time.time())}"

        # 1. Doctor sends message
        p_doc = json.dumps({
            "sender_id": "3001",
            "sender_role": "doctor",
            "sender_name": "Dr. Admin Doctor",
            "content": test_content_doc
        }).encode("utf-8")
        req_doc = urllib.request.Request(
            f"{BASE_URL}/api/conversations/{conv_id}/messages",
            data=p_doc,
            headers={"Content-Type": "application/json"}
        )
        res_doc = json.loads(urllib.request.urlopen(req_doc).read().decode())
        self.assertTrue(res_doc.get("success"))

        # 2. Patient reads conversation and sees doctor message
        req_pat_read = urllib.request.Request(
            f"{BASE_URL}/api/conversations/{conv_id}/messages?user_id=4001&role=patient"
        )
        res_pat_read = json.loads(urllib.request.urlopen(req_pat_read).read().decode())
        self.assertTrue(res_pat_read.get("success"))
        contents = [m["content"] for m in res_pat_read.get("messages", [])]
        self.assertIn(test_content_doc, contents)

        # 3. Patient replies
        p_pat = json.dumps({
            "sender_id": "4001",
            "sender_role": "patient",
            "sender_name": "Patient User",
            "content": test_content_pat
        }).encode("utf-8")
        req_pat = urllib.request.Request(
            f"{BASE_URL}/api/conversations/{conv_id}/messages",
            data=p_pat,
            headers={"Content-Type": "application/json"}
        )
        res_pat = json.loads(urllib.request.urlopen(req_pat).read().decode())
        self.assertTrue(res_pat.get("success"))

        # 4. Doctor verifies patient reply is persisted and present
        req_doc_check = urllib.request.Request(
            f"{BASE_URL}/api/conversations/{conv_id}/messages?user_id=3001&role=doctor"
        )
        res_doc_check = json.loads(urllib.request.urlopen(req_doc_check).read().decode())
        self.assertTrue(res_doc_check.get("success"))
        updated_contents = [m["content"] for m in res_doc_check.get("messages", [])]
        self.assertIn(test_content_pat, updated_contents)

    def test_06_error_handling_empty_question(self):
        """Phase 13.F: Empty or whitespace-only question returns 400 with QUESTION_REQUIRED."""
        for empty_val in ["", "   ", None]:
            payload = json.dumps({
                "question": empty_val,
                "user_id": "3001",
                "role": "doctor"
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{BASE_URL}/api/ai-assistant/chat",
                data=payload,
                headers={"Content-Type": "application/json"}
            )
            try:
                urllib.request.urlopen(req)
                self.fail("Expected 400 for empty question")
            except urllib.error.HTTPError as e:
                self.assertEqual(e.code, 400)
                err_data = json.loads(e.read().decode())
                self.assertFalse(err_data.get("success"))
                self.assertEqual(err_data.get("error", {}).get("code"), "QUESTION_REQUIRED")

if __name__ == "__main__":
    unittest.main()
