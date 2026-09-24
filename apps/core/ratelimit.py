"""Tiny fixed-window rate limiter on the Django cache (use Redis in production)."""
from django.conf import settings
from django.core.cache import cache


def allow(bucket, identity):
    limit, window = settings.WIKISCHOLAR["RATE_LIMITS"][bucket]
    key = f"rl:{bucket}:{identity}"
    cache.add(key, 0, window)
    try:
        count = cache.incr(key)
    except ValueError:  # key expired between add and incr
        cache.set(key, 1, window)
        count = 1
    return count <= limit
