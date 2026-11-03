"""K-MOOC 실제 강좌 수집(로컬 데모). 실제 apis.data.go.kr 호출.
목록 전수 대신 N페이지 제한 → 제목으로 역량 태깅(색인 미구현 보완) → 매칭분만 상세 보강·적재.
실행: docker compose exec -T -e KMOOC_API_KEY=... app python - < collect_kmooc.py
"""
import os

from app.db import SessionLocal
from app.features.roadmap import kmooc
from app.features.roadmap.kmooc import KMOOC_SOURCE
from app.features.roadmap.service import upsert_contents
from app.models.learning import LearningContent

# 로드맵 갭 키 ↔ 제목에 나올 법한 동의어(한/영). 제목에 있으면 그 갭 키로 태깅.
SYN = {
    "aws": ["aws", "클라우드", "cloud"],
    "docker": ["docker", "도커", "컨테이너"],
    "kubernetes": ["kubernetes", "쿠버네티스", "k8s"],
    "linux": ["linux", "리눅스", "유닉스", "unix"],
    "git": ["git", "github", "깃허브", "깃"],
    "terraform": ["terraform", "테라폼"],
    "python": ["python", "파이썬"],
    "network": ["네트워크", "network", "tcp"],
    "security": ["보안", "security", "정보보호", "해킹"],
}
MAX_PAGES = int(os.environ.get("COLLECT_MAX_PAGES", "50"))
CAP = int(os.environ.get("COLLECT_CAP", "60"))


def tag(title: str) -> list[str]:
    t = (title or "").lower()
    return [k for k, syns in SYN.items() if any(s.lower() in t for s in syns)]


def main():
    # 1) 목록만 빠르게(상세 없이) 수집
    courses = kmooc.collect(kmooc.fetch_list_page, fetch_detail=None, page_size=100, max_pages=MAX_PAGES)
    print(f"목록 수집: {len(courses)}건 (max_pages={MAX_PAGES})")

    # 2) 제목 태깅 → 매칭분만
    matched = []
    for c in courses:
        keys = tag(c.title)
        if keys and c.url and c.external_id:
            matched.append((c, keys))
        if len(matched) >= CAP:
            break
    print(f"역량 태깅 매칭: {len(matched)}건")

    s = SessionLocal()
    try:
        # 가짜 시드 제거(kmooc-/w24-)
        s.query(LearningContent).filter(LearningContent.external_id.like("kmooc-%")).delete()
        s.query(LearningContent).filter(LearningContent.external_id.like("w24-%")).delete()
        s.commit()

        # 3) 매칭분 상세 보강(시간·요약·수료증)
        enriched = []
        for c, keys in matched:
            try:
                c = kmooc.merge_detail(c, kmooc.detail_results(kmooc.fetch_course_detail(c.external_id)))
            except Exception as e:  # 상세 실패해도 목록 수준으로 적재
                print(f"  detail 실패({c.external_id}): {e}")
            enriched.append((c, keys))

        # 4) 적재 + competency_keys 태깅
        counts = upsert_contents(s, [c for c, _ in enriched])
        s.commit()
        for c, keys in enriched:
            row = s.query(LearningContent).filter_by(source=KMOOC_SOURCE, external_id=c.external_id).first()
            if row:
                row.competency_keys = keys
        s.commit()
        print(f"적재: {counts}")

        # 갭 키별 보유 수 + 샘플
        from collections import Counter
        cnt = Counter()
        for _, keys in enriched:
            for k in keys:
                cnt[k] += 1
        print("갭 키별 강좌 수:", dict(cnt))
        print("샘플:")
        for c, keys in enriched[:8]:
            print(f"  [{'+'.join(keys)}] {c.title} | {c.url}")
    finally:
        s.close()


if __name__ == "__main__":
    main()
