"""Service Layer unit tests — RBAC, audit, rate limits (PRD §3 Layer 5, §8.4)."""

from backend.config_loader import config
from backend.envelope import Envelope
from backend.layers.service import ServiceLayer
from backend.layers.service.rate_limiter import RateLimiter

VALID = {"entity": "sales", "metric": "total_sales", "filters": {"period": "this_week"}}


def _service(audit_logger, rate_limiter=None):
    rl = rate_limiter or RateLimiter(max_requests=1000, window_seconds=60)
    return ServiceLayer(config, audit=audit_logger, rate_limiter=rl)


def test_admin_is_approved_and_audited(audit_logger):
    env = Envelope.create(user_id="admin-user", role="admin", payload=VALID)
    out = _service(audit_logger).process(env)
    assert out.ok
    entries = audit_logger.entries()
    assert len(entries) == 1
    assert entries[0]["decision"] == "approved"
    assert entries[0]["request_id"] == env.request_id


def test_non_admin_role_is_denied_and_logged(audit_logger):
    # §8.4 — a non-admin role is rejected with RBAC_DENIED and appears in the log.
    env = Envelope.create(user_id="guest-user", role="guest", payload=VALID)
    out = _service(audit_logger).process(env)
    assert not out.ok
    assert out.error.code == "RBAC_DENIED"
    entry = audit_logger.entries()[0]
    assert entry["decision"] == "rejected"
    assert "RBAC_DENIED" in entry["reason"]
    assert entry["request_id"] == env.request_id


def test_rate_limit_is_enforced_per_user(audit_logger):
    service = _service(audit_logger, RateLimiter(max_requests=2, window_seconds=60))
    results = []
    for _ in range(3):
        env = Envelope.create(user_id="admin-user", role="admin", payload=VALID)
        results.append(service.process(env))
    assert results[0].ok and results[1].ok
    assert not results[2].ok
    assert results[2].error.code == "RATE_LIMIT_EXCEEDED"
