import uuid
from django.conf import settings
from django.db import models


class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    title = models.CharField(max_length=180)
    messages = models.JSONField(default=list)
    revision = models.PositiveIntegerField(default=1)
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ['-updated_at', '-id']


class PurgedConversation(models.Model):
    """Content-free tombstone prevents legacy browser imports from resurrecting chats."""
    id = models.UUIDField(primary_key=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    purged_at = models.DateTimeField(auto_now_add=True)


class RequestQuota(models.Model):
    key = models.CharField(max_length=64, primary_key=True)
    expires_at = models.BigIntegerField(db_index=True)
    count = models.PositiveIntegerField()


class QueryJob(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    conversation = models.ForeignKey(Conversation, null=True, blank=True, on_delete=models.CASCADE)
    session_hash = models.CharField(max_length=64)
    kind = models.CharField(max_length=20)
    question = models.TextField(blank=True)
    status = models.CharField(max_length=20, default='queued', db_index=True)
    title = models.CharField(max_length=180, default='Consulta')
    answer = models.TextField(blank=True)
    sql = models.TextField(blank=True)
    columns = models.JSONField(default=list)
    source_tables = models.JSONField(default=list)
    filters = models.JSONField(default=dict)
    chart = models.JSONField(default=dict)
    panels = models.JSONField(default=list)
    analysis = models.JSONField(default=dict)
    context_state = models.JSONField(default=dict)
    response_type = models.CharField(max_length=20, default='answer')
    row_count = models.PositiveBigIntegerField(default=0)
    error = models.JSONField(default=dict)
    demo = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']


class AIUsage(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    job_id = models.UUIDField(null=True, db_index=True)
    provider = models.CharField(max_length=30)
    model = models.CharField(max_length=200)
    stage = models.CharField(max_length=20)
    prompt_tokens = models.PositiveBigIntegerField(null=True)
    completion_tokens = models.PositiveBigIntegerField(null=True)
    total_tokens = models.PositiveBigIntegerField(null=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class SystemAudit(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=60)
    detail = models.CharField(max_length=500, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']


class AssistantSkill(models.Model):
    preset_key = models.CharField(max_length=40, unique=True, null=True, blank=True, editable=False)
    name = models.CharField(max_length=100, unique=True)
    instructions = models.TextField(max_length=4000)
    stage = models.CharField(max_length=20, choices=[('planner', 'Planificador'), ('analyst', 'Analista'), ('both', 'Ambos agentes')])
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']


class AIProvider(models.Model):
    name = models.CharField(max_length=30, unique=True)
    endpoint = models.URLField(max_length=500)
    protocol = models.CharField(max_length=20, default='openai', choices=[
        ('openai', 'Compatible con OpenAI'), ('openrouter', 'OpenRouter · modelos gratuitos')])
    enabled = models.BooleanField(default=True)
    legacy_code = models.CharField(max_length=20, unique=True, null=True, blank=True)

    class Meta:
        ordering = ['name']


class ProviderModel(models.Model):
    provider = models.ForeignKey(AIProvider, on_delete=models.CASCADE, related_name='models')
    name = models.CharField(max_length=80)
    identifier = models.CharField(max_length=200)
    enabled = models.BooleanField(default=True)
    fallback_enabled = models.BooleanField(default=False)
    priority = models.PositiveIntegerField(default=10)

    class Meta:
        ordering = ['name', 'pk']
        constraints = [models.UniqueConstraint(fields=['provider', 'identifier'], name='unique_provider_model')]


class ProviderKey(models.Model):
    provider = models.ForeignKey(AIProvider, on_delete=models.CASCADE, related_name='keys')
    name = models.CharField(max_length=80)
    secret = models.CharField(max_length=4096)
    priority = models.PositiveIntegerField(default=1)
    enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ['priority', 'pk']


class ProviderSelection(models.Model):
    active_model = models.ForeignKey(ProviderModel, null=True, blank=True, on_delete=models.PROTECT)
