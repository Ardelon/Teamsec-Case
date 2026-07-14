import redis
from django.conf import settings

RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


def get_redis_client() -> redis.Redis:
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


def lock_key(tenant_id: str, loan_type: str) -> str:
    return f"lock:{tenant_id}:{loan_type}"


def acquire_sync_lock(client: redis.Redis, tenant_id: str, loan_type: str, job_id: str) -> bool:
    # Long ETL runs need a lock that survives multi-hour jobs.
    return bool(client.set(lock_key(tenant_id, loan_type), job_id, nx=True, ex=14400))


def get_active_job_id(client: redis.Redis, tenant_id: str, loan_type: str) -> str | None:
    return client.get(lock_key(tenant_id, loan_type))


def release_sync_lock(client: redis.Redis, tenant_id: str, loan_type: str, job_id: str) -> None:
    client.eval(RELEASE_LOCK_SCRIPT, 1, lock_key(tenant_id, loan_type), job_id)
