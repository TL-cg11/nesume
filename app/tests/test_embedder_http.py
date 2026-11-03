"""C3 HttpEmbedder 테스트 (네트워크 없음 — urlopen 가짜). docs/C3.md HttpEmbedder."""
import io
import json
import urllib.error

import pytest

from app.retrieval import embedder as em

_SECRET_TEXT = "토큰화된 자소서 [[PHONE_1]] 본문"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _vecs(n, dim=em.EMBED_DIM):
    return [[0.01] * dim for _ in range(n)]


def _fake(monkeypatch, outcomes):
    """outcomes: 요청마다 돌려줄 것(Exception이면 raise, callable이면 요청 본문으로 응답 생성)."""
    bodies = []

    def fake_urlopen(req, timeout):
        payload = json.loads(req.data)
        bodies.append(payload)
        out = outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        if callable(out):
            out = out(payload)
        return _Resp(json.dumps(out).encode())

    monkeypatch.setattr(em.urllib.request, "urlopen", fake_urlopen)
    return bodies


def _http_error(code):
    return urllib.error.HTTPError("http://embedder:8080/embed", code, "err", {}, None)


def test_batches_by_32_and_keeps_order(monkeypatch):
    echo = lambda p: _vecs(len(p["inputs"]))  # noqa: E731
    bodies = _fake(monkeypatch, [echo, echo, echo])
    out = em.HttpEmbedder("http://embedder:8080/", sleep=lambda s: None).embed([f"t{i}" for i in range(66)])
    assert len(out) == 66 and len(out[0]) == em.EMBED_DIM
    assert [len(b["inputs"]) for b in bodies] == [32, 32, 2]
    assert bodies[0]["normalize"] is True and bodies[0]["truncate"] is True
    assert bodies[2]["inputs"] == ["t64", "t65"]


def test_retries_5xx_and_connection_errors(monkeypatch):
    sleeps = []
    _fake(monkeypatch, [_http_error(503), ConnectionRefusedError(), _vecs(1)])
    out = em.HttpEmbedder("http://embedder:8080", sleep=sleeps.append).embed(["a"])
    assert len(out) == 1 and sleeps == [1.0, 2.0]


def test_4xx_fails_immediately(monkeypatch):
    sleeps = []
    _fake(monkeypatch, [_http_error(413)])
    with pytest.raises(em.EmbeddingError, match="HTTP 413"):
        em.HttpEmbedder("http://embedder:8080", sleep=sleeps.append).embed(["a"])
    assert sleeps == []


def test_error_does_not_leak_input_text(monkeypatch):
    _fake(monkeypatch, [_http_error(503)] * 5)
    with pytest.raises(em.EmbeddingError) as ei:
        em.HttpEmbedder("http://embedder:8080", sleep=lambda s: None).embed([_SECRET_TEXT])
    assert _SECRET_TEXT not in str(ei.value) and _SECRET_TEXT not in repr(ei.value)
    assert ei.value.__cause__ is None and ei.value.__suppress_context__


@pytest.mark.parametrize(
    ("response", "match"),
    [
        (_vecs(2), "개수"),                       # 입력 1개에 2개
        ([[0.1] * 768], "차원"),                   # 다른 모델 차원
        ([[float("nan")] * em.EMBED_DIM], "유한"),  # NaN
        ([[True] * em.EMBED_DIM], "유한"),          # bool
        ({"error": "x"}, "개수"),                  # TEI 오류 본문
    ],
)
def test_rejects_malformed_response(monkeypatch, response, match):
    _fake(monkeypatch, [response])
    with pytest.raises(em.EmbeddingError, match=match):
        em.HttpEmbedder("http://embedder:8080", sleep=lambda s: None).embed(["a"])


@pytest.mark.parametrize("url", ["embedder:8080", "file:///etc/passwd", "ftp://x/"])
def test_rejects_bad_url(url):
    with pytest.raises(em.EmbeddingError):
        em.HttpEmbedder(url)


def test_get_embedder_none_without_url(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "embedding_url", "")
    assert em.get_embedder() is None
    monkeypatch.setattr(get_settings(), "embedding_url", "http://embedder:8080")
    assert isinstance(em.get_embedder(), em.HttpEmbedder)


# ---- 요청 경로 정책 (11-03, docs/C6.md "요청 경로 임베더는 짧게") ----

def _refused(*a, **k):
    raise urllib.error.URLError(ConnectionRefusedError(61, "refused"))


def test_query_policy_retries_refused_once_quickly(monkeypatch):
    calls, sleeps = [], []

    def flaky(req, timeout):
        calls.append(timeout)
        if len(calls) == 1:
            _refused()
        return _Resp(json.dumps([[0.0] * em.EMBED_DIM]).encode())

    monkeypatch.setattr(em.urllib.request, "urlopen", flaky)
    q = em.HttpEmbedder("http://embedder:8080", sleep=sleeps.append).with_query_policy()
    assert len(q.embed(["a"])) == 1
    assert calls == [em.QUERY_TIMEOUT_S, em.QUERY_TIMEOUT_S] and sleeps == [0.2]


def test_query_policy_does_not_retry_timeout_or_5xx(monkeypatch):
    sleeps = []
    q = em.HttpEmbedder("http://embedder:8080", sleep=sleeps.append).with_query_policy()

    def timeout(req, timeout):
        raise TimeoutError()

    monkeypatch.setattr(em.urllib.request, "urlopen", timeout)
    with pytest.raises(em.EmbeddingError):
        q.embed(["a"])

    def http500(req, timeout):
        raise urllib.error.HTTPError("http://embedder:8080/embed", 503, "busy", {}, None)

    monkeypatch.setattr(em.urllib.request, "urlopen", http500)
    with pytest.raises(em.EmbeddingError):
        q.embed(["a"])
    assert sleeps == []  # 기다리지 않는다 — 최악 = 시간 제한 한 번


def test_query_policy_refused_twice_gives_up_after_one_retry(monkeypatch):
    calls, sleeps = [], []

    def always_refused(req, timeout):
        calls.append(1)
        _refused()

    monkeypatch.setattr(em.urllib.request, "urlopen", always_refused)
    with pytest.raises(em.EmbeddingError):
        em.HttpEmbedder("http://embedder:8080", sleep=sleeps.append).with_query_policy().embed(["a"])
    assert len(calls) == 2 and sleeps == [0.2]


def test_batch_default_unchanged(monkeypatch):
    """배치 기본(긴 재시도)은 그대로 — 카나리 시드 훅이 임베더 기동 중에도 버틴다."""
    sleeps = []
    monkeypatch.setattr(em.urllib.request, "urlopen", _refused)
    with pytest.raises(em.EmbeddingError):
        em.HttpEmbedder("http://embedder:8080", sleep=sleeps.append).embed(["a"])
    assert tuple(sleeps) == em.RETRY_DELAYS


def test_get_query_embedder(monkeypatch):
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "embedding_url", "")
    assert em.get_query_embedder() is None
    monkeypatch.setattr(get_settings(), "embedding_url", "http://embedder:8080")
    q = em.get_query_embedder()
    assert isinstance(q, em.HttpEmbedder) and q._timeout_s == em.QUERY_TIMEOUT_S


def test_build_retriever_forces_query_policy():
    """A가 배치용 get_embedder()를 넘겨도 검색은 짧은 정책으로 돈다."""
    from app.retrieval.search import build_retriever

    r = build_retriever(em.HttpEmbedder("http://embedder:8080"))
    assert r is not None
    assert r._embedder._timeout_s == em.QUERY_TIMEOUT_S and r._embedder._retry_delays == em.QUERY_RETRY_DELAYS


def test_tests_do_not_read_local_embedding_url():
    from app.config import get_settings

    assert get_settings().embedding_url == ""  # conftest가 끈다

