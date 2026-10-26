# 로컬 후보의 생성 응답 형식 개입

2026-10-26 · 설계만 · 기준 소스 `b5cae0d817510ba7b77eedf05ff2a146c038e624`

**다음 개입 하나는 명시적 opt-in `claims-json-gbnf-v1`에서 요약·QA의 생성 문법을 고정하는 것이다.** 프롬프트·원문·질문·모델·예산·parser는 그대로 둔다. 목표는 문맥에 맞고 충분한 자연어 요약·답변이며, 생성 문법을 통과한 뒤에도 근거와 의미를 별도로 판정한다.

[실제 v4](../experiments/results/meetings-local-resource-actual-v1.json)는 생성8·요약4/QA4 전부 거부·parsed0·review0이며 소비됐다. [최종 구조 진단](../experiments/results/meetings-local-resource-structure-v1.json)은 입력2,275–3,184토큰, 생성 grammar 빈 값8건, 코드 펜스 시작8건을 확인했다. 원래 native 계약·오류 우선순위와 모순되는 증거는 없었다.

EOS4건(요약1/QA3)은 펜스 내부 JSON이 성립했지만 전체 응답은 strict JSON이 아니었다. 요약1건은 주장5개 모두 근거가5–9개로 기존1–4개 계약을 위반했다. QA3건의 필요 구조 조건 확인은 실제 ID/offset·질문 충족·의미적 지원 검증이 아니다. 나머지4건은 실제 토큰이 요청 상한에 도달한 미완결 응답이다. 어떤 기존 출력도 수정·채택하거나 성공으로 재분류하지 않는다.

| 대안 | 선택 판단 |
|---|---|
| 펜스 제거·부분 JSON 추출 | 거부. 미완결4건과 요약 근거 개수 위반을 해결하지 못하며 기존 수용 경계를 바꾼다. |
| 토큰/시간 상향 또는 원문·주장·근거 사후 축소 | 거부. 고정 예산이나 내용·근거를 바꾸는 별도 개입이다. |
| 프롬프트 강조·예시 추가 | 보류. 현재도 JSON만 요구하며, 이번에는 관측된 출력 형식에 직접 대응하는 문법 한 가지를 고정한다. |
| 일반 JSON-only schema | 보류. JSON 형태만으로 정확 키·주장/근거 개수 계약까지 표현하지 못한다. |
| 기존 계약을 표현한 고정 GBNF | **선택.** 펜스 없는 JSON 구조·배열 상한을 생성 중 제한하는 후보이며, 완결·속도·의미 개선은 미확인이다. |

현재 candidate `complete`는 summary/QA에 빈 grammar, review에만 `REVIEW_GRAMMAR`를 전달한다. `GGUFGenerator._complete`는 grammar를 native 요청에 포함하고 응답의 실제 설정 echo를 정확히 대조한다. 이 연결과 기존 strict parser를 재사용한다.

최소 구현 범위는 `scripts/probe_meeting_local_candidate.py`와 `tests/test_probe_meeting_local_candidate.py` 두 파일이다. 요약은 frozen `meeting_grounded_summary.GENERATION_GRAMMAR`를 그대로 import한다. QA는 아래 정수 ID 계약의 작은 static grammar 한 개만 candidate 내부에 추가한다. 기존 `meeting_answer_grammar.ANSWER_GRAMMAR`는 `{id,quote}` 근거와0–9 ID를 쓰는 다른 계약이므로 사용하지 않는다. frozen77·공통 GGUF·parser·서비스 경로는 수정하지 않는다.

기존 schema1/2와 직접 생성한 adapter의 기본값은 현재와 동일하게 summary/QA grammar가 빈 값이며, review grammar·요청 메시지/바이트·한도·기존 등록은 보존한다. 새 schema3만 기존 schema2의 정확한 resource policy/limits와 compact wire에 `response_format` 필드를 추가한다. 새 문법에 맞춘 프롬프트나 원문 재작성은 없다.

`response_format`은 정확히 `{policy,summary_sha256,qa_sha256,review_sha256}` 네 키다. policy는 `claims-json-gbnf-v1` 하나이며, 나머지는 코드에 고정된 각 grammar UTF-8 bytes의 SHA-256과 정확히 같아야 한다. 임의 문법 문자열·CLI/env override·unknown version·추가/누락 키·잘못된 타입·hash 불일치는 native 전에 거부한다. 새 정책이 없는 구 등록을 자동 승격하지 않는다.

기존 순수 `registration_policy`는 schema3의 형식 결속도 검증한 뒤 같은 `native-rss6-host2-v1`을 반환하도록 좁게 확장한다. 외부 observer와 내부 실행이 동일 등록을 해석해야 한다. adapter에는 검증된 불변 format 선택만 전달하고, 새 report/terminal에는 policy와 grammar hash3종을 기록한다. code/등록 SHA와 native의 정확 grammar echo를 함께 결속한다.

요약 grammar는 기존 `draft|abstained`, top-level `status,claims`, claim의 `evidence,text`, 주장1–6개·근거1–4개를 그대로 쓴다. QA grammar는 `answered|abstained`와 같은 배열 상한·정수 ID 형태를 쓰되 현재 QA prompt의 `text→evidence` 키 순서를 따른다. QA prompt의1–4개 권고와 parser의1–6개 수용 범위도 변경하지 않는다. abstained는 기존 빈 claims 형태만 허용하며 성공으로 강제 전환하지 않는다.

ID 문법은 기존 원문 분할의 최대160 units에 맞는0–159 정수 표현이다. 원본 ID를 재번호화하거나 선택·정렬·중복 제거하지 않는다. 실제 ID 존재·정확 offset/quote 연결·중복·요약 근거의 원문 순서는 기존 parser가 계속 검사한다. QA의 근거 순서에 새 조건을 추가하지 않는다. 부족한 근거를 사후 잘라서1–4개로 맞추지 않는다.

JSON 문자열은 한글·영어·비BMP 문자·따옴표·역슬래시·표준 escape를 표현할 수 있어야 한다. Unicode 정규화·문구 치환은 없다. 문법은 기존 string/escape 규칙을 재사용하고, 요약 문자240/합계1200·단일문단·한글 및 QA의 기존 text 길이/공백 조건은 parser에 남긴다. ID의 잘못된 숫자형·중복 키·JSON에서 허용하지 않는 raw 제어문자·잘못된 escape를 느슨하게 수용하지 않는다.

문법이 요청됐어도 EOS가 아니면 기존 `generation_output_limit`이다. 닫는 괄호·따옴표를 보충하거나 cap에서 완결처럼 보이는 JSON을 채택하지 않는다. EOS 뒤에도 strict JSON→기존 schema/evidence→요약 필수 review를 모두 통과해야 한다. 내용 거부는 다음 고정 항목으로 진행하고, native 설정 불일치·프로토콜·자원 오류는 기존대로 STOP한다.

유효 요약은 기존 `REVIEW_GRAMMAR`와128토큰으로 반드시 자체 검토한다. 요약 생성과 검토의120초 공유 deadline을 재시작하지 않으며 검토 입력도4096을 다시 적용한다. 검토 불충분·거부·초과를 통과로 바꾸지 않는다. QA에는 새 검토 단계나 재생성을 추가하지 않는다.

원문4·질문4·기준·compact wire·template·greedy·모델/프로필·ctx6144·parallel1·GPU99·f16 KV는 동일하다. 입력4096, 출력768/128/256, 요약+검토120초/QA60초, 시작120/활성900/정리5/전체1025초, native RSS6GiB/시작8GiB/호스트여유2GiB, 생성8+검토최대4/출력예산4608도 유지한다. 문법 비용 때문에 더 느리거나 여전히 cap에 닿을 수 있다.

후속 회귀는 기존 candidate105 cases와 관련 frozen guard6 cases를 보존하고 다음을 확인한다. 이번 설계에서 검사·문법 컴파일·모델 실행은 하지 않는다.

- schema1/2 default·메시지와 요청 grammar 바이트 불변; schema3의 정확 field/type/policy/hash/wire/resource 결속, unknown·혼합·누락·변조는 native 전 거부.
- 요약/QA/review 각각 정확 grammar 선택·native echo 일치, mismatch 시 STOP·추가 completion0·자동 무문법 fallback 없음.
- 정확 top-level/claim 키, 주장0/1/6/7·근거0/1/4/5 경계, abstained, fence/산문/중복 키/불완전 JSON. grammar 모양 확인과 parser 검사를 실제 엔진 제약 검증으로 부르지 않는다.
- 한글·비BMP·조합형·따옴표·역슬래시·escape/잘못된 escape·단독 surrogate·줄바꿈·문자 길이 경계; 원본 ID0/159·실제 범위 밖·음수/실수/bool·중복·요약 비정렬은 기존 parser 기준으로 확인.
- EOS/cap 미만·limit/cap 도달·limit인데 JSON이 닫힌 경우, summary 성공 후 mandatory review의 입력/토큰/공유시간 거부와 QA 고정 일정·고정 분모.
- 내용/프로토콜 실패 구분과 첫 실패 보존, 자원 감시·소유 핸들·lease·drain·cleanup·전체 deadline·설정/등록/출력 hash 결속 유지.

실제 GBNF 엔진의 호환성·제약 수행은 mock HTTP나 문자열 검사로 입증할 수 없다. [고정 runtime revision의 공식 GBNF 문서](https://raw.githubusercontent.com/ggml-org/llama.cpp/d81235049384534c167caea52b85a694f6103d14/grammars/README.md)는 grammar 필드·Unicode·반복 구문을 지원 근거로 제공한다. 실제 적합성은 별도 승인된 한 번의 실행에서 설정 echo·종료·원본 응답·parser 결과로만 확인하며, 문법 오류면 실패를 보존하고 설정 변경·재시도하지 않는다.

부모 수용·공개 → source2 최소 구현 → synthetic 검사·독립 검토·정확 소스 CI → 새 schema3 등록·새 출력·새 companion → 별도 실제1회 배정 순서다. fresh gate1회 거부면 CLI0, 통과 시 공식CLI1회이며 폴링·다른 앱 종료·사전 native 탐색은 없다. v4 소비 결과와 v3 미소비 거부 기록은 그대로다.

별도 판정자는 실행 전에 기존 원문·요약/QA 기준을 그대로 채택하고, 새 출력의 개별 의미 판정을 추가 정체 매핑·자체 검토·성능 공개보다 먼저 잠근다. 기존 자동 문맥에 노출된 정체·집계는 인계 기록에 남기며 완전 맹검을 주장하지 않는다. 전체 원문/선택 근거 지지·핵심 누락·자연스러운 한국어·질문 충족을 평가한다. 요약4/QA4 분모에서 구조 수용·review·의미 충족·실패·미실행·시간/자원을 나눠 보고한다. 문법 통과만으로 서비스 채택·Phase1 완료를 선언하지 않는다.

이 설계는 raw 응답·원문·질문·private criteria를 열지 않고 최종 안전 집계와 일반 코드만 사용했다. 새 학습·추가 원문·유료 API·클라우드·배포는 추가하지 않는다.
