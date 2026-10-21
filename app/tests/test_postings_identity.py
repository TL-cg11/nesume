"""C4 정규화·식별 테스트. DB 불필요(순수 로직)."""
from datetime import date

from app.postings.identity import (
    REPOST_WINDOW_DAYS,
    Action,
    ExistingPosting,
    classify,
    content_hash,
    is_reliable_key,
    link_key,
)
from app.postings.normalize import normalize_code, normalize_company, normalize_title

# --- 정규화: 기업명 ---

def test_company_strips_corp_forms():
    # ㈜ / (주) / 주식회사 가 모두 같은 형태로 정규화돼야 같은 키가 된다
    base = normalize_company("네수메")
    assert normalize_company("㈜네수메") == base
    assert normalize_company("(주)네수메") == base
    assert normalize_company("주식회사 네수메") == base
    assert normalize_company("네수메 주식회사") == base


def test_company_separators_collapse_to_space():
    # 구분자(공백·기호)는 단일 공백으로 통일. 공백 유무 자체는 보존(보수적 — 오묶음 방지)
    assert normalize_company("A B C") == "a b c"
    assert normalize_company("A-B-C") == "a b c"
    assert normalize_company("A  B   C") == "a b c"
    assert normalize_company("ABC") == "abc"  # 공백 없는 표기는 다른 키


def test_company_empty():
    assert normalize_company(None) == ""
    assert normalize_company("") == ""


# --- 정규화: 제목·코드 ---

def test_title_collapses_separators():
    canon = normalize_title("백엔드 개발자")
    assert normalize_title("백엔드/개발자") == canon
    assert normalize_title("백엔드  개발자") == canon


def test_title_fullwidth_nfkc():
    assert normalize_title("ＰＹＴＨＯＮ") == normalize_title("python")


def test_code_strips_noise():
    assert normalize_code(" 024000 ") == "024000"
    assert normalize_code("02-4000") == "024000"
    assert normalize_code(None) == ""


# --- link_key ---

def test_link_key_deterministic_and_normalized():
    a = link_key(
        source="seoul", company="㈜네수메", title="백엔드 개발자", region_code="11000", job_code="024",
    )
    b = link_key(
        source="seoul", company="주식회사 네수메", title="백엔드/개발자", region_code="11000", job_code="024",
    )
    assert a == b  # 표기 차이는 같은 키
    assert len(a) == 64  # sha256 hex


def test_link_key_differs_by_region():
    seoul = link_key(source="seoul", company="네수메", title="백엔드", region_code="11000", job_code="024")
    busan = link_key(source="seoul", company="네수메", title="백엔드", region_code="26000", job_code="024")
    assert seoul != busan  # 지사(지역) 다르면 다른 공고


def test_link_key_native_id_takes_precedence():
    # native_id가 있으면 기업명·제목과 무관하게 출처 ID로만 키 생성
    k1 = link_key(source="saramin", native_id="12345", company="무시됨", title="무시됨")
    k2 = link_key(source="saramin", native_id="12345", company="달라도", title="상관없음")
    assert k1 == k2


def test_link_key_no_date_input():
    # 마감일 같은 날짜는 아예 인자에 없음 → 연장돼도 키 불변 (시그니처로 보장)
    assert "close" not in link_key.__code__.co_varnames


# --- content_hash ---

def test_content_hash_changes_on_body():
    common = dict(company="네수메", title="백엔드", registered_on=date(2026, 10, 1),
                  job_code="024", region_code="11000")
    h1 = content_hash(**common, job_content="파이썬 경험 우대")
    h2 = content_hash(**common, job_content="자바 경험 우대")
    assert h1 != h2


def test_content_hash_stable_on_whitespace():
    common = dict(company="네수메", title="백엔드", registered_on=date(2026, 10, 1),
                  job_code="024", region_code="11000")
    assert content_hash(**common, job_content="a  b\n c") == content_hash(**common, job_content="a b c")


# --- link_key: work_address 보강 ---

def test_link_key_differs_by_work_address():
    base = dict(source="seoul", company="네수메", title="직원 모집", region_code="11000", job_code="024")
    a = link_key(**base, work_address="서울 강남구 테헤란로")
    b = link_key(**base, work_address="서울 노원구 상계동")
    assert a != b  # 같은 기업·제목·지역·직종이라도 지점(근무지) 다르면 다른 공고


# --- is_reliable_key: 약한키·결측 격리 ---

def test_reliable_key_normal():
    assert is_reliable_key(company="네수메", title="백엔드 개발자")


def test_reliable_key_rejects_missing_fields():
    assert not is_reliable_key(company="", title="백엔드 개발자")
    assert not is_reliable_key(company="네수메", title="")


def test_reliable_key_rejects_generic_title():
    assert not is_reliable_key(company="네수메", title="직원 모집")
    assert not is_reliable_key(company="네수메", title="채용")


def test_reliable_key_native_id_always_reliable():
    assert is_reliable_key(native_id="12345")  # 기업·제목 없어도 출처 ID면 신뢰


# --- classify (재공고 판별, missing_streak 기반) ---

H_OLD = "a" * 64
H_NEW = "b" * 64


def test_classify_new_when_no_existing():
    assert classify(None, incoming_content_hash=H_OLD) == Action.NEW


def test_classify_unchanged():
    e = ExistingPosting(content_hash=H_OLD, missing_streak=0, is_active=True)
    assert classify(e, incoming_content_hash=H_OLD) == Action.UNCHANGED


def test_classify_content_changed():
    e = ExistingPosting(content_hash=H_OLD, missing_streak=0, is_active=True)
    assert classify(e, incoming_content_hash=H_NEW) == Action.CONTENT_CHANGED


def test_classify_reactivated_within_window():
    # 비활성(일시 누락)인데 streak ≤ 14 → 복귀
    e = ExistingPosting(content_hash=H_OLD, missing_streak=5, is_active=False)
    assert classify(e, incoming_content_hash=H_OLD) == Action.REACTIVATED


def test_classify_repost_when_streak_exceeds_window():
    # streak > 14 → 재공고, 새 내부 ID
    e = ExistingPosting(content_hash=H_OLD, missing_streak=15, is_active=False)
    assert classify(e, incoming_content_hash=H_OLD) == Action.NEW


def test_classify_boundary_exactly_window_is_same_posting():
    # streak == 14 (경계) → 아직 같은 공고 (복귀)
    e = ExistingPosting(content_hash=H_OLD, missing_streak=REPOST_WINDOW_DAYS, is_active=False)
    assert classify(e, incoming_content_hash=H_OLD) == Action.REACTIVATED
