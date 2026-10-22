# 근거를 연결한 회의 압축 요약 후보

2026-10-22. 새 제품 계약의 설계이며 구현·모델 실행 지시가 아니다. 목표는 회의의 핵심 내용과 그 조건·변경 관계를 사용자가 이해할 수 있는 요약이다. 기존 발췌/분류 정책과 소비된 실행은 그대로 보존한다.

## 판단 근거와 대안

- 허용된 표현력 진단 안전 집계는 `.local/meeting-summary-representation-diagnostic-v1/safe-aggregate.json`, 5,434B, SHA `371e376ea9196a041b15980fc3da9f3781c5e8d74cb6a6dda0065a5d053fcb64`다. 4개 whole unit 이하의 충분한 선택을 구성한 문서1, 확정 불가능0, 불확정3이다. 불확정은 불가능 증명도 품질 통과도 아니다.
- 앞선 동일-label coverage 비교 안전 집계 SHA `a2adfbaeec091bc36473e2e18901fe4e384799fe235b2133b7d103233dcb853f`에서는 근거지원4→4, 핵심 누락4→4, 충분0→0이었다. 인용의 진위와 핵심 요약의 충분성은 서로 다른 판단이다. 기존 원문·annotation·기대 의미·평가 결과를 수정하거나 재채점하지 않는다.

| 대안 | 추가 completion | 장점과 남는 한계 | 선택 |
| --- | --- | --- | --- |
| 현재 발췌 유지/4 whole unit 의미 선택 | 0 / 최대1 | 원문 동일성을 검증하기 쉽지만 여러 구절에 흩어진 관계를 담는 표현력이 불확실하다. | 기존 서비스 호환은 유지하고 선택 후보 구현은 보류한다. |
| 근거 묶음을 가진 압축문장 생성 | 최대1 | 한 문장에 여러 원문 관계를 보존할 수 있다. 문장과 인용의 일치 여부는 좌표 검사만으로 알 수 없다. | 기계 검사만으로 배포 수용하지 않는다. |
| 압축문장 생성 후 같은 로컬 모델 검토 | 최대2: 생성1+검토1 | 원문 전체를 다시 보고 주장별 지지와 핵심 누락을 거부할 기회를 둔다. 지연·입력 비용과 동일 모델의 공통 오류가 남는다. | 다음 개발 후보로 선택한다. 재생성0, repair0. |

이 선택은 제품 우선순위 판단이다. 4unit 방법이 불가능하다고 결론 내리지 않으며, 새 버전의 문장/근거 수를 과거 평가에 소급 적용하지 않는다. 이 후보도 충분성에 실패하면 요약 완성으로 수용하지 않는다.

## 명시적 후보와 출력 계약

- 기존 `--extraction-assembly`에 `grounded-summary-v1`만 추가하고 `analysis_policy=batch-v2`일 때만 허용한다. 기본값 `legacy`, `coverage-v1`, single/batch-v1/batch-v2의 기존 prompt/grammar/분류 결과 조립 동작은 바꾸지 않는다. 새 이름의 `v1`은 후보 첫 버전이며 아래 저장 계약은 `summary_version: 2`다. 알 수 없거나 호환되지 않는 조합은 native 시작 전에 거부한다.
- worker의 바깥 응답 `schema_version: 1`과 기존 metadata/items 필드는 유지한다. 새 analysis만 `summary_version: 2`, `summary_claims`를 추가한다. 이 두 필드가 없는 분석은 현재 발췌 계약 그대로 읽고 수정한다. 일부만 있거나 알 수 없는 버전은 거부하며 자동 구형 변환은 하지 않는다.
- `summary_claims`는 순서 있는 1–6개 `{id, text, citations}`다. `id`는 배열 위치와 같은 정수0부터 연속 부여한다. `text`는 공백만 아닌 단일 문단, 1–240 Unicode code point, 모든 문장 합계 최대1,200 code point다. 한국어 UI의 후보는 `response_language=ko`로 고정하고 고유명사와 인용은 원문을 유지한다. 기존 script-presence 검사를 재사용하더라도 정확한 언어/번역 보증으로 보지 않는다. 각 항목은 필요한 조건·시점·불확실성을 포함한 하나의 의미 주장이다. 문법적으로 한 문장인지와 명제의 원자성은 기계 검사의 보증 범위가 아니다.
- 주장마다 `citations` 1–4개, 전체 참조 최대24개를 둔다. 각 참조는 현재 문서의 `{quote,start_offset,end_offset}`이고, 해당 주장을 뒷받침하는 **근거 묶음 하나**를 이룬다. 한 인용문이 여러 주장을 지원할 수 있지만 같은 주장 안의 중복 좌표는 거부한다. 문서 ID/원문 revision은 회의 분석의 기존 외부 소속에서 가져오며 다른 문서 근거를 혼합하지 않는다.
- 호환용 `summary`는 주장 순서대로 `text`를 LF로 연결한 값, `summary_evidence`는 모든 인용을 좌표로 중복 제거한 뒤 원문 순서로 정렬한 값이다. Python과 Java 모두 이 투영의 정확한 일치를 검증한다. 독립 수정 가능한 세 개의 요약 표현을 만들지 않는다.
- 상한의 목적은 읽을 수 있는 짧은 회의 개요와 유한한 생성/검토 비용이다. 기존 Knowledge 답변의 최대6개 주장/주장당4근거 형태를 출발점으로 삼되, 회의의 필수 조건을 상한 때문에 지우지 않는다. 6개 항목이나 모든 유형을 억지로 채우지 않는다. 이 크기에서 충분한 요약이 항상 가능하거나 출력 토큰이 항상 맞는다는 보장은 없다.

## 전체 입력과 실제 호출 경로

- 새 `GroundedSummaryGenerator(ScopedBatchedAnalysisGenerator)`와 얇은 runtime만 둔다. 기존 설치 Qwen3.5-9B의 동일 artifact/revision, GPU28, context6144, greedy/nonthinking 설정과 native 인스턴스·outer lock을 공유한다. 새 모델/다운로드/서버/DB/스케줄러를 만들지 않는다. Knowledge `/answer` 호출로 별도90초를 얻지 않는다.
- 기존 `partitions`의 전체 unit/순서/원문 code-point 좌표를 검증한다. generation/review의 데이터는 모든 unit과 사이의 원문 gap으로 직렬화하며, 연결 결과가 `request.content`와 정확히 같아야 한다. 문서 제목도 신뢰할 수 없는 데이터로 표시한다. classification의 Purpose 정규화는 기존 분류 경로에만 남기고 요약 입력 원문은 새로 정규화하지 않는다.
- 모든 unit이 요약 근거 후보다. label0/metadata/잘못 분류된 unit을 숨기지 않으며 단어·위치·문구 규칙으로 후보를 제거하지 않는다. 빈/공백-only span은 입력에는 보존하고 인용 근거로는 거부한다. 생성 모델에는 label이나 기존 요약/기대 답/annotation을 정답처럼 넣지 않는다. 시스템 지시와 JSON 데이터 경계를 구분하고 원문 안 명령은 따르지 않도록 명시한다.
- 작업 순서는 전체 unit 구성 → 생성용 전체 prompt의 실제 template/token admission → 기존 batch-v2 분류 → 기존 metadata/items 투영·충돌 검사 → 요약 생성1 → 기계 검사 → 전체 원문+후보의 검토 prompt admission → 검토1 → 최종 조립/검사/응답이다. 앞 단계가 실패하면 뒤 completion은 실행하지 않는다. 분류의 batch8/출력128/입력4096/전체 unit 제한160은 그대로다.
- 새 생성은 `_prepare`와 `_complete(messages, same_deadline, 768, new_grammar)`, 검토는 같은 메서드의 출력128을 사용한다. 생성·검토 각각 실제 template 포함 입력4096 이하, EOS 필수다. 768/128은 각각의 최대 출력 토큰이며 새 호출 둘의 합계 최대896이다. 기존 분류 토큰/호출은 별도 합산한다. 선언된 글자 수가 실제 토큰 수를 대신하지 않는다.
- 생성 wire는 `{"status":"draft","claims":[{"evidence":[unit_id,...],"text":"..."},...]}` 또는 `{"status":"abstained","claims":[]}`다. 모델이 인용문이나 offset을 생성하지 않고, 검증된 unit ID를 전체 원문 span으로 해석한다. 범위/정수형/중복/개수, 비어 있지 않은 유효 Unicode text, 상한, 허용 key만 검사한다. ID 목록은 원문 순서여야 하며 주장 순서는 모델의 설명 순서를 보존한다. 인용의 quote는 Java 기존 span 한도12,000 code point도 충족해야 한다. 넘는 span을 자르거나 임의 부분문자열로 바꾸지 않는다.
- 검토 wire는 `{"claims":[[claim_id,"supported|unsupported|uncertain"],...],"coverage":"sufficient|insufficient|uncertain"}`의 실제 enum 값 중 하나를 쓰는 엄격한 객체다. 모든 candidate ID가 정확히 한 번, 원래 순서로 있어야 한다. 전부 supported이고 coverage가 sufficient일 때만 반환한다. 검토는 새 문장을 쓰거나 근거를 바꾸지 않는다. 잘못된/모호한 응답은 수리하지 않는다.
- 생성과 검토 지시는 의결/제안/확약, 현재/과거 상태, 조건·예외·변경·적용 시점·대상 범위, 해결되지 않은 충돌을 구분한다. 검토는 각 **주장 전체**가 그 주장에 연결된 근거만으로 지지되는지와 전체 원문 핵심의 누락을 별개로 판단한다. 해결되지 않은 충돌을 그대로 설명할 수는 있지만 임의의 첫 값/최신 날짜를 정답으로 고르지 않는다. 특정 개발 문구나 사례는 넣지 않는다.

## 시간·검토·실패의 의미

- 기존 service/watchdog/`MeetingRuntime._run`의 하나의120초 분석 deadline을 분류, template/tokenize, 생성, 검토, 조립, observer 기록까지 공유한다. 단계별 `begin_request`나 타이머 재시작은 금지한다. Java의 기존 최대120초 generation transport도 늘리지 않는다. worker 종료 직전과 응답/관측 후 deadline 검사를 유지한다.
- `_complete`는 EOS뿐 아니라 length 결과도 반환하므로 새 호출자가 length를 반드시 거부한다. request-local cache와 native setting/model identity 검증, 종료 시 cache 삭제를 재사용한다. template/tokenize 요청 수는 completion 수와 구분해 실제 기록한다. classification 도중 cache eviction이 생겨도 추가 completion/예산을 허용하지 않는다.
- 생성 전 전체 prompt admission은 가능한 조기 실패 검사다. 검토 prompt에는 실제 생성문이 추가되므로 생성 전에 그 정확한 크기를 알 수 없다. 검토에서4096 초과이면 생성이 끝났더라도 실패한다. 근거만 남겨 전체 원문을 빼거나 후보를 줄이는 우회는 없다. 120초 안에2회가 가능한지도 아직 측정하지 않았다.
- strict JSON/중복 key/추가 key/type/GBNF/EOS/span 불일치와 기존 metadata 충돌은 실패다. 생성 abstain은 고정 `generation_summary_insufficient`, 검토의 거부/불확정은 `generation_summary_review_rejected`로 구분한다. 둘은502 worker→503 Java의 좁은 allowlist에만 추가한다. 형식 오류·시간 초과·native 실패·cleanup 실패는 기존 분류를 유지한다. 사용자에게 raw 코드나 원문을 포함한 오류를 보여주지 않는다.
- 실패는 새 분석을 성공으로 저장하지 않고 기존 같은 revision의 AI 초안/사용자 수정본을 보존한다. 새 요청 실패와 보존된 분석의 ready 상태를 UI에서 구분한다. 자동 발췌 fallback, 재생성, 누락 검토를 success 처리하는 경로는 없다. 원문은 보관/검색 가능하며 사용자의 명시적 재시도와 실험의 once 제한은 별개다.
- 좌표 검사는 **인용의 존재/정확성**만 보장한다. 같은 모델의 supported/coverage 응답은 독립 entailment 증명이나 사실 보증이 아니다. 공유된 오해, 그럴듯한 잘못된 압축, 빠진 조건, 과도한 충분 판정이 남을 수 있다. 독립 의미 평가가 지원성·충분성을 각각 확인하기 전 품질 통과/사용자 검수로 기록하지 않는다.

## 기존 제품과의 호환

- Python `merge_analyses`는 summary를 인용문 연결로 덮어쓰므로 새 최종 조립에서 호출하지 않는다. `extraction_analysis`의 metadata/items 처리와 coverage의 검증/제목 투영을 얇게 재사용하되, 기존4인용 선택이나 empty-summary 실패를 거치지 않고 새 계약을 마지막에 붙인다. 분류 오류10/작업 확약3, 집단 담당/관계 경고는 별도 미해결 항목이다. 제목 접두어 개선은 이 후보에 묶지 않고 현재 coverage 투영을 유지한다.
- Java `MeetingAnalysis`에 정확한 v1/v2 분기와 주장별 span/파생 투영 검사를 추가한다. `MeetingService`는 AI v2를 저장하기 전에 worker 응답의 `summary_review={policy:"grounded-review-v1",status:"accepted"}`를 확인한다. 이 표시는 로컬 worker가 검토 단계를 완료했다는 계약이며 독립 검증 표시는 아니다. 사용자 PUT에는 이 필드를 받지 않고 분석 안에도 검증 배지를 저장하지 않는다. 실제 후보/검토 연결은 runtime 및 raw 관측에서 검증한다.
- 현재 JSON 저장 열(`analysis`, `ai_analysis`, `meeting_runs.analysis`, `meeting_edits`)을 사용해 DB migration 없이 두 버전을 보관한다. 새 후보는 명시적 실행/재분석에만 적용하고 기존 row를 일괄 재작성하지 않는다. 일반 편집 PUT은 현재 요약 계약 버전을 유지하며 v2를 필드 삭제로 v1처럼 저장하는 요청을 거부한다. 버전 전환은 기존 `AI 초안을 사용자 수정본으로 적용` 경로의 저장된 `ai_analysis`와 정확히 같은 payload에 한정한다. 원문 revision/분석 version CAS, session/ACL/소유자 재검증, 실행 중 수정 거부, 사용자 수정본 보존을 유지한다.
- React는 v1에 현재 발췌 화면/편집을 유지하고, v2는 주장별 text 바로 아래 각 근거 버튼을 둔다. 기존 `EvidenceButton`→`openEvidence`의 document ID+source revision+정확 offset 이동을 재사용한다. AI v2 제목은 `AI 요약 초안`, 수정본은 `수정한 요약`; 모델 검토를 `사실 검증 완료`로 표시하지 않는다. stale/삭제/권한 변경 때 기존 재조회·중립 오류·상태 무효화 규칙을 유지한다.
- v2 편집은 주장 text와 해당 근거 목록을 함께 수정하며 두 호환 투영은 자동 계산한다. 인용 추가/교체는 원문의 실제 위치를 선택해야 하고 반복 문자열의 첫 위치를 몰래 고르지 않는다. 기존 결정 연결의 code-point occurrence 선택 방식을 재사용한다. 근거 없는 주장/범위 밖 span은 저장 거부하며, 사람의 의미 판단은 `user_edited`로 구분한다. 삭제/추가/순서 변경 후 ID를 다시 매기되 AI 원본은 보존한다. 충돌 복구/읽기 전용 AI 초안도 같은 문장별 근거를 보여준다.
- 목록은 파생 `summary`를 계속 사용한다. Knowledge 검색은 현재 ACL을 먼저 적용한 전체 원문 chunks를 계속 사용하고 생성 요약을 새 근거 corpus로 넣지 않는다. metadata/items 필터, 작업/확정 결정/사용자 연결은 그대로다. 새 요약만으로 항목을 확정하거나 결정 링크를 자동 생성하지 않는다.

## 재사용 경계와 최소 구현 순서

1. **계약/adapter NEW2**: `src/doctrail/meeting_grounded_summary.py`, `tests/test_meeting_grounded_summary.py`. 새 prompt/grammar/계약/검토/얇은 조립을 이곳에 둔다. `meeting_answer_v2`/`KnowledgeService.validateAnswer`의 strict 구조·근거/좌표 검증 원리를 재사용하되, 현재 answer의0–9 chunk ID grammar, 질문용 abstention, thinking90초 경로는 호출하지 않는다. frozen77 및 coverage module bytes는 수정하지 않는다.
2. **Python 연결 기존8**: `meeting_service_rag.py`, 두 service launcher, `run_meeting_rag_acceptance.py`와 대응 test4. normal/observer 모두 같은 새 generator/runtime, enum/health/lifecycle에 후보·계약·두 prompt/grammar SHA·각 cap·review 보증 한계를 표시한다. 실제 선택과 health가 어긋나면 거부한다. 새 import 의존성을 code binding에 항상 포함하고 plan/registration/calibration gate의 유효 assembly 일치를 유지한다.
3. **Java 최소4**: `MeetingAnalysis.java`의 v2 검사, `MeetingService.java`의 AI review envelope 확인, `GenerationClient.java`의 새 고정 오류2개, NEW `MeetingGroundedSummaryTest.java`에서 저장/수정/실패/구형 호환 경계를 확인한다. 기존 transaction/ACL/DB 구조는 교체하지 않는다. 새 출력이 없는 초기 구형 empty analysis도 계속 유효하다.
4. **React 최소3**: `web/src/meetings.ts`의 구분 가능한 타입/오류 안내, `components/MeetingViews.tsx`의 v2 표시·편집·충돌 비교, NEW `web/tests/meeting-grounded-summary.spec.ts`. `useMeetings.save`는 analysis를 그대로 전송하고 CAS/복구를 이미 처리하므로 새 추상화나 별도 hook을 만들지 않는다. 정상 v2를 v1 payload로 몰래 저장해 근거 연결을 잃는 UI 경로도 금지한다.
5. 처음부터 위 전체를 구현 완료로 부르지 않는다. NEW2 독립 읽기 검토 후 작은 Java/React 계약 연결, Python 실제 선택 연결 순으로 합친다. 총 NEW4+기존13의 예상 경계이며 구현자는 필요한 추가 seam이 있으면 근거를 먼저 반환한다. 새 prepare/probe/audit 체계나 복제 실행기를 추가하지 않는다.

## 검사와 이후 실제 판단

- Generic synthetic 회귀는 전체 원문/gap/Unicode 보존, skip/metadata 포함, 여러 unit 지지, 반복 quote의 좌표, 문장·근거 상한, duplicate/unknown ID/key, 충돌, 미지원/불확정/불완전 검토, length/EOS, 검토 입력 초과, 단계 사이/최종 관측 deadline 초과, busy 때 이전 진단 재사용 금지, 오류 후 추가 completion0을 검사한다. 원문 속 명령은 데이터로 전달되는지 확인하되 mock 통과를 실제 injection 저항성으로 주장하지 않는다.
- 기존 single/v1/v2 prompt bytes/분류 payload와 answer90초를 보존하는 guard, normal/observer MRO, 요약 추가 completion 최대2회, policy/hash/binding 불일치 거부, 전체120 및 cleanup5/소유 PID/exit/seal의 기존 실패 gate를 검사한다. 요약 assembly 진단은 request 성공과 구분하고 stage별 실제 payload/응답/검토 결과/토큰/EOS/첫 실패를 기존 observer 경로에 남긴다. raw는 custodians만, 부모는 안전 집계만 읽는다.
- Java 회귀와 실제 Java+합성 transport 브라우저 회귀에서는 v1/v2 저장·재조회·사용자 수정·재분석 실패 보존, 주장별 모든 근거 이동, revision/ACL/삭제/409 복구, 새 오류 안내와 원문 전체 검색을 확인한다. 합성 accepted flag나 화면 정상 동작은 실제 생성/의미 검토 성공이 아니다.
- 독립 코드 읽기 검토 → 정확한 source commit의 CI → 새 후보/입력/실행 경로 binding → 부모의 별도 명시 once 배정 후에만 실제 개발 비교한다. 기존 실행/coverage 결과/4unit 진단을 덮어쓰거나 자동 재실행하지 않는다. 기존 입력을 재사용하더라도 새 후보 비교임을 명시하고 원본 bytes·기대 의미·판단 기준은 유지한다. 공식 closed cal/val/test와 신규 source 평가 절차는 바꾸지 않는다.
- 실제 비교는 분류의 완전성/오류, 생성 주장 지원성, 핵심 충분성, 동일 모델 검토의 잘못된 수용/거부, 전체 지연·입력 초과·실패·cleanup을 따로 보고한다. 새 요약이 좋아져도 분류10오류가 해결됐다고 합산하지 않는다. 독립 검토자는 새 요약을 고정된 원문 기준으로 먼저 판단·잠그고 그 전에는 모델 자기검토/진단을 보지 않는다. 뒤의 오류 비교에서도 자기검토 flag를 정답으로 쓰지 않는다.
- 전체 원문이4096 안에 들어가지 않거나120초 내 분류+생성+검토가 끝나지 않으면 해당 후보는 그 입력에서 지원되지 않는다. 이는 원문 보존/검색을 중단할 이유가 아니며 더 큰 문서를 위한 계층 처리나 자원 정책은 별도 후속 설계가 필요하다. 이번 결과를 맞추려고 cap/시간/자료/기준을 바꾸지 않는다. 충분성을 달성하지 못한 상태에서 목표를 몇 구절 표시로 축소하지 않는다.

읽은 근거: 위 안전 집계와 기존 설계, `meeting_qwen35._prepare/_complete`, `meeting_gguf._complete`, `meeting_contract.extraction_analysis`, `meeting_worker.merge_analyses/_run`, coverage/service/launcher 경로, `MeetingAnalysis`, `MeetingService`, `GenerationClient`, `KnowledgeService`, React `meetings`/`MeetingViews`/`useMeetings`, frozen77 경로 목록이다. 실제 원문·labels·질문·packet/private judgment/rawrun/heldout는 읽지 않았다. 설계자는 기존 노출을 유지하며 final judge에 참여하지 않는다. 이번 작업은 문서1개만 작성했고 구현/검사/모델/tokenizer/Java/browser/Git 실행0, 실제 사용자 검수/품질 수용0이다.
