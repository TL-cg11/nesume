"""C16 NeMo 설정·공정성 시험. nemoguardrails 가 없어도 도는 것(설정 파일·문장 겹침)과
있을 때만 도는 것(의도 판정·다운로드 없음)을 나눈다 — CI 이미지에는 nemoguardrails 가 없다."""

import hashlib
import math
import re
import unicodedata
from pathlib import Path

import pytest
import yaml

from app.guardrails_nemo import compare
from app.guardrails_nemo.intent import ACTION, CONFIG_DIR, parse_intent

SHEET = Path(__file__).resolve().parents[2] / "eval" / "scenarios_sheet.yaml"


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", s)).lower()


def _colang_examples() -> list[str]:
    return re.findall(r'^\s+"(.+)"\s*$', (CONFIG_DIR / "rails.co").read_text(encoding="utf-8"), re.M)


def test_config_uses_only_our_embedding_engine():
    cfg = yaml.safe_load((CONFIG_DIR / "config.yml").read_text(encoding="utf-8"))
    engines = [m["engine"] for m in cfg["models"] if m["type"] == "embeddings"]
    for k in ("core", "knowledge_base"):
        engines.append(cfg[k]["embedding_search_provider"]["parameters"]["embedding_engine"])
    assert engines and set(engines) == {"nesume_bge_m3"}
    assert cfg["rails"]["dialog"]["user_messages"]["embeddings_only"] is True


def test_every_bot_message_maps_to_an_intent():
    bots = re.findall(r'"(NEMO_INTENT:[a-z]+)"', (CONFIG_DIR / "rails.co").read_text(encoding="utf-8"))
    assert {parse_intent(b) for b in bots} == set(ACTION)
    assert parse_intent("I'm sorry, an internal error has occurred.") == "normal"


@pytest.mark.skipif(not SHEET.exists(), reason="평가 시트 없음")
def test_colang_examples_do_not_reuse_eval_sentences():
    """예시 문장에 평가 문장이 들어가면 비교표가 부풀려진다."""
    sheet = yaml.safe_load(SHEET.read_text(encoding="utf-8"))
    evals = {_norm(t) for s in sheet["scenarios"] for t in (s.get("turns") or [])}
    extra = {_norm(t) for t in compare.SECURITY_NORMAL + compare.PARAPHRASED_EXFIL
             + compare.CHUNKS_INJECTED + compare.CHUNKS_NORMAL}
    examples = {_norm(t) for t in _colang_examples()}
    assert len(examples) >= 40
    assert not examples & evals
    assert not examples & extra


def test_combined_only_raises():
    row = compare.Row("x", "B18 정상", "allow", ["t"])
    assert compare.combined(row, "block", ["normal"]) == "block"  # A3 가 막은 것을 풀지 않는다
    assert compare.combined(row, "allow", ["exfil"]) == "block"
    assert compare.combined(row, "allow", ["authz"]) == "flag"
    assert compare.combined(row, "flag", ["normal"]) == "flag"
    chunk = compare.Row("c", "추가 조각(지시문)", "drop", ["t"])
    assert compare.combined(chunk, "keep", ["instruction"]) == "drop"
    assert compare.combined(chunk, "keep", ["exfil"]) == "keep"


# ---------------------------------------------------------------- nemoguardrails 가 있을 때만

class _HashEmbedder:
    """낱말 해시 1024차원 — 네트워크 없이 NeMo 를 끝까지 돌려 보기 위한 가짜."""

    def embed(self, texts):
        out = []
        for t in texts:
            v = [0.0] * 1024
            for w in t.split():
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 1024] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


# nemoguardrails 가 import 때 내는 경고(제3자 코드) — pytest.ini 의 경고=오류에서 이 시험만 뺀다
@pytest.mark.filterwarnings("ignore::DeprecationWarning", "ignore::UserWarning")
def test_rail_runs_without_llm_or_downloads(tmp_path, monkeypatch):
    pytest.importorskip("nemoguardrails")
    from app.guardrails_nemo.intent import NemoIntentRail

    cache = tmp_path / "fastembed"
    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(cache))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    rail = NemoIntentRail(_HashEmbedder(), threshold=0.99)
    example = _colang_examples()[0]  # 예시 문장 그 자체는 유사도 1 → 그 의도
    got = rail.check_many([example, "전혀 관계없는 문장입니다"])
    assert got[0].intent == "authz"
    assert got[1].intent == "normal"  # 임계값 아래 → fallback
    assert not cache.exists() or not any(cache.rglob("*"))  # 기본 FastEmbed 모델을 받지 않았다
