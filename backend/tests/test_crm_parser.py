"""Pure-text checks for Ask ERP's CRM understanding — no database needed."""
import unittest
from datetime import datetime

from app.ai import crm_parser as p

NOW = datetime(2026, 9, 29, 11, 0)  # a Tuesday, 11:00 local


class IntentTests(unittest.TestCase):
    def test_intents(self):
        cases = {
            "what's overdue today": "crm.overdue",
            "What do I have due today?": "crm.overdue",
            "which deals are going stale": "crm.stale",
            "how's the pipeline": "crm.pipeline",
            "log a call with Rahman Traders — no answer": "crm.log_activity",
            "called nisha, she wants 200 boxes": "crm.log_activity",
            "whatsapped Kannur tiles the price list": "crm.log_activity",
            "remind me to call Nisha tomorrow at 3pm": "crm.schedule_followup",
            "call Rahman next week": "crm.schedule_followup",
            "mark Malabar Hardware lost — price too high": "crm.move_stage",
            "we won the Vadakara deal": "crm.move_stage",
            "Create a quotation for Rahman Traders: 50 boxes Product A": "sales.create_quotation",
            "quotation Rahman Traders 50 boxes Product A": "sales.create_quotation",
            "hello": "unknown",
        }
        for text, intent in cases.items():
            with self.subTest(text=text):
                self.assertEqual(p.classify_intent(text, NOW), intent)

    def test_team_scope(self):
        self.assertTrue(p.wants_everyone("what's overdue for the team"))
        self.assertFalse(p.wants_everyone("what's overdue today"))


class PieceTests(unittest.TestCase):
    def test_activity_type_stage_and_notes(self):
        self.assertEqual(p.activity_type("whatsapped Kannur tiles"), "WhatsApp")
        self.assertEqual(p.activity_type("met Al Faisal"), "Meeting")
        self.assertEqual(p.target_stage("move Beypore from proposal to negotiation"), "Negotiation")
        self.assertEqual(p.trailing_note("called nisha, she wants 200 boxes"), "she wants 200 boxes")
        self.assertEqual(p.lost_reason("Mark Malabar — branch expansion lost — Price too high"), "Price too high")
        self.assertEqual(p.lost_reason("mark Malabar lost"), "")


class WhenTests(unittest.TestCase):
    def at(self, text):
        when, _ = p.parse_when(text, NOW)
        return when.at if when else None

    def test_relative_and_absolute_dates(self):
        self.assertEqual(self.at("tomorrow at 3pm"), datetime(2026, 9, 30, 15, 0))
        self.assertEqual(self.at("on Friday"), datetime(2026, 10, 2, 10, 0))
        self.assertEqual(self.at("next week"), datetime(2026, 10, 5, 10, 0))
        self.assertEqual(self.at("in 3 days"), datetime(2026, 10, 2, 10, 0))
        self.assertEqual(self.at("on 5 Oct at 11:30"), datetime(2026, 10, 5, 11, 30))
        self.assertEqual(self.at("on 3/10"), datetime(2026, 10, 3, 10, 0))  # dd/mm
        self.assertEqual(self.at("naale"), datetime(2026, 9, 30, 10, 0))  # Malayalam "tomorrow"
        self.assertEqual(self.at("at 9am"), datetime(2026, 9, 30, 9, 0))  # already past today -> tomorrow
        self.assertEqual(self.at("at 3"), datetime(2026, 9, 29, 15, 0))  # business hours -> pm
        self.assertIsNone(self.at("sometime"))

    def test_impossible_date(self):
        when, problem = p.parse_when("on 31/02", NOW)
        self.assertIsNone(when)
        self.assertTrue(problem)


if __name__ == "__main__":
    unittest.main()
