# 회의 핵심 의미 선택 요약 후보

부모 결정 — 2026-10-22: 이 설계는 **구현 보류**한다. 표현력 진단은 가능 근거1/확정 불가능0/불확정3이며 완전한 요약 가능성이 입증된 것은 아니다. 제품 목표에 직접 연결되는 근거 기반 압축문장 계약을 별도 설계한다. 이는4unit 방식의 불가능 증명이나 기존 평가 변경이 아니다. 아래는 보존된 제안이며 구현/실행 지시가 아니다. [진단](../experiments/results/meetings-summary-representation-diagnostic-v1.json).

2026-10-22. NEW 설계 문서1개다. 구현·tokenizer·모델·replay·서비스 실행을 배정하지 않는다. 목표는 핵심 관계를 보존하는 실제 AI 회의 요약이며, 네 구절 표시를 목표의 대체물로 삼지 않는다.

## 근거와 현재 한계

- 허용된 안전 집계 `meeting-extraction-coverage-comparison-v1/independent-review-v1/safe-result.json`은 9,154B, SHA `a2adfbaeec091bc36473e2e18901fe4e384799fe235b2133b7d103233dcb853f`다. 동일 저장 label의 후처리 비교에서 근거지원4→4, 핵심 누락4→4, 충분0→0이다. 주요 결정 노출은 늘었지만 조건·변경 관계·적용 시점·운영 범위는 여전히 빠졌다.
- 제목 누락2→0이나 접두어가 남은2건 때문에 고정 기대값 일치는2→2다. 분류 오류10건과 그중 작업 확약3건, 집단 담당/논의 관계 한계는 해결되지 않았다. 원래 annotation·판단·기준·분모는 그대로다.
- 현재 `assemble_coverage`의 유형 순환은 중요성이나 관계를 판단하지 않는다. `metadata_values`를 먼저 적용하고 heading을 나중에 벗기는 제목 경로는 heading 안 field-prefix가 그대로 남을 수 있다. 이는 generic 코드의 가능 경로이며 실제2건의 형식/trace를 읽어 원인을 확정한 것이 아니다.
- `MeetingAnalysis.java:16–33`은 schema와 literal source-span을 검증한다. 생성한 summary의 각 명제가 인용에서 따라오는지, 조건/시점이 빠졌는지는 검사하지 않는다. 현재 React 표시는 “AI 발췌 요약”이다.
- 기존 모든 실행/coverage-v1 비교는 보존한다. 디자이너는 안전 집계·generic 코드만 읽었고 실제 원문/질문/label/packet/private judgment/rawrun/held-out는 읽지 않았다. 이전 합성 인용 상수 노출과 최종 judge 제외를 유지한다.

## 대안과 선택

| 대안 | 추가 비용·장점 | 제약·판정 |
| --- | --- | --- |
| 기존 deterministic 발췌 유지 | 추가 completion0, 기존 운영/검증 재사용 | 기존 legacy 선택지로 보존한다. 관측된 핵심 충분성 실패를 해결한 것으로 수용하지 않는다. 위치/문구 규칙과 인용 cap을 늘려 다시 통과시키지 않는다. |
| AI가 전체 문맥에서 의미 연결을 보존할 원문 unit 선택 | 회의당 추가 completion 최대1, 출력128 이내의 ID만 생성. 현재 literal span·Java·UI 계약 재사용 | **다음 최소 후보로 선택.** 전역 문맥에서 중요한 관계를 고르는 모델 능력을 시험한다. 최대4 whole-unit의 표현력과 입력4096/전체120초는 여전히 한계다. |
| AI가 근거 붙은 압축문장 생성 | 생성 최소1회, ID 선택보다 긴 출력·명제별 인용 검증 필요. 여러 조건을 연결해 표현할 가능성 | 현재 flat summary/evidence는 명제별 연결이 없고 citation 존재만으로 entailment를 보장하지 못한다. 별도 검증 호출도 지연·동일 모델 오류를 더한다. 바로 기존 계약에 끼워 넣지 않되, 발췌의 구조적 한계가 확인되면 검토할 후속 제품 방향이다. |

새 명시 모드는 `extraction_assembly=semantic-extract-v1`, 분류는 기존 `analysis_policy=batch-v2` 그대로다. 기본legacy와 명시 coverage-v1의 bytes/행동, single/v1/v2 prompt·grammar·모델 정책을 보존한다. 새 요약 prompt/grammar SHA와 실제 선택 모드는 별도로 드러낸다.

## 표현력 사전 확인과 의미 지침

- 서로 독립적인 핵심 사실/조건이5개 이상의 unit에 흩어져 있고 한 unit이 둘을 함께 담지 못하면, 어떤 선택 모델도4 whole-unit으로 전부 보존할 수 없다. 대명사·선행 제안·수정 결론이 나뉜 경우에도 인용 개수보다 관계 보존이 우선이다. 연결된 문장을 모델이 새로 쓰지 않는 이 후보의 명확한 표현력 한계다.
- 부모가 별도로 배정한 기존 의미 검토자의 source-only 개발진단은 잠긴 핵심 기준에 대해 ≤4 whole-unit 충분 선택의 존재를 판단한다. 존재/불가능/불확정을 구분하고 구체 선택이나 정답 조건은 모델·디자이너·부모에게 주지 않는다. 이 문서 작성 시 반환 전이므로 실제4문서의 선택 가능성을 확정하지 않는다. 새 기준/후행 pass threshold를 만들지 않는다.
- 불가능이 확인된 대상에는 이 선택 후보를 성공 기대 실험으로 배정하지 않는다. 불확정은 가능의 증거가 아니다. 별도 명시 개발 실행을 하더라도 탐색 관측으로 기록하고 충분성 실패를 완료로 수용하지 않는다.
- selector에는 현재 회의의 핵심 목적/범위, 채택된 결과와 변경/대체 관계, 적용 조건·예외·시점, 실행 약속을 전체 문맥에서 파악하고 서로의 뜻을 바꾸지 않는 인용 묶음을 고르도록 지시한다. 유형별 quota·첫/마지막 문장 우대·특정 개발 문구/날짜/답변은 넣지 않는다.
- 제안과 채택, 과거와 현재, 질문과 뒤의 해소를 혼동하지 않고 필요한 전제와 한정을 함께 보존한다. 단독 인용이 다른 결론을 암시하거나4개로 핵심을 담을 수 없으면 `insufficient`를 선택한다. 모델의 자기판단도 의미 보증은 아니며 독립 충분성 검토가 필요하다.

## 전체 입력과 기존 호출기 재사용

1. frozen `partitions`와 원래 document content로 전체 unit ID/quote/offset을 만든다. 공백-only 분할 span도 보존한다. 새 formatter는 source의 gap과 unit을 순서대로 직렬화하고 각 unit에 positional ID를 표시한다. 모든 part의 text를 연결하면 **전체 request.content와 정확히 같아야** 한다. 원문은 한 번만 싣고 quote를 별도 중복 첨부하지 않는다.
2. selector의 선택 domain은 label5–9가 아닌 **전체 원래 unit ID**이고 문맥에는 모든 unit과 gap이 들어간다. 기존 분류 label로 후보를 거르거나 skip/metadata를 숨기지 않는다. oracle/expected marker/잠긴 선택/다른 문서/검색 결과를 주입하지 않는다. 질문 파일을 받지 않으며 원문 속 질문·명령도 비신뢰 데이터다. system 지침과 JSON data를 분리한다.
3. 분석 request의 기존 `_run`/outer lock 안에서 새 summary messages의 실제 nonthinking template/token 수를 먼저 확인한다. 전체 prompt가4096을 넘거나 native body 한도에 맞지 않으면 **이 문서의 generation 전에** 기존 input-limit 실패로 끝낸다. 일부 unit 삭제·창 이동·부분 요약을 재요약·원문 축약·더 작은 개발 문서 대체는 하지 않는다. 업로드/색인의 전체 원문 보존 계약도 바꾸지 않는다.
4. 기존 batch-v2 `classify_bounded`를 한 번 호출해 전체 item/metadata를 기존대로 구성·검증한다. 그다음 남아 있는 동일 deadline으로 semantic selection completion을 최대1회 호출한다. 분류 실패/metadata 충돌에는 selector를 호출하지 않는다. 생성 후 조립·진단 저장까지 같은120초 안이어야 한다.
5. NEW `SemanticSummaryGenerator(ScopedBatchedAnalysisGenerator)`에 얇은 `prepare_summary`/`select_summary_bounded`만 추가한다. 기존 `Qwen35Generator._prepare`와 `_complete(messages, deadline, 128, grammar)`는 실제 template·token·native identity/config·cache0 검사와 종료 사유를 제공한다. 새 selector가 반환된 `finish_reason == eos`를 반드시 확인한다. `generate_bounded`는 기존 answer grammar용이므로 요약에 사용하지 않는다. 새 weights/download/client/native 인스턴스는 만들지 않는다.
6. 사전 token 확인 뒤 분류가 request cache8을 밀어낼 수 있으므로 selector 직전 재-template/tokenize가 생길 수 있다. 이를 재시도나 무료 비용으로 숨기지 않고 실제 횟수를 기록한다. cache 확대/`cache_prompt=True`/별도 tokenizer를 추가하지 않는다. `_complete`는 현재 요청 cache가 있으면 재사용한다.

시간은 사전 형식화/토큰 확인+기존 분류+추가 prefill/최대128 decode+검증/관측의 합이다. 실제 지연과 충분한 잔여 시간이 아직 측정되지 않았으며120초에 맞는다고 주장하지 않는다. 새 request/begin_request를 만들거나 deadline을 갱신하지 않고 부족하면 timeout으로 끝낸다. native 분석 호출 수는 기존 분류 completion 수+최대1이며 답변90초·GPU28·startup120/active1500/cleanup5·전체1625초는 그대로다.

## 출력·근거·실패 계약

- native 출력은 정확히 `{"status":"selected","ids":[...]}` 또는 `{"status":"insufficient","ids":[]}`다. selected는 실제 ID 중1–4개의 서로 다른 정수이며 원문 순서여야 한다. free text·rationale·새 title/label·offset은 모델이 생성하지 않는다. 허용 ID를 열거한 compact GBNF, strict JSON/정확한 key·type·수·중복·순서 검사를 함께 쓴다.
- 범위/순서 오류를 정렬·중복 제거·재생성으로 고치지 않는다. 정상 반환의 finish_reason이 EOS가 아니면 기존 output-truncated 오류, schema/ID 오류는 기존 invalid-schema/evidence 오류다. native truncated 표시·128 초과·identity/config 불일치는 inherited 검증의 기존 실패 경로를 유지하며 raw 응답을 다시 해석해 완화하지 않는다. insufficient는 기존 `generation_unsupported_field`(502)와 별도 `summary_selection.status=insufficient` 진단으로 남기고 전체 분석을 실패시킨다. 해당 코드는 현재 Java 오류 계약에 포함돼 있다.
- 선택한 whole-unit의 원래 quote/offset을 그대로 `summary_evidence`로 쓰고, summary는 그 quote들의 newline 연결과 정확히 같아야 한다. 원문 일치·max4·Java summary12000 한도를 검사한다. 빈 quote는 unit 계약에서 거부하고, 공백-only span은 전체 입력에는 유지하되 모델이 요약으로 선택하면 invalid-evidence로 실패한다. 이 구조 검사는 단어/의미 기반 후보 제거가 아니다. 인용 내부를 자르거나 여러 unit을 하나의 거대 span으로 합쳐4개 제한을 우회하지 않는다.
- 모든 content item과 날짜/참석자/목적 및 그 근거는 기존 label/추출 규칙대로 보존한다. selector가 잘못된 item label을 고쳤다고 주장하지 않는다. 새 순수 assembler는 frozen `extraction_analysis`/`merge_analyses`를 재사용하되 summary ID는 모델 선택만 사용한다. coverage-v1 순환 선택을 선행 수용조건이나 fallback으로 호출하지 않는다.
- literal 인용도 전제를 빼면 독자를 오도할 수 있다. ID/문자열 검증은 core coverage·시간 관계·인과/entailment를 증명하지 않는다. 생성 압축문장을 택하게 될 후속 후보는 명제별 복수 근거 연결, 새 사실/조건 생략 검사와 독립 의미 판단이 필요하며 단순 citation 유무로 검증을 대체해서는 안 된다.
- timeout·native/검증/관측 오류 시 partial ready/legacy fallback/retry는0이다. 첫 원인과 이후 cleanup 오류, 미실행을 구분한다. assembly-only/selection 진단은 요청 성공이 아니며 최종 result/error·실제 exit·seal·소유 정리가 권위다. 기존 ACL/소유자 확인·revision/deletion·근거 접근 검사를 바꾸지 않는다.

## 제목은 같은 후보의 분리된 결정적 변경

- 새 후보에서만 **ATX heading1–6/유효한 닫는 marker 제거 → 기존 명시적 title-prefix 한 번 투영 → literal 값 검증** 순서를 사용한다. 원문 형식은 읽지 않았으며 generic heading 안의 field-label 합성만 다룬다. 기존 허용 prefix 이름/대소문자 규칙을 재사용하고 개발 자료별 별칭을 추가하지 않는다.
- model label1만 대상이다. prefix가 없으면 한 줄 literal 제목을 유지하며, 본문 중간의 콜론/“title” 단어를 지우거나 반복 stripping하지 않는다. 값은 원래 quote의 연속 부분·비어 있지 않음·200 codepoint 이내여야 한다. 원래 evidence, 반복 동일값의 모든 근거, 서로 다른 값의 충돌 실패는 그대로다.
- summary와 title을 별도 비교 축으로 기록한다. 같은 native selector의 개선으로 제목이 고쳐졌다고 하지 않고, 제목 정확값 일치가 summary 충분성 실패를 상쇄하지 않는다. 기존 coverage-v1 `_title`와 결과는 수정하지 않는다.

## 최소 파일 경계와 검사

- NEW `src/doctrail/meeting_summary_semantic.py` + NEW `tests/test_meeting_summary_semantic.py`: prompt/grammar/strict parser, 전체 source formatter, 위 generator와 얇은 runtime/순수 assembler, title 합성 투영을 둔다. frozen 코드와 기존 coverage module을 수정하지 않는다. 분류 loop/HTTP client/실행 플랫폼은 복제하지 않는다.
- 기존 service/test2: 새 assembly의 normal generator와 `ObservedAnalysisGenerator`를 앞에 둔 observer MRO를 명시 선택한다. 기존 batch-v2 분류 prompt/알고리즘과 shared native/lock/deadline을 재사용한다. 실제 health에는 assembly와 summary prompt/grammar SHA·4096/128/4 정책을 별도로 확인한다.
- 기존 worker/combined launcher와 각 test, acceptance driver/test에는 필요한 enum 전달·health/lifecycle·plan/registration/calibration gate의 exact-policy 일치와 새 module 필수 code binding만 추가한다. defaultlegacy, unknown/비호환 시작 전 거부, 기존 caller의 자동 승격 없음. shared enum으로 diff가 불필요한 파일은 바꾸지 않는다. 예상 최대 NEW2+기존8이며 Java/React/DB/schema 변경은 필요하지 않다.
- 기존 observer를 그대로 써 실제 summary prompt/ID mapping/native 응답·token/EOS/남은시간/선택 결과를 보존한다. summary completion은 분석 native 집계에 포함하되 `classification_units`와 구분한다. 원문/비밀값은 일반 로그에 내보내지 않으며 부모에게는 안전 metadata만 반환한다.
- generic 회귀는 전체 text roundtrip/Unicode·공백·분할 ID,4096 경계와 초과 전 generation0, 정확 ID/중복/순서/insufficient/EOS/출력cap, 원문 주입문, 최대4/summary 길이, item/metadata 보존, title heading+prefix/자연 콜론/빈 값/충돌을 다룬다. 원래 데이터나 정답을 복사하지 않는다.
- mock transport는 실제 호출 경로·분류 N+selector1 상한·normal/observer 동일 payload·deadline 갱신0·cache eviction 비용·관측 실패·busy 진단 격리를 검사한다. single/v1/v2·legacy/coverage-v1 고정 prompt bytes/SHA/동작을 보존하고 새 모드만 달라지는지 본다. 의미 지침이 payload에 있는 검사는 모델이 관계를 이해했다는 증거가 아니다.

## 이후 단계와 완료 경계

1. 부모가 설계를 확인한 뒤 최소 구현과 generic 회귀를 별도 배정한다. 독립 읽기 검토와 정확한 source commit의 기존 CI를 완료한다. 이 문서로 검사/모델/새 자료 실행을 시작하지 않는다.
2. source-only 표현력 진단의 집계와 입력/시간 한계를 검토한 뒤 부모가 새 후보의 **한 번의 개발 실행**을 명시 배정한다. 기존 실행기를 필요한 flag/binding만 연결해 재사용하며 새 prepare/probe/audit 체계를 만들지 않는다. 기존 code·harness·JAR/UI·원래 개발 입력·새 모드/CI를 정확히 결속한 NEW 경로를 쓴다. 소비된 run/비교/기준을 수정하거나 재발행하지 않는다.
3. 전체 Java→worker→native→React 경로와 기존 업로드/자동분석4건→질문6건 흐름을 검증할 경우 분석별 selector≤1, 질문별 answer≤1, 자동 재분석/retry0을 유지한다. 입력 admission도 이 실행 안에서 이루어지며 첫 실패 뒤 미실행을 남긴다. 별도 dispatch 없는 사전 model/tokenizer probe는 없다.
4. 기존 source-only lock/기대 의미를 유지한 독립 검토자가 새 summary의 근거와 **핵심 충분성**, title exact value, 새로운 item/분류 차이와 실행된 답변을 구분해 판단한다. 이 실행은 저장 label만 재조립한 이전 비교와 달리 새 native 관측이다. label이 달라지면 같은-label 인과 비교라고 하지 않는다. 판단 lock 전 성능 진단을 노출하지 않고 부모는 metadata만 읽는다.
5. 충분성을 충족하지 못하면 선택 후보는 미완료/실패다. 모델이 더 좋은4개를 못 골랐는지4개 표현 자체가 부족한지를 구분하되, 결과를 본 뒤 cap/기준/원문을 조정해 이 실행을 통과시키지 않는다. 현재 context에 전체 원문이 안 맞거나120초에 완결되지 않으면 해당 지원 범위 한계를 정직하게 기록한다.
6. 구조적 한계가 확인되면 목표를 영구히4구절로 축소하지 않는다. 다음 선택은 관계를 압축한 명제와 명제별 다중 근거를 표현하는 새 요약 계약, 필요한 의미 검증/자원 비용의 **별도 prospective 결정**이다. 이는 이 계획의 자동 후속 구현/예산 확대 승인이 아니며 과거 결과 재채점도 아니다. 실제 사용 가능한 요약이라는 전체 목표는 계속 남는다.
7. 새 후보의 합성 개발 통과도 fresh 실제 자료·정확한 서비스 수용·사용자 검수를 대신하지 않는다. 라이선스/provenance·전체 원문/indexing·ACL·revision/deletion·cal6→독립6/6 lock→val8·test 격리 조건은 유지하고 공식 closed 자료를 다시 실행하지 않는다.

근거: 위 안전 집계와 현재 `meeting_extraction_coverage.py:44–106`, `meeting_contract.py:114–148,245–309`, `meeting_analysis_batch.py:105–183`, `meeting_qwen35.py:54–84`, `meeting_gguf.py:201–271`, service/launcher/driver, Java `MeetingAnalysis`/`GenerationClient`, React summary 표시 계약 및 기존 설계다. 이번 작업은 문서1개 작성이며 실제 구현·검사·모델/tokenizer·Java/browser·Git0, 사용자 검수/최종 품질 수용0이다.
