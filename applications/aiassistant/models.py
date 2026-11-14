"""Models backing the AI assistant feature.

These do NOT hold any official fest transactional data. Django remains the
system of record; this app only records an audit trail of AI-initiated write
operations so that operators can see who asked the assistant to change what,
plus the user's own chat history so the widget can offer a history dropdown.
"""
from django.conf import settings
from django.db import models


class AIChatSession(models.Model):
    """One chat thread of a user with the AI assistant.

    ``conversation_id`` is generated client-side (uuid) and echoed by the
    FastAPI service; it stays stable for the whole thread so follow-ups keep
    context. ``title`` is derived from the first user message for the history
    dropdown.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ai_chat_sessions",
    )
    conversation_id = models.CharField(max_length=64, db_index=True)
    title = models.CharField(max_length=200, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated"]
        unique_together = (("user", "conversation_id"),)

    def __str__(self):
        return f"{self.title or self.conversation_id} ({self.user_id})"


class AIChatMessage(models.Model):
    """A single user/assistant turn inside an :class:`AIChatSession`."""

    ROLE_USER = "user"
    ROLE_ASSISTANT = "assistant"
    ROLE_CHOICES = ((ROLE_USER, "User"), (ROLE_ASSISTANT, "Assistant"))

    session = models.ForeignKey(
        AIChatSession,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    role = models.CharField(max_length=10, choices=ROLE_CHOICES)
    content = models.TextField()
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created"]

    def __str__(self):
        return f"{self.role} @ {self.created:%Y-%m-%d %H:%M}"


class AIOperationAuditLog(models.Model):
    """Audit trail for AI-initiated write operations.

    Every write operation executed through the AI assistant (schedule updates,
    group creation, result updates, ...) is recorded here with the acting user,
    the exact requested action, the confirmation that preceded it, and the
    outcome. Sensitive prompts are not stored.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_operation_logs",
    )
    action = models.CharField(max_length=50)  # e.g. create_schedule / create_group
    target_type = models.CharField(max_length=50, blank=True)  # e.g. program / venue
    target_id = models.IntegerField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    idempotency_key = models.CharField(max_length=128, blank=True, db_index=True)
    approved = models.BooleanField(default=False)
    success = models.BooleanField(default=False)
    message = models.CharField(max_length=500, blank=True)
    source = models.CharField(max_length=20, default="ai")  # ai|ui|api
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created"]

    def __str__(self):
        return f"{self.action} @ {self.created:%Y-%m-%d %H:%M} success={self.success}"