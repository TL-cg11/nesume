"""GitHub 공개 저장소 정보 수집 (tasks B14, spec 3.4, part2_guide 4.9·4.60).

- 공개 저장소만. 토큰을 받지 않는다(비인증 API, IP당 시간당 60회)
- 요청은 api.github.com 으로만 보낸다(입력 URL에서 소유자·저장소 이름만 뽑는다 → 다른 주소 접근 불가)
- 같은 저장소는 10분 동안 결과를 재사용해 호출을 아낀다(앱 서버마다 메모리)
- HTTP는 표준 라이브러리(urllib). 새 의존성 없음
"""
from __future__ import annotations

import base64
import json
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field

API = "https://api.github.com"
TIMEOUT = 10
CACHE_TTL = 600
_URL = re.compile(r"^https://github\.com/([A-Za-z0-9-]{1,39})/([A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$")
_LAST_PAGE = re.compile(r'[?&]page=(\d+)[^>]*>;\s*rel="last"')


class InvalidRepoUrl(ValueError):
    pass


class RepoNotFound(LookupError):
    """없거나 비공개 저장소(비인증 API는 둘을 구분하지 못한다)."""


class RateLimited(RuntimeError):
    pass


class GithubUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class RepoStats:
    full_name: str
    html_url: str
    description: str
    languages: dict[str, int] = field(default_factory=dict)  # 언어 → 바이트
    readme: str = ""
    commits: int = 0
    contributors: int = 0

    def language_share(self) -> list[tuple[str, int]]:
        """(언어, 비율 %) 큰 순서. 합이 0이면 빈 목록."""
        total = sum(self.languages.values())
        if not total:
            return []
        return sorted(((k, round(v * 100 / total)) for k, v in self.languages.items()), key=lambda x: -x[1])


def parse_repo_url(url: str) -> tuple[str, str]:
    """https://github.com/소유자/저장소. 발표 화면처럼 github.com/… 로 시작하면 https:// 를 붙여 받는다."""
    url = (url or "").strip()
    if url.startswith("github.com/"):
        url = f"https://{url}"
    m = _URL.match(url)
    if not m or m.group(2) in (".", ".."):
        raise InvalidRepoUrl()
    return m.group(1), m.group(2)


def _get(path: str, *, accept: str = "application/vnd.github+json"):
    """(상태, 헤더, 본문 바이트). 4xx는 예외로 바꾼다."""
    req = urllib.request.Request(f"{API}{path}", headers={"Accept": accept, "User-Agent": "nesume",
                                                            "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:  # noqa: S310 (주소는 API 상수 + 검증한 이름)
            return res.status, dict(res.headers), res.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RepoNotFound() from None
        if e.code == 429 or (e.code == 403 and e.headers.get("X-RateLimit-Remaining") == "0"):
            raise RateLimited() from None
        if e.code == 409:  # 빈 저장소(커밋 없음)
            return 409, dict(e.headers), b"[]"
        raise GithubUnavailable(f"http {e.code}") from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise GithubUnavailable(str(e)) from None


def _count(path: str) -> int:
    """per_page=1로 불러 Link 헤더의 마지막 페이지 번호 = 전체 개수."""
    status, headers, body = _get(f"{path}?per_page=1&anon=1")
    if status == 409:
        return 0
    m = _LAST_PAGE.search(headers.get("Link", "") or headers.get("link", ""))
    if m:
        return int(m.group(1))
    return len(json.loads(body or b"[]"))


def _readme(owner: str, repo: str) -> str:
    try:
        _, _, body = _get(f"/repos/{owner}/{repo}/readme")
    except RepoNotFound:  # README 없음
        return ""
    data = json.loads(body)
    if data.get("encoding") == "base64":
        return base64.b64decode(data.get("content", "")).decode("utf-8", errors="replace")
    return data.get("content", "") or ""


_cache: dict[str, tuple[float, RepoStats]] = {}
_lock = threading.Lock()


def fetch(owner: str, repo: str, *, now: float | None = None) -> RepoStats:
    now = time.time() if now is None else now
    key = f"{owner}/{repo}".lower()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    _, _, body = _get(f"/repos/{owner}/{repo}")
    info = json.loads(body)
    if info.get("private"):
        raise RepoNotFound()
    _, _, lang = _get(f"/repos/{owner}/{repo}/languages")
    stats = RepoStats(
        full_name=info.get("full_name", f"{owner}/{repo}"), html_url=info.get("html_url", ""),
        description=info.get("description") or "", languages=json.loads(lang or b"{}"),
        readme=_readme(owner, repo), commits=_count(f"/repos/{owner}/{repo}/commits"),
        contributors=_count(f"/repos/{owner}/{repo}/contributors"),
    )
    with _lock:
        _cache[key] = (now + CACHE_TTL, stats)
    return stats


def clear_cache() -> None:
    with _lock:
        _cache.clear()
