"""임베딩 클라이언트 추상화.

운영(EKS)에서 bge-m3를 어떻게 서빙할지는 D 결정(docs/C_임베딩모델_제안.md: 별도 임베딩 컨테이너 권장).
C3 파이프라인·C8 추천은 이 `Embedder` 프로토콜만 의존하므로 서빙 방식이 바뀌어도 코드가 그대로다.

- `LocalBgeM3Embedder`: 개발·배치용(sentence-transformers·torch, 지연 로드). **app 이미지엔 넣지 않는다.**
- (운영) D 임베딩 서비스 HTTP 클라이언트는 D 서빙 확정 후 추가.

차원 1024 고정. bge-m3는 정규화 임베딩 → 코사인 유사도.
"""
from typing import Protocol

EMBED_DIM = 1024


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
