import random


def health_check(url: str, timeout: int = 5) -> dict:
    """Stub health check. Returns mock endpoint status."""
    is_healthy = random.random() > 0.2
    status_code = 200 if is_healthy else random.choice([503, 504, 500])
    response_time = round(random.uniform(0.01, 0.5 if is_healthy else 5.0), 3)
    return {
        "url": url,
        "status_code": status_code,
        "response_time_seconds": response_time,
        "healthy": is_healthy,
        "body": {"status": "UP" if is_healthy else "DOWN", "uptime_seconds": random.randint(100, 864000)},
    }
