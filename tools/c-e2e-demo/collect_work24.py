"""WORK24(고용24) 국민내일배움카드 훈련과정 수집(로컬 데모).
API: /cm/openApi/call/hr/callOpenApiSvcInfo310L01.do (키워드 검색 지원).
titleLink = 실제 과정 상세 페이지 URL → LearningContent(source=work24, mode=offline).
실행: docker compose exec -T -e WORK24_TRAINING_API_KEY=... app python - < collect_work24.py
"""
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from app.db import SessionLocal
from app.models.learning import LearningContent

KEY = os.environ["WORK24_TRAINING_API_KEY"]
BASE = "https://www.work24.go.kr/cm/openApi/call/hr/callOpenApiSvcInfo310L01.do"
# 로드맵 갭 키 ↔ WORK24 검색 키워드(LearningPage 역량과 맞춤)
KW = {"aws": "클라우드", "security": "정보보안", "python": "파이썬", "network": "네트워크", "linux": "리눅스"}
PER = int(os.environ.get("W24_PER", "5"))


def fetch(keyword: str) -> str:
    q = urllib.parse.urlencode({
        "authKey": KEY, "returnType": "XML", "outType": "1",
        "pageNum": 1, "pageSize": PER,
        "srchTraStDt": "20250101", "srchTraEndDt": "20261231",
        "srchTraProcessNm": keyword,
    })
    with urllib.request.urlopen(f"{BASE}?{q}", timeout=30) as r:  # noqa: S310
        return r.read().decode("utf-8")


def parse(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    out = []
    for node in root.findall(".//scn_list"):
        def t(tag):
            e = node.find(tag)
            return (e.text or "").strip() if e is not None and e.text else None
        title, link, prov = t("title"), t("titleLink"), t("subTitle")
        if not title or not link:
            continue
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
        ext = f"{qs.get('tracseId', [''])[0]}_{qs.get('tracseTme', [''])[0]}"
        out.append({
            "external_id": ext, "title": title, "url": link,
            "provider": prov, "address": t("address"),
            "start": t("traStartDate"), "end": t("traEndDate"),
        })
    return out


def main():
    s = SessionLocal()
    try:
        s.query(LearningContent).filter(LearningContent.source == "work24").delete()
        s.commit()
        total = 0
        for key, kw in KW.items():
            try:
                rows = parse(fetch(kw))
            except Exception as e:
                print(f"  [{key}] '{kw}' 실패: {e}")
                continue
            n = 0
            for r in rows:
                if not r["external_id"] or r["external_id"] == "_":
                    continue
                ex = s.query(LearningContent).filter_by(source="work24", external_id=r["external_id"]).first()
                if ex:
                    if key not in (ex.competency_keys or []):
                        ex.competency_keys = list(ex.competency_keys or []) + [key]
                    continue
                summary = " · ".join(x for x in [r["provider"], r["address"], (f"{r['start']}~{r['end']}" if r["start"] else None)] if x)
                s.add(LearningContent(
                    source="work24", external_id=r["external_id"], mode="offline",
                    title=r["title"], url=r["url"], provider=r["provider"],
                    summary=summary or None, competency_keys=[key], is_active=True,
                ))
                n += 1
            s.commit()
            total += n
            print(f"  [{key}] '{kw}' → {n}건 신규")
        print(f"work24 훈련과정 적재 총 {total}건")
        for row in s.query(LearningContent).filter_by(source="work24").limit(8):
            print(f"  - {row.competency_keys} {row.title[:30]} | {row.url[:72]}")
    finally:
        s.close()


if __name__ == "__main__":
    main()
