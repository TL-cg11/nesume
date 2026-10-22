"""A14 — 사용자 말투 프로필.

리라이팅(A6)·조정(A13)이 "이 사람처럼" 쓰게 하려고 들고 있는 값이다.

    PUT    /profile/writing   쓴 글(1,000자+) → 프로필 생성·갱신
    GET    /profile/writing   내 프로필
    DELETE /profile/writing   내 프로필 삭제

## 이 기능에서 가장 중요한 판단 네 가지

**① 화이트리스트로만 센다.** 자주 쓰는 "표현" 을 그대로 저장하면 **회사명·학교명·사람
이름이 프로필로 새어 들어온다.** 프로필은 PII 가 아니라고 생각하고 만든 테이블이라,
거기서 PII 가 새면 아무도 예상하지 못한다. 그래서 종결 어미·연결어를 **미리 정해 두고
그 안에서만** 센다. 사전 밖의 말은 개수조차 세지 않는다.

**② 본인만 쓴다 — 멘토·운영자도 못 본다.** 말투 프로필은 **문체 지문**이라, 공유된
자소서를 보고 누가 썼는지 역추적하는 데 쓸 수 있다. **마스킹으로 가릴 수 있는 종류의
값이 아니다.** `matrix.yaml` 보다 엄격하며, 그 차이를 D·C 에 알려 두었다.

**③ 1,000자 미만으로는 만들지 않는다.** 표본이 적으면 말투가 아니라 **그 글의 우연**이다.
그 프로필로 리라이팅하면 엉뚱한 문체를 사용자에게 되돌려준다.

**④ LLM 을 부르지 않는다.** 모델에게 말투를 요약하게 하면 **요약문에 원문 조각이
들어오고** 그것이 저장된다. 규칙으로 뽑으면 그럴 수 없다.

## A13 과 겹치지 않는다

| | 보는 것 |
| --- | --- |
| **A13** | 문체 **종류** — 합니다체/해요체가 섞였는지 (교정) |
| **A14** | 그 안의 **개인 습관** — 어떤 종결·연결을 즐겨 쓰는지 (복원) |

A13 은 "틀린 것" 을 찾고, A14 는 "이 사람다운 것" 을 찾는다.
"""

from app.features.profile.extract import (
    LONG_SENTENCE_LEN,
    MIN_SOURCE_CHARS,
    TOP_N,
    NotEnoughText,
    TokenizedTextError,
    WritingStyle,
    extract,
)
from app.features.profile.service import (
    PROMPT_HEADER,
    THIN_SAMPLE_NOTICE,
    THIN_SENTENCE_COUNT,
    build,
    delete,
    get,
    is_thin,
    prompt_fragment,
)
from app.features.profile.store import (
    DbProfileStore,
    InMemoryProfileStore,
    ProfileStore,
)

__all__ = [
    # 추출
    "extract",
    "WritingStyle",
    "MIN_SOURCE_CHARS",
    "LONG_SENTENCE_LEN",
    "TOP_N",
    "NotEnoughText",
    "TokenizedTextError",
    # 조립
    "build",
    "get",
    "delete",
    "is_thin",
    "prompt_fragment",
    "PROMPT_HEADER",
    "THIN_SAMPLE_NOTICE",
    "THIN_SENTENCE_COUNT",
    # 저장소
    "ProfileStore",
    "InMemoryProfileStore",
    "DbProfileStore",
]
