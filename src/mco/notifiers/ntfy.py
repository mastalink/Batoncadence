"""Private, payload-minimized operator notifications.

ntfy topics are bearer-like capabilities: anyone who can guess the public
``ntfy.sh/<topic>`` URL can subscribe. This module therefore has one
destination authority, rejects weak topics, and never derives a topic from a
role, job, or caller argument. Public helpers also build the payload here so
job titles, errors, hostnames, and other board data cannot reach the relay.
"""

from __future__ import annotations

import re
import time
from collections import deque
from typing import List, Optional

import requests
from loguru import logger

from mco.config import get_config
from mco.secret_vault import SecretNotFoundError, SecretRef, VaultError, build_secret_vault


REPEAT_AFTER_SECONDS = 600
MAX_PUSHES_PER_HOUR = 10
# Compatibility name for callers/tests from the older routine-only budget.
MAX_ROUTINE_PER_HOUR = MAX_PUSHES_PER_HOUR
URGENT_PRIORITY = 4
MIN_PRIVATE_TOPIC_LENGTH = 32
_SAFE_TITLES = {
    "decision": "BitCadence: decision needed",
    "alert": "BitCadence: alert",
    "done": "BitCadence: done",
    "test": "BitCadence: test",
}
_WEAK_TOPIC_PREFIXES = ("mco-", "codex", "claude", "grok", "gemini", "bitcadence")
_GENERIC_PROJECTS = {"operations", "bitcadence", "simlab", "via", "moses", "mymeals"}
_last_sent: dict[tuple[str, str], float] = {}
_push_sends: deque[float] = deque()
_routine_sends = _push_sends
_batched: deque[tuple[str, str, int]] = deque(maxlen=1000)
_last_rate_limit_log = [0.0]


def _topic_ref(org_id: str = "default") -> SecretRef:
    # Stable vault identity: default/ntfy/topic. The legacy key keeps existing
    # local installs on NTFY_TOPIC while ConfigManager stores it encrypted.
    return SecretRef(org_id=org_id, scope="ntfy", name="topic", legacy_config_key="NTFY_TOPIC")


def _vault_topic(config, db=None, org_id: str = "default") -> str:
    try:
        return str(build_secret_vault(config, db).get(_topic_ref(org_id))).strip()
    except (SecretNotFoundError, VaultError, ValueError):
        return ""


def _aws_vault_topic(config) -> str:
    """Read the optional AWS vault key without ever logging its value."""
    secret_id = str(config.get("NTFY_TOPIC_SECRET_ID") or "").strip()
    if not secret_id:
        return ""
    try:
        import boto3
        profile = str(config.get("NTFY_AWS_PROFILE") or "").strip() or None
        session = boto3.Session(profile_name=profile)
        value = session.client("secretsmanager").get_secret_value(SecretId=secret_id)
        return str(value.get("SecretString") or "").strip()
    except Exception as exc:
        logger.warning("ntfy vault topic unavailable ({})", type(exc).__name__)
        return ""


def topic_is_private(topic: str) -> bool:
    """Conservatively accept only long, URL-safe, non-derived topics."""
    value = str(topic or "").strip()
    lowered = value.lower()
    return (
        len(value) >= MIN_PRIVATE_TOPIC_LENGTH
        and re.fullmatch(r"[A-Za-z0-9_-]+", value) is not None
        and not lowered.startswith(_WEAK_TOPIC_PREFIXES)
        and len(set(value)) >= 12
    )


def get_ntfy_config(*, db=None, org_id: str = "default") -> dict:
    """Resolve the one configured topic; a missing/weak topic disables sends."""
    config = get_config()
    # ConfigManager already overlays the encrypted local store. The explicit
    # vault read adds the shared-vault path without a caller-supplied target.
    topic = str(config.get("NTFY_TOPIC") or "").strip()
    if not topic and str(config.get("MCO_SECRET_VAULT_BACKEND") or "local").lower() == "database":
        if db is None:
            try:
                from mco.orchestrator.routes import get_db_client
                db = get_db_client()
            except Exception:
                db = None
        topic = _vault_topic(config, db, org_id)
    if topic and not topic_is_private(topic):
        logger.warning("ntfy disabled: configured topic is not a random private topic of at least 32 characters")
        topic = ""
    if not topic:
        vault_topic = _aws_vault_topic(config)
        if topic_is_private(vault_topic):
            topic = vault_topic
        elif vault_topic:
            logger.warning("ntfy disabled: vault topic is not a random private topic of at least 32 characters")
    return {
        "server": str(config.get("NTFY_SERVER") or "https://ntfy.sh").rstrip("/"),
        "topic": topic,
        "token": config.get("NTFY_TOKEN"),
        "sns_topic": config.get("SNS_TOPIC") or config.get("MCO_SNS_TOPIC"),
        "aws_profile": config.get("NTFY_AWS_PROFILE"),
        "max_per_hour": config.get("NTFY_MAX_PER_HOUR", MAX_PUSHES_PER_HOUR),
        "repeat_after": config.get("NTFY_REPEAT_AFTER", REPEAT_AFTER_SECONDS),
    }


def _throttle_config(cfg: dict) -> tuple[int, int, int]:
    def _int(value, default):
        try:
            return max(0, int(value if value is not None else default))
        except (TypeError, ValueError):
            return default
    return (
        _int(cfg.get("repeat_after", cfg.get("NTFY_REPEAT_AFTER")), REPEAT_AFTER_SECONDS),
        min(MAX_PUSHES_PER_HOUR, _int(cfg.get("max_per_hour", cfg.get("NTFY_MAX_PER_HOUR")), MAX_PUSHES_PER_HOUR)),
        URGENT_PRIORITY,
    )


def _allowed(message: str, title: Optional[str], priority: int, cfg: dict, now: float) -> bool:
    """Enforce a hard ten-per-hour cap for every priority."""
    repeat_after, max_per_hour, _ = _throttle_config(cfg)
    key = (title or "", message)
    last = _last_sent.get(key)
    if last is not None and repeat_after and now - last < repeat_after:
        logger.debug("ntfy suppressed a repeated operator notification")
        return False
    while _push_sends and now - _push_sends[0] >= 3600:
        _push_sends.popleft()
    if max_per_hour == 0 or len(_push_sends) >= max_per_hour:
        return False
    _push_sends.append(now)
    _last_sent[key] = now
    if len(_last_sent) > 512:
        for old in sorted(_last_sent, key=_last_sent.get)[:256]:
            _last_sent.pop(old, None)
    return True


def _short_id(job_id: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9]", "", str(job_id or ""))
    return clean[:8].lower() or "unknown"


def _generic_project(project: str) -> str:
    value = re.sub(r"[^a-z0-9]", "", str(project or "").lower())
    return value if value in _GENERIC_PROJECTS else "operations"


def _body(kind: str, job_id: str, project: str = "operations", count: int = 0) -> str:
    short = _short_id(job_id)
    project = _generic_project(project)
    if kind == "decision":
        return f"Decision waiting on {project} (job {short})"
    if kind == "done":
        return f"Work finished on {project} (job {short})"
    if kind == "digest":
        return f"{max(1, int(count))} things need you today (job {short})"
    return f"Attention needed on {project} (job {short})"


def _send_sns_backup(cfg: dict, title: str, message: str) -> bool:
    """Best-effort email backup through the already-subscribed SNS topic."""
    topic_arn = str(cfg.get("sns_topic") or "").strip()
    if not topic_arn:
        logger.warning("SNS backup skipped: SNS_TOPIC is not configured")
        return False
    try:
        import boto3
        region = topic_arn.split(":", 4)[3] if topic_arn.startswith("arn:aws:sns:") else None
        session = boto3.Session(profile_name=str(cfg.get("aws_profile") or "").strip() or None)
        session.client("sns", region_name=region or None).publish(
            TopicArn=topic_arn, Subject=title[:100], Message=message,
        )
        return True
    except Exception as exc:  # never include an ARN or payload in logs
        logger.warning("SNS backup delivery failed ({})", type(exc).__name__)
        return False


def _post(cfg: dict, message: str, title: str, priority: int) -> bool:
    if not cfg.get("topic"):
        logger.warning("ntfy send skipped: no valid private topic is configured")
        return False
    try:
        headers = {"Title": title, "Priority": str(priority)}
        if cfg.get("token"):
            headers["Authorization"] = f"Bearer {cfg['token']}"
        response = requests.post(
            f"{cfg['server']}/{cfg['topic']}",
            data=message.encode("utf-8"), headers=headers, timeout=10,
        )
        response.raise_for_status()
        logger.debug("ntfy operator notification accepted")
        return True
    except Exception as exc:  # request exceptions may contain the secret URL
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status == 429 and time.time() - _last_rate_limit_log[0] > 600:
            _last_rate_limit_log[0] = time.time()
            logger.warning("ntfy relay rate-limited operator notifications")
        elif status:
            logger.warning("ntfy delivery failed with HTTP status {}", status)
        else:
            logger.warning("ntfy delivery failed ({})", type(exc).__name__)
        return False


def _deliver(message: str, title: str, priority: int, *, cfg: Optional[dict] = None) -> bool:
    cfg = cfg or get_ntfy_config()
    # Email remains a backup for every push attempt, including a rate-limited
    # ntfy send. This prevents the phone relay from becoming the only path.
    _send_sns_backup(cfg, title, message)
    if not _allowed(message, title, priority, cfg, time.time()):
        _batched.append((title, message, priority))
        logger.warning("ntfy hourly cap reached; operator notification batched")
        return False
    return _post(cfg, message, title, priority)


def notify_event(kind: str, job_id: str, *, project: str = "operations", count: int = 0) -> bool:
    """Send one minimized event. Callers provide no relay-visible prose."""
    normalized = "alert" if kind == "digest" else kind
    if normalized not in _SAFE_TITLES or normalized == "test":
        raise ValueError("unsupported operator notification kind")
    title = _SAFE_TITLES[normalized]
    priority = 4 if normalized in {"decision", "alert"} else 3
    return _deliver(_body(kind, job_id, project, count), title, priority)


def flush_batched() -> bool:
    """Collapse overflow into one neutral push when the hourly window opens."""
    if not _batched:
        return False
    cfg = get_ntfy_config()
    now = time.time()
    summary = f"{len(_batched)} more items need attention (job batch)"
    title = _SAFE_TITLES["alert"]
    if not _allowed(summary, title, 4, cfg, now):
        return False
    _batched.clear()
    _send_sns_backup(cfg, title, summary)
    return _post(cfg, summary, title, 4)


def send_test_push() -> bool:
    return _deliver(
        "Your fleet can reach you. No action needed.",
        _SAFE_TITLES["test"], 3,
    )


def notify(message: str, title: Optional[str] = None, priority: int = 3,
           tags: Optional[List[str]] = None, topic: Optional[str] = None,
           server: Optional[str] = None, jev_provider=None) -> bool:
    """Compatibility entry point that intentionally discards caller prose.

    ``topic`` and ``server`` remain accepted only to avoid breaking extensions;
    neither can influence the destination. New code should use
    :func:`notify_event`.
    """
    del message, title, priority, tags, topic, server, jev_provider
    return notify_event("alert", "unknown")


def is_joseph_decision(title: str) -> bool:
    lowered = str(title or "").strip().lower()
    return lowered.startswith("joseph decision") or lowered.startswith("cio approval")


def notify_job_created(job_id: str, title: str, to_role: str):
    del to_role
    if is_joseph_decision(title):
        return notify_event("decision", job_id)
    return False


def notify_job_leased(job_id: str, agent_id: str, to_role: str):
    del job_id, agent_id, to_role
    return False


def notify_job_completed(job_id: str, status: str, to_role: str):
    del job_id, status, to_role
    return False


def notify_job_failed(job_id: str, error: str, to_role: str):
    del error, to_role
    return notify_event("alert", job_id)


def notify_job_needs_approval(job_id: str, title: str, to_role: str):
    del to_role
    if is_joseph_decision(title):
        return notify_event("decision", job_id)
    return False


def notify_job_escalated(job_id: str, title: str, escalate_to_role: str, error: str):
    del title, escalate_to_role, error
    return notify_event("alert", job_id)


def notify_sidecar_escalation(job_id: str, project: str = "operations"):
    return notify_event("decision", job_id, project=project)


def notify_operate_alert(job_id: str, project: str = "operations"):
    return notify_event("alert", job_id, project=project)


def notify_sns_alarm(alarm_id: str, project: str = "operations"):
    return notify_event("alert", alarm_id, project=project)


def notify_force_pull(role: str, reason: str = "Manual trigger"):
    del role, reason
    return notify_event("alert", "manual")


def notify_agent_online(role: str, instance_id: str):
    del role, instance_id
    return False


def notify_agent_offline(role: str, instance_id: str):
    del role, instance_id
    return False


def notify_gateway_startup(stats: dict):
    del stats
    return False
