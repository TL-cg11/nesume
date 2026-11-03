"""임베딩 클라이언트 추상화.

운영(EKS)에서 bge-m3를 어떻게 서빙할지는 D 결정(docs/C_임베딩모델_제안.md: 별도 임베딩 컨테이너 권장).
C3 파이프라인·C8 추천은 이 `Embedder` 프로토콜만 의존하므로 서빙 방식이 바뀌어도 코드가 그대로다.

- `LocalBgeM3Embedder`: 개발·배치용(sentence-transformers·torch, 지연 로드). **app 이미지엔 넣지 않는다.**
- `HttpEmbedder`: 운영·로컬 — D20 임베딩 서비스(TEI + bge-m3, embedder/README.md) HTTP 클라이언트.
- `get_embedder()`: 설정 `EMBEDDING_URL`이 있으면 HttpEmbedder, 없으면 None(임베딩 없이 동작).
  **배치용**(긴 재시도).
- `get_query_embedder()`: 같은 서비스, **요청 경로용**(5초, 연결 거부만 한 번).
  가드레일 검색은 `build_retriever`가 알아서 바꾼다.

차원 1024 고정. bge-m3는 정규화 임베딩 → 코사인 유사도.
"""
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Protocol

EMBED_DIM = 1024
#: TEI `MAX_CLIENT_BATCH_SIZE`(compose·Helm 32, D20 #28에서 64→32). 넘기면 서버가 거부한다
BATCH_SIZE = 32
#: 노드 교체 중이면 수 분 불가(D20) → 5xx·연결 오류만 재시도.
#: 대량 색인 중 임베더가 잠시 NotReady 로 빠질 수 있어 총 ~1분 기다린다(10-29 dev 강좌 8,700건)
RETRY_DELAYS = (1.0, 2.0, 4.0, 8.0, 15.0, 30.0)
#: 요청 경로(사용자가 기다리는 곳 — 가드레일 검색·C14 로드맵) 정책. 위 배치 기본(최악 ~8분)을 쓰면
#: 임베더가 매달릴 때 AI 요청이 분 단위로 늦는다(11-03 지적, docs/C6.md).
#: 시간 제한 5초(측정 전 값), 연결 거부일 때만 0.2초 뒤 한 번.
QUERY_TIMEOUT_S = 5.0
QUERY_RETRY_DELAYS = (0.2,)
_MAX_BYTES = 64 * 1024 * 1024  # 32 × 1024 float JSON ≈ 0.7MB. 넉넉한 상한


class EmbeddingError(RuntimeError):
    """임베딩 실패. 메시지에 **입력 텍스트·응답 본문을 싣지 않는다**(토큰화된 자소서가 로그에 남지 않게)."""


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]:
        """텍스트 목록 → 1024차원 정규화 벡터 목록."""
        ...


class LocalBgeM3Embedder:
    """개발·배치용. bge-m3를 로컬에서 실행(지연 로드). `sentence-transformers`·`torch` 필요."""

    def __init__(self, model_name: str = "BAAI/bge-m3"):
        self._model_name = model_name
        self._model = None

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self._model is None:
            # 지연 import — app 이미지가 torch에 의존하지 않도록
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        return self._model.encode(texts, normalize_embeddings=True).tolist()


class HttpEmbedder:
    """D20 임베딩 서비스 클라이언트. `POST {url}/embed {"inputs":[…],"normalize":true,"truncate":true}`.

    - `BATCH_SIZE`(32)개씩 나눠 보내고 순서대로 이어 붙인다.
    - 5xx·타임아웃·연결 오류는 `RETRY_DELAYS`만큼 재시도, 4xx는 즉시 실패.
    - 응답 검증: 개수 = 입력 수, 각 1024차원, 유한한 실수. 어긋나면 실패(잘못된 벡터를 적재하지 않는다).
    - URL은 설정값으로만(사용자 입력 아님). http는 클러스터 내부·로컬 서비스라 허용.
    """

    def __init__(
        self,
        url: str,
        *,
        timeout_s: float = 60.0,
        sleep=time.sleep,
        retry_delays: tuple[float, ...] = RETRY_DELAYS,
        retry_refused_only: bool = False,
    ):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise EmbeddingError("EMBEDDING_URL은 http(s)://host 형식이어야 한다")
        self._url = url
        self._endpoint = url.rstrip("/") + "/embed"
        self._timeout_s = timeout_s
        self._sleep = sleep
        self._retry_delays = tuple(retry_delays)
        #: True면 연결 거부(임베더 재시작 중)만 다시 시도한다. 시간 초과·5xx는 바로 실패(기다려도 늦기만 함)
        self._retry_refused_only = retry_refused_only

    def with_query_policy(self) -> "HttpEmbedder":
        """같은 서비스를 요청 경로 정책(5초, 연결 거부만 0.2초 뒤 1번)으로 부르는 복사본. 배치는 그대로."""
        return HttpEmbedder(
            self._url,
            timeout_s=QUERY_TIMEOUT_S,
            sleep=self._sleep,
            retry_delays=QUERY_RETRY_DELAYS,
            retry_refused_only=True,
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i:i + BATCH_SIZE]
            out.extend(_validate(self._post(batch), len(batch)))
        return out

    def _post(self, batch: list[str]) -> object:
        body = json.dumps({"inputs": batch, "normalize": True, "truncate": True}).encode("utf-8")
        reason = ""
        delays = self._retry_delays
        for attempt in range(len(delays) + 1):
            req = urllib.request.Request(
                self._endpoint, data=body, method="POST", headers={"content-type": "application/json"}
            )
            try:
                with urllib.request.urlopen(req, timeout=self._timeout_s) as resp:  # noqa: S310 (설정값 내부 서비스)
                    raw = resp.read(_MAX_BYTES + 1)
                break
            except urllib.error.HTTPError as e:
                reason, retryable = f"HTTP {e.code}", e.code >= 500 and not self._retry_refused_only
            except Exception as e:  # noqa: BLE001 - 타임아웃·연결 오류. 본문이 예외에 딸려 가지 않게 바꿔 올린다
                reason = type(e).__name__
                retryable = _is_refused(e) if self._retry_refused_only else True
            if not retryable or attempt == len(delays):
                raise EmbeddingError(f"임베딩 요청 실패: {reason}") from None
            self._sleep(delays[attempt])
        if len(raw) > _MAX_BYTES:
            raise EmbeddingError("임베딩 응답 크기 초과")
        try:
            return json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise EmbeddingError("임베딩 응답이 JSON이 아님") from None


def _is_refused(exc: BaseException) -> bool:
    """연결 거부(서비스가 막 재시작 중). urllib은 `URLError(reason=ConnectionRefusedError)`로 싼다."""
    if isinstance(exc, ConnectionRefusedError):
        return True
    return isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, ConnectionRefusedError)


def _validate(payload: object, n: int) -> list[list[float]]:
    if not isinstance(payload, list) or len(payload) != n:
        raise EmbeddingError("임베딩 응답 개수가 입력과 다름")
    vecs = []
    for v in payload:
        if not isinstance(v, list) or len(v) != EMBED_DIM:
            raise EmbeddingError(f"임베딩 차원이 {EMBED_DIM}이 아님")
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in v):
            raise EmbeddingError("임베딩 값이 유한한 실수가 아님")
        vecs.append([float(x) for x in v])
    return vecs


def get_embedder() -> Embedder | None:
    """설정 `EMBEDDING_URL`이 있으면 HttpEmbedder, 없으면 None(호출부는 임베딩 없이 동작)."""
    from app.config import get_settings  # 지연 import — 테스트가 env 없이 모듈을 import할 수 있게

    url = get_settings().embedding_url
    return HttpEmbedder(url) if url else None


def get_query_embedder() -> Embedder | None:
    """요청 경로용(`QUERY_TIMEOUT_S`, 연결 거부만 한 번 재시도). 배치는 `get_embedder()`(긴 재시도)를 쓴다."""
    embedder = get_embedder()
    return embedder.with_query_policy() if isinstance(embedder, HttpEmbedder) else embedder
