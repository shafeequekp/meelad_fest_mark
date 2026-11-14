"""Tests for the AI assistant Django boundary (auth, reads, writes)."""
import json
import time
from unittest import mock

import requests
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from applications.accounts.models import Madrasa, User
from applications.program.models import (
    Category, Prize, Program, Student, Venue,
)
from applications.scoreboard.models import Team
from .models import AIOperationAuditLog

SVC_TOKEN = "test-ai-service-token"


class FestRulesAITests(TestCase):
    """The AI service reads this madrasa's rules text for its RAG index —
    scoped to the acting user's madrasa and never another's."""

    def setUp(self):
        self.madrasa = Madrasa.objects.create(name="Rules M")
        self.other = Madrasa.objects.create(name="Other M")
        self.user = User.objects.create_user(
            email="a@t.com", phone_number="9000000001", madrasa=self.madrasa,
            password="x")

    def _get(self, **headers):
        base = {"HTTP_X_MEELAD_AI_TOKEN": SVC_TOKEN,
                "HTTP_X_MEELAD_USER_ID": str(self.user.id)}
        base.update(headers)
        return self.client.get(reverse("aiassistant:ai_fest_rules"), **base)

    @override_settings(MEELAD_AI_SERVICE_TOKEN=SVC_TOKEN)
    def test_requires_service_token_and_actor(self):
        self.assertEqual(self.client.get(
            reverse("aiassistant:ai_fest_rules")).status_code, 401)
        self.assertEqual(self.client.get(
            reverse("aiassistant:ai_fest_rules"),
            **{"HTTP_X_MEELAD_AI_TOKEN": SVC_TOKEN}).status_code, 403)

    @override_settings(MEELAD_AI_SERVICE_TOKEN=SVC_TOKEN)
    def test_no_rules_reports_has_rules_false(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["has_rules"])

    @override_settings(MEELAD_AI_SERVICE_TOKEN=SVC_TOKEN)
    def test_returns_own_madrasa_rules_text(self):
        self.madrasa.fest_rules = "fest_rules/rules.pdf"  # name only; text is what matters
        self.madrasa.fest_rules_text = (
            "Tie breaking: a coin toss by the chief judge decides the winner.")
        self.madrasa.fest_rules_updated_at = timezone.now()
        self.madrasa.save()
        resp = self._get()
        data = resp.json()
        self.assertTrue(data["has_rules"])
        self.assertEqual(data["madrasa_id"], self.madrasa.id)
        self.assertIn("coin toss", data["text"])
        self.assertIsNotNone(data["updated_at"])

    @override_settings(MEELAD_AI_SERVICE_TOKEN=SVC_TOKEN)
    def test_other_madrasa_rules_never_leak(self):
        self.other.fest_rules_text = "SECRET OTHER MADRASA RULE"
        self.other.save()
        resp = self._get()
        self.assertNotIn("SECRET OTHER MADRASA RULE", resp.content.decode())
        self.assertFalse(resp.json()["has_rules"])


class AIAuthTests(TestCase):
    """The service boundary must reject missing token / missing actor."""

    @override_settings(MEELAD_AI_SERVICE_TOKEN=SVC_TOKEN)
    def test_health_requires_service_token(self):
        bad = self.client.get(reverse("aiassistant:ai_health"))
        self.assertEqual(bad.status_code, 401)
        good = self.client.get(
            reverse("aiassistant:ai_health"),
            **{"HTTP_X_MEELAD_AI_TOKEN": SVC_TOKEN})
        self.assertEqual(good.status_code, 200)

    @override_settings(MEELAD_AI_SERVICE_TOKEN=SVC_TOKEN)
    def test_read_requires_actor(self):
        resp = self.client.get(
            reverse("aiassistant:ai_teams"),
            **{"HTTP_X_MEELAD_AI_TOKEN": SVC_TOKEN})
        self.assertEqual(resp.status_code, 403)

    @override_settings(MEELAD_AI_SERVICE_TOKEN=SVC_TOKEN)
    def test_reads_are_scoped_to_actor_madrasa(self):
        m1 = Madrasa.objects.create(name="M1")
        m2 = Madrasa.objects.create(name="M2")
        user = User.objects.create_user(
            email="a@t.com", phone_number="9000000001", madrasa=m1, password="x")
        Team.objects.create(name="Alpha", madrasa=m1)
        Team.objects.create(name="Foreign", madrasa=m2)
        resp = self.client.get(
            reverse("aiassistant:ai_teams"),
            **{"HTTP_X_MEELAD_AI_TOKEN": SVC_TOKEN,
               "HTTP_X_MEELAD_USER_ID": str(user.id)})
        self.assertEqual(resp.status_code, 200)
        names = [t["name"] for t in resp.json()["teams"]]
        self.assertIn("Alpha", names)
        self.assertNotIn("Foreign", names)


@override_settings(MEELAD_AI_SERVICE_TOKEN=SVC_TOKEN)
class ScheduleWriteTests(TestCase):
    def setUp(self):
        from datetime import date as _date
        self.madrasa = Madrasa.objects.create(name="M")
        self.other = Madrasa.objects.create(name="Other")
        self.user = User.objects.create_user(
            email="a@test.com", phone_number="9000000001",
            madrasa=self.madrasa, password="x")
        self.venue = Venue.objects.create(name="Hall A", madrasa=self.madrasa)
        self.category = Category.objects.create(name="Speech", madrasa=self.madrasa)
        self.program = Program.objects.create(
            title="Q1", madrasa=self.madrasa)
        self.category.programs.add(self.program)
        from applications.schedule.models import FestDay
        self.day = FestDay.objects.create(
            madrasa=self.madrasa, name="Day 1", date=_date(2025, 6, 1))

    def headers(self):
        return {"HTTP_X_MEELAD_AI_TOKEN": SVC_TOKEN,
                "HTTP_X_MEELAD_USER_ID": str(self.user.id)}

    def payload(self, **kw):
        p = {"program_id": self.program.id, "venue_id": self.venue.id,
             "fest_day": self.day.id, "start_time": "09:00",
             "duration_minutes": 60, "idempotency_key": "k1"}
        p.update(kw)
        return p

    def test_schedule_success_and_audit(self):
        resp = self.client.post(
            reverse("aiassistant:ai_op_schedule"), data=self.payload(),
            content_type="application/json", **self.headers())
        self.assertEqual(resp.status_code, 200)
        self.program.refresh_from_db()
        self.assertEqual(self.program.venue_id, self.venue.id)
        self.assertTrue(AIOperationAuditLog.objects.filter(
            action="schedule", success=True).exists())

    def test_write_requires_actor(self):
        resp = self.client.post(
            reverse("aiassistant:ai_op_schedule"), data=self.payload(),
            content_type="application/json",
            **{"HTTP_X_MEELAD_AI_TOKEN": SVC_TOKEN})
        self.assertEqual(resp.status_code, 403)
        self.program.refresh_from_db()
        self.assertIsNone(self.program.scheduled_time)

    def test_schedule_conflict_warns_but_saves(self):
        from datetime import time as _time
        from applications.schedule.models import ScheduleEntry
        other = Program.objects.create(title="Other", madrasa=self.madrasa)
        ScheduleEntry.objects.create(
            program=other, fest_day=self.day, start_time=_time(9, 0),
            duration_minutes=60, venue=self.venue)
        resp = self.client.post(
            reverse("aiassistant:ai_op_schedule"), data=self.payload(),
            content_type="application/json", **self.headers())
        # Like add_schedule: entry is saved, conflicts come back as warnings.
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json().get("warnings"))
        self.program.refresh_from_db()
        self.assertIsNotNone(self.program.scheduled_time)

    def test_schedule_idempotent(self):
        url = reverse("aiassistant:ai_op_schedule")
        r1 = self.client.post(url, data=self.payload(),
                              content_type="application/json", **self.headers())
        r2 = self.client.post(url, data=self.payload(),
                              content_type="application/json", **self.headers())
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        self.assertTrue(r2.json().get("idempotent"))

    def test_cannot_schedule_foreign_program(self):
        foreign = Program.objects.create(title="Foreign", madrasa=self.other)
        resp = self.client.post(
            reverse("aiassistant:ai_op_schedule"), data=self.payload(
                program_id=foreign.id),
            content_type="application/json", **self.headers())
        self.assertEqual(resp.status_code, 404)
        
@override_settings(MEELAD_AI_SERVICE_TOKEN=SVC_TOKEN)
class GroupWriteTests(TestCase):
    def setUp(self):
        self.madrasa = Madrasa.objects.create(name="M")
        self.user = User.objects.create_user(
            email="u@test.com", phone_number="9000000002",
            madrasa=self.madrasa, password="x")
        self.team = Team.objects.create(name="Red", madrasa=self.madrasa)
        self.program = Program.objects.create(
            title="Group Q", madrasa=self.madrasa, is_group=True)
        self.s1 = Student.objects.create(full_name="A", team=self.team)
        self.s2 = Student.objects.create(full_name="B", team=self.team)
        self.s3 = Student.objects.create(full_name="C", team=self.team)
        self.program.participants.add(self.s1, self.s2, self.s3)

    def headers(self):
        return {"HTTP_X_MEELAD_AI_TOKEN": SVC_TOKEN,
                "HTTP_X_MEELAD_USER_ID": str(self.user.id)}

    def payload(self, **kw):
        p = {"program_id": self.program.id,
             "participant_ids": [self.s1.id, self.s2.id],
             "idempotency_key": "g1"}
        p.update(kw)
        return p

    def test_group_requires_at_least_two(self):
        resp = self.client.post(
            reverse("aiassistant:ai_op_create_group"),
            data=self.payload(participant_ids=[self.s1.id]),
            content_type="application/json", **self.headers())
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Prize.objects.filter(program=self.program).exists())

    def test_create_group_success(self):
        resp = self.client.post(
            reverse("aiassistant:ai_op_create_group"), data=self.payload(),
            content_type="application/json", **self.headers())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Prize.objects.filter(program=self.program).count(), 1)
        group = Prize.objects.get(program=self.program)
        self.assertEqual(group.participants.count(), 2)
        self.assertEqual(group.team_id, self.team.id)

    def test_group_members_share_one_team(self):
        other_team = Team.objects.create(name="Blue", madrasa=self.madrasa)
        s5 = Student.objects.create(full_name="E", team=other_team)
        self.program.participants.add(s5)
        resp = self.client.post(
            reverse("aiassistant:ai_op_create_group"),
            data=self.payload(participant_ids=[self.s1.id, s5.id]),
            content_type="application/json", **self.headers())
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(Prize.objects.filter(program=self.program).exists())

    def test_duplicate_members_rejected(self):
        s6 = Student.objects.create(full_name="D", team=self.team)
        self.program.participants.add(s6)
        self.client.post(
            reverse("aiassistant:ai_op_create_group"),
            data=self.payload(idempotency_key="g_first"),
            content_type="application/json", **self.headers())
        resp = self.client.post(
            reverse("aiassistant:ai_op_create_group"),
            data=self.payload(participant_ids=[self.s1.id, s6.id],
                              idempotency_key="g_dup"),
            content_type="application/json", **self.headers())
        self.assertEqual(resp.status_code, 400)


class ChatHistoryTests(TestCase):
    """History dropdown: per-user, latest-20, detail, save-on-proxy."""

    def setUp(self):
        self.madrasa = Madrasa.objects.create(name="Hist M")
        self.user = User.objects.create_user(
            email="hist@t.com", phone_number="9000000098",
            madrasa=self.madrasa, password="x")
        # NOTE: accounts_user.madrasa_id is UNIQUE (one user per madrasa),
        # so the "other" user needs its own madrasa.
        self.other_madrasa = Madrasa.objects.create(name="Hist Other M")
        self.other = User.objects.create_user(
            email="other@t.com", phone_number="9000000097",
            madrasa=self.other_madrasa, password="x")

    def _session(self, user, conv, title):
        from .models import AIChatSession, AIChatMessage
        s = AIChatSession.objects.create(
            user=user, conversation_id=conv, title=title)
        AIChatMessage.objects.create(
            session=s, role="user", content="hello")
        AIChatMessage.objects.create(
            session=s, role="assistant", content="hi there")
        return s

    def test_requires_authentication(self):
        resp = self.client.get(reverse("aiassistant:chat_history"))
        self.assertEqual(resp.status_code, 401)

    def test_lists_only_own_sessions_latest_20(self):
        from .models import AIChatSession
        for i in range(22):
            AIChatSession.objects.create(
                user=self.user, conversation_id=f"c{i}", title=f"T{i}")
        self._session(self.other, "ox", "Other chat")
        self.client.force_login(self.user)
        resp = self.client.get(reverse("aiassistant:chat_history"))
        self.assertEqual(resp.status_code, 200)
        sessions = resp.json()["sessions"]
        self.assertEqual(len(sessions), 20)
        self.assertTrue(all(s["conversation_id"] != "ox" for s in sessions))

    def test_detail_returns_messages_and_forbids_others(self):
        self._session(self.user, "c1", "Who is leading?")
        self._session(self.other, "ox", "Other chat")
        self.client.force_login(self.user)
        resp = self.client.get(
            reverse("aiassistant:chat_history_detail", args=["c1"]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()["messages"]), 2)
        resp = self.client.get(
            reverse("aiassistant:chat_history_detail", args=["ox"]))
        self.assertEqual(resp.status_code, 404)

    @override_settings(MEELAD_AI_SERVICE_TOKEN="svc",
                       MEELAD_AI_SERVICE_BASE_URL="http://ai.test")
    def test_proxy_saves_turn_for_history(self):
        from .models import AIChatSession
        ai = mock.Mock(status_code=200,
                       json=lambda: {"answer": "You have 4 teams.",
                                     "conversation_id": "c9"})
        with mock.patch("requests.post", return_value=ai):
            self.client.force_login(self.user)
            resp = self.client.post(
                reverse("aiassistant:chat"),
                data=json.dumps({"message": "Who is leading?"}),
                content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(AIChatSession.objects.filter(
            user=self.user, conversation_id="c9",
            title__icontains="leading").exists())


class ChatProxyTests(TestCase):
    """The browser-facing chat proxy must ALWAYS answer with JSON.

    If the AI service outlives the chat deadline, gunicorn's arbiter aborts
    the worker mid-request and the browser gets an HTML 500 the widget cannot
    parse ("Unexpected response from the server (500)"). These tests pin the
    hard-deadline behaviour: a slow AI service must produce Django's own JSON
    504 (which the widget then auto-retries) instead of a worker abort.
    """

    def setUp(self):
        self.madrasa = Madrasa.objects.create(name="Chat M")
        self.user = User.objects.create_user(
            email="chat@t.com", phone_number="9000000099", madrasa=self.madrasa,
            password="x")

    def _post(self, message="list teams"):
        self.client.force_login(self.user)
        return self.client.post(
            reverse("aiassistant:chat"),
            data=json.dumps({"message": message}),
            content_type="application/json")

    def test_requires_authentication(self):
        resp = self.client.post(
            reverse("aiassistant:chat"),
            data=json.dumps({"message": "list teams"}),
            content_type="application/json")
        self.assertEqual(resp.status_code, 401)
        self.assertIn("error", resp.json())

    @override_settings(MEELAD_AI_SERVICE_TOKEN="svc",
                       MEELAD_AI_SERVICE_BASE_URL="http://ai.test",
                       MEELAD_AI_CHAT_TIMEOUT=1)
    def test_slow_ai_service_returns_json_504_before_deadline(self):
        """An AI response arriving after the deadline must never crash the
        request: Django answers its own JSON 504 within the deadline."""
        started = time.monotonic()

        def slow_post(*args, **kwargs):
            time.sleep(2)  # deadline is 1s
            return mock.Mock(status_code=200, text="", json=lambda: {})

        with mock.patch("requests.post", side_effect=slow_post):
            resp = self._post()
        elapsed = time.monotonic() - started

        self.assertEqual(resp.status_code, 504)
        self.assertIn("timed out", resp.json()["error"])
        # Prove the hard deadline (not the mocked 2s sleep) bounded the call.
        self.assertLess(elapsed, 2)

    @override_settings(MEELAD_AI_SERVICE_TOKEN="svc",
                       MEELAD_AI_SERVICE_BASE_URL="http://ai.test")
    def test_relays_ai_json_answer(self):
        ai = mock.Mock(status_code=200,
                       json=lambda: {"answer": "You have 4 teams.",
                                     "conversation_id": "c1"})
        with mock.patch("requests.post", return_value=ai):
            resp = self._post()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["answer"], "You have 4 teams.")

    @override_settings(MEELAD_AI_SERVICE_TOKEN="svc",
                       MEELAD_AI_SERVICE_BASE_URL="http://ai.test")
    def test_ai_5xx_becomes_json_502(self):
        ai = mock.Mock(status_code=500, text="boom")
        with mock.patch("requests.post", return_value=ai):
            resp = self._post()
        self.assertEqual(resp.status_code, 502)
        self.assertEqual(resp.json()["error"], "AI service encountered an error.")

    @override_settings(MEELAD_AI_SERVICE_TOKEN="svc",
                       MEELAD_AI_SERVICE_BASE_URL="http://ai.test")
    def test_ai_non_json_body_becomes_json_502(self):
        ai = mock.Mock(status_code=200, json=mock.Mock(side_effect=ValueError))
        with mock.patch("requests.post", return_value=ai):
            resp = self._post()
        self.assertEqual(resp.status_code, 502)
        self.assertIn("invalid response", resp.json()["error"])

    @override_settings(MEELAD_AI_SERVICE_TOKEN="svc",
                       MEELAD_AI_SERVICE_BASE_URL="http://ai.test")
    def test_connection_error_becomes_json_503(self):
        with mock.patch("requests.post",
                        side_effect=requests.exceptions.ConnectionError("x")):
            resp = self._post()
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["error"], "AI service is unavailable.")

    @override_settings(MEELAD_AI_SERVICE_TOKEN="svc")
    def test_missing_base_url_returns_json_503(self):
        resp = self._post()
        self.assertEqual(resp.status_code, 503)