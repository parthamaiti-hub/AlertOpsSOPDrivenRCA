import random
from datetime import UTC, datetime, timedelta


def graphql_query(endpoint: str, query: str, variables: dict = None) -> dict:
    """Stub GraphQL query client. Executes a GraphQL query against an API endpoint."""
    if variables is None:
        variables = {}

    now = datetime.now(UTC)

    # Simulate response based on query content
    query_lower = query.lower()

    if "deployment" in query_lower or "pod" in query_lower:
        data = {
            "deployments": [
                {
                    "name": f"app-{random.choice(['api', 'worker', 'scheduler'])}-{random.randint(1, 5)}",
                    "namespace": "production",
                    "replicas": random.randint(1, 10),
                    "readyReplicas": random.randint(0, 5),
                    "restartCount": random.randint(0, 12),
                    "lastRestartedAt": (now - timedelta(minutes=random.randint(5, 120))).isoformat() + "Z",
                    "status": random.choice(["Running", "CrashLoopBackOff", "Pending"]),
                }
                for _ in range(random.randint(2, 5))
            ]
        }
    elif "incident" in query_lower or "alert" in query_lower:
        data = {
            "incidents": [
                {
                    "id": f"INC-{random.randint(1000, 9999)}",
                    "title": random.choice([
                        "API latency spike", "Database connection exhausted", "Memory pressure detected"
                    ]),
                    "severity": random.choice(["critical", "high", "medium"]),
                    "status": random.choice(["open", "investigating", "resolved"]),
                    "createdAt": (now - timedelta(hours=random.randint(1, 24))).isoformat() + "Z",
                }
                for _ in range(random.randint(1, 4))
            ]
        }
    elif "metric" in query_lower or "service" in query_lower:
        data = {
            "serviceMetrics": {
                "errorRate": round(random.uniform(0.1, 8.5), 2),
                "p99Latency": round(random.uniform(200, 2500), 1),
                "throughput": random.randint(100, 5000),
                "availabilityPercent": round(random.uniform(95.0, 99.99), 2),
                "sampledAt": now.isoformat() + "Z",
            }
        }
    else:
        data = {
            "result": {
                "status": "ok",
                "query": query[:80],
                "rowCount": random.randint(0, 50),
                "executedAt": now.isoformat() + "Z",
            }
        }

    return {
        "endpoint": endpoint,
        "query": query,
        "variables": variables,
        "data": data,
        "errors": None,
        "latency_ms": random.randint(20, 400),
        "timestamp": now.isoformat() + "Z",
    }


execute = graphql_query
