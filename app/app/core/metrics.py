"""요청 트래픽 메트릭 (D14). 프로세스 안에서 분 단위로 집계한다.

RequestIdMiddleware 가 요청 1건마다 record() 를 부르고, 운영자 대시보드(/admin/dashboard/traffic)가
snapshot() 으로 읽는다. CloudWatch(Fluent Bit → 메트릭 필터)가 환경 전체의 기준이고, 이 집계는
파드 1개 기준의 "지금 이 순간" 보조 지표다. 재시작하면 비워진다.

- 링 버퍼: 최근 24시간, 1분 1버킷. 오래된 버킷은 기록 시점에 버린다.
- is_test 트래픽(평가 러너)은 본 집계에서 빼고 건수만 따로 센다. /health·/ready 프로브도 마찬가지.
- 경로는 ID 세그먼트(UUID·숫자·긴 hex)를 {id} 로 바꿔 라우트 단위로 묶는다. 질의·토큰은 다루지 않는다.
- 지연은 히스토그램(상한 고정)으로 들고 p50/p95/p99 는 버킷 안에서 선형 보간한다.
"""
import os
import re
import socket
import threading
import time
from collections import Counter
from datetime import UTC, datetime

WINDOW_MINUTES = 24 * 60
LATENCY_BOUNDS_MS = (25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)  # 마지막 버킷은 10000 초과
PROBE_PATHS = frozenset({"/health", "/ready"})
MAX_ROUTES = 15

_ID_SEGMENT = re.compile(r"^(?:[0-9a-fA-F-]{20,}|\d+)$")


def normalize_route(path: str) -> str:
    """/resumes/3f2a.../versions/12 → /resumes/{id}/versions/{id}. 404 가 나는 임의 경로도 묶인다."""
    parts = path.split("/")
    return "/".join("{id}" if _ID_SEGMENT.match(p) else p for p in parts) or "/"


class _Hist:
    __slots__ = ("counts", "total", "sum_ms")

    def __init__(self) -> None:
        self.counts = [0] * (len(LATENCY_BOUNDS_MS) + 1)
        self.total = 0
        self.sum_ms = 0.0

    def add(self, ms: float) -> None:
        idx = len(LATENCY_BOUNDS_MS)
        for i, bound in enumerate(LATENCY_BOUNDS_MS):
            if ms <= bound:
                idx = i
                break
        self.counts[idx] += 1
        self.total += 1
        self.sum_ms += ms

    def merge(self, other: "_Hist") -> None:
        for i, c in enumerate(other.counts):
            self.counts[i] += c
        self.total += other.total
        self.sum_ms += other.sum_ms

    def percentile(self, q: float) -> float | None:
        if self.total == 0:
            return None
        target = q * self.total
        seen = 0
        lower = 0.0
        for i, c in enumerate(self.counts):
            upper = float(LATENCY_BOUNDS_MS[i]) if i < len(LATENCY_BOUNDS_MS) else LATENCY_BOUNDS_MS[-1] * 2.0
            if seen + c >= target:
                if c == 0:
                    return upper
                frac = (target - seen) / c
                return round(lower + (upper - lower) * frac, 1)
            seen += c
            lower = upper
        return float(LATENCY_BOUNDS_MS[-1])

    @property
    def avg(self) -> float | None:
        return round(self.sum_ms / self.total, 1) if self.total else None


class _RouteStat:
    __slots__ = ("requests", "errors_5xx", "client_4xx", "hist")

    def __init__(self) -> None:
        self.requests = 0
        self.errors_5xx = 0
        self.client_4xx = 0
        self.hist = _Hist()

    def merge(self, other: "_RouteStat") -> None:
        self.requests += other.requests
        self.errors_5xx += other.errors_5xx
        self.client_4xx += other.client_4xx
        self.hist.merge(other.hist)


class _Bucket:
    __slots__ = ("requests", "status", "hist", "by_role", "test_requests", "probe_requests", "routes")

    def __init__(self) -> None:
        self.requests = 0
        self.status = Counter()  # "2xx" | "3xx" | "4xx" | "5xx"
        self.hist = _Hist()
        self.by_role = Counter()  # role 없으면 "anonymous"
        self.test_requests = 0
        self.probe_requests = 0
        self.routes: dict[tuple[str, str], _RouteStat] = {}


class TrafficStats:
    def __init__(self, window_minutes: int = WINDOW_MINUTES, clock=time.time) -> None:
        self._window = window_minutes
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: dict[int, _Bucket] = {}  # epoch minute → bucket
        self.started_at = datetime.now(UTC)
        self.hostname = os.environ.get("HOSTNAME") or socket.gethostname()

    def record(
        self,
        method: str | None,
        path: str | None,
        status: int,
        duration_ms: float,
        *,
        role: str | None = None,
        is_test: bool | None = None,
    ) -> None:
        minute = int(self._clock() // 60)
        with self._lock:
            bucket = self._buckets.get(minute)
            if bucket is None:
                bucket = self._buckets[minute] = _Bucket()
                self._evict(minute)
            if is_test:
                bucket.test_requests += 1
                return
            if path in PROBE_PATHS:
                bucket.probe_requests += 1
                return
            bucket.requests += 1
            bucket.status[f"{status // 100}xx"] += 1
            bucket.hist.add(duration_ms)
            bucket.by_role[role or "anonymous"] += 1
            key = (method or "-", normalize_route(path or "/"))
            rs = bucket.routes.get(key)
            if rs is None:
                rs = bucket.routes[key] = _RouteStat()
            rs.requests += 1
            if status >= 500:
                rs.errors_5xx += 1
            elif status >= 400:
                rs.client_4xx += 1
            rs.hist.add(duration_ms)

    def _evict(self, now_minute: int) -> None:
        oldest = now_minute - self._window
        for m in [m for m in self._buckets if m <= oldest]:
            del self._buckets[m]

    def snapshot(self, minutes: int = 60, step: int | None = None) -> dict:
        """최근 `minutes` 분 집계. series 는 `step` 분 단위(기본: 60분→1, 6시간→5, 24시간→15)."""
        minutes = max(1, min(minutes, self._window))
        if step is None:
            step = 1 if minutes <= 60 else 5 if minutes <= 360 else 15
        now_minute = int(self._clock() // 60)
        first = now_minute - minutes + 1

        total = _Bucket()
        routes: dict[tuple[str, str], _RouteStat] = {}
        series: list[dict] = []
        with self._lock:
            for start in range(first, now_minute + 1, step):
                agg = _Bucket()
                for m in range(start, min(start + step, now_minute + 1)):
                    b = self._buckets.get(m)
                    if b is None:
                        continue
                    agg.requests += b.requests
                    agg.status.update(b.status)
                    agg.hist.merge(b.hist)
                    agg.by_role.update(b.by_role)
                    agg.test_requests += b.test_requests
                    agg.probe_requests += b.probe_requests
                    for key, rs in b.routes.items():
                        target = routes.get(key)
                        if target is None:
                            target = routes[key] = _RouteStat()
                        target.merge(rs)
                series.append(
                    {
                        "at": datetime.fromtimestamp(start * 60, UTC).isoformat(timespec="seconds"),
                        "requests": agg.requests,
                        "errors_5xx": agg.status["5xx"],
                        "client_4xx": agg.status["4xx"],
                        "test_requests": agg.test_requests,
                        "p95_ms": agg.hist.percentile(0.95),
                    }
                )
                total.requests += agg.requests
                total.status.update(agg.status)
                total.hist.merge(agg.hist)
                total.by_role.update(agg.by_role)
                total.test_requests += agg.test_requests
                total.probe_requests += agg.probe_requests

        top = sorted(routes.items(), key=lambda kv: (-kv[1].requests, kv[0]))[:MAX_ROUTES]
        errors = total.status["5xx"]
        return {
            "pod": {
                "hostname": self.hostname,
                "started_at": self.started_at.isoformat(timespec="seconds"),
                "uptime_s": int((datetime.now(UTC) - self.started_at).total_seconds()),
            },
            "window_minutes": minutes,
            "step_minutes": step,
            "totals": {
                "requests": total.requests,
                "errors_5xx": errors,
                "client_4xx": total.status["4xx"],
                "test_requests": total.test_requests,
                "probe_requests": total.probe_requests,
                "rpm": round(total.requests / minutes, 2),
                "error_rate": round(errors / total.requests, 4) if total.requests else 0.0,
                "latency_ms": {
                    "avg": total.hist.avg,
                    "p50": total.hist.percentile(0.5),
                    "p95": total.hist.percentile(0.95),
                    "p99": total.hist.percentile(0.99),
                },
            },
            "status": {k: total.status.get(k, 0) for k in ("2xx", "3xx", "4xx", "5xx")},
            "by_role": dict(sorted(total.by_role.items(), key=lambda kv: -kv[1])),
            "latency_hist": [
                {"le_ms": LATENCY_BOUNDS_MS[i] if i < len(LATENCY_BOUNDS_MS) else None, "count": c}
                for i, c in enumerate(total.hist.counts)
            ],
            "routes": [
                {
                    "method": method,
                    "route": route,
                    "requests": rs.requests,
                    "errors_5xx": rs.errors_5xx,
                    "client_4xx": rs.client_4xx,
                    "avg_ms": rs.hist.avg,
                    "p95_ms": rs.hist.percentile(0.95),
                }
                for (method, route), rs in top
            ],
            "series": series,
        }


# 프로세스 전역 1개. 테스트는 TrafficStats 를 따로 만들어 쓴다.
traffic = TrafficStats()
