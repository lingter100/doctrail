# 로컬 QA의 질문 전체 충족과 근거 선택 개입

2026-10-27 · 설계만 · 현재 source2 `9de904a8` / `f323dd3c` 읽기 전용 · v5 소비·원본 보존

**다음 후보는 QA 생성에만 고정 지침 `qa-coverage-plan-v1`을 추가한다.** 질문의 요구 항목에 답변 분량을 배분하고 각 주장 전체를 뒷받침할 근거를 선택하게 한다. 같은 모델·전체 원문·256토큰·60초 안에서 자연어 답변의 완전성과 근거 지지가 달라지는지 한 번 측정하는 개입이며, 효과는 아직 모른다.

[공개 v5 결과](../experiments/results/meetings-local-format-actual-v1.json)는 QA 형식4/4, 독립 내용 수용0/4다. 인용11/11은 정확하지만 선택 근거의 주장 전체 지지는 완전0·부분3·미지지1이고, 필수13요소는 충족1·부분7·누락4·오류1이다. 각 답변은 주장1개였다. 주장 수 자체가 실패 원인이라는 증거는 아니지만, 질문 전체를 빠짐없이 구성하는 지침을 시험할 근거는 된다.
현재 EOS 필수 경로에서 QA4개가 형식을 통과했고 출력한도 거부는0이었다. 출력이 잘려서 누락됐다는 근거는 없으며, 256토큰이 충분하다는 증거도 아니다. 부모와 설계자는 비공개 QA 문장·질문·원문·기준·개별 판정·패킷을 읽지 않는다.

| 대안 | 이번 판단 |
|---|---|
| 질문 요구별 구성 + 주장별 근거 선택 지침 | **선택.** 공개 집계의 누락4건·선택 근거 부족4건을 겨냥하는 QA 지침 하나다. |
| 질문 하위 항목을 새 JSON 필드로 출력·별도 분해 호출 | 보류. 출력 계약·호출 수·예산을 동시에 바꾸며 형식 통과만 늘릴 위험이 있다. |
| 인용 단위 확대·원문 발췌 나열 | 보류. C1에서 지적된 연속성 문제는 별도 가설이며, 넓은 정확 인용이나 발췌만으로 완전한 자연어 답변이 되지는 않는다. |
| 출력 상한 상향 | 보류. 필요한 토큰 수와60초 적합성이 불명이며, 근거 없는 추가 주장·정보 선택 오류를 해결한다는 증거가 없다. |
| 다른 무료 로컬 모델 | 보류. 생성 능력 비교는 가능하지만 현재 집계만으로 적합 후보·자원·우위를 선택할 수 없다. 이번에는 모델·다운로드를 바꾸지 않는다. |
| 같은 설정 재실행·추가 자기검토 | 선택하지 않는다. 새 가설이 없거나 호출·지연이 늘어난다. [C1 사후 문서](MEETINGS-C1-FAILURE-FOLLOWUP.md)의 해당 부분 실행도 자기검토의 완전 적합 개선을 보이지 못했으며, 이를 모든 방식의 무효로 일반화하지 않는다. |

기존 `ANSWER_PROMPT`에도 주장 전체 지지·원자적 사실·계획/완료 구분이 있다. 이 규칙이 없어서 실패했다고 단정하지 않는다. 새 요소는 **질문의 모든 요구를 먼저 배분하고, 답변 전체의 누락을 마지막에 점검하는 생성 지침**이다. 체크리스트·추론·자체 품질점수는 출력하지 않고 추가 호출도 하지 않는다.
추가 본문은 다음5줄을 LF로 연결하고 끝 LF 없이 고정한다. 예시·정답·문항별 문구는 넣지 않는다.
```text
Before emitting JSON, identify every explicit part of the question and the source qualifications needed to answer it; emit only the final answer, not this plan.
Cover every requested part with the existing 1-4 short factual claims as needed, following the question order. Do not collapse unrelated facts into one claim or repeat the same fact.
For each claim, select all and only the original evidence IDs needed to support every detail, including subject, state, time, scope and qualifications. Uncited surrounding text or another claim's citations cannot substitute.
Before finishing, check the whole answer for unanswered parts and unsupported details. Do not invent facts or drop necessary qualifications to fill a gap; keep the existing abstention rule.
The 256 generated-token budget covers the entire JSON, including evidence IDs. Keep the answer concise and complete; output no plan, reasoning, checklist, quotes or extra keys.
```

여러 요구를 짧게 담으려다 조건·예외·시점·주체를 지우거나, 관련 없는 근거를 많이 붙이는 위험이 있다. 기존 전체 질문 충족·자연스러움·각 주장 전체의 선택 근거 지지·abstain 기준을 그대로 적용한다. 주장 수 증가·인용 증가·짧음·abstain 자체는 개선 지표가 아니다. 기존 prompt의1–4 주장 지침과 parser/grammar의1–6 허용은 원래 차이이며 새 hard 제한을 만들지 않는다.

최소 구현은 summary-control의 독립 검토·수용 뒤 candidate/test 두 파일뿐이다. frozen `ANSWER_PROMPT`/parser/grammar·근거 단위/offset map·요약/mandatory review·런타임/정리 코드는 유지한다. QA 요청 builder에서만 system=`ANSWER_PROMPT + LF + instruction`, compact 변환 후 기존 `LF + COMPACT_LEGEND`를 정확히1회 붙인다. 원문·제목·질문·ID·순서·user payload는 전량 그대로다.
새 schema5는 수용된 schema4의 `summary_control`과 format/compact/resource/limits를 그대로 고정하고 `qa_control`만 추가한다. 정확 키는 `{policy,base_prompt_sha256,instruction_sha256,effective_system_sha256}`이며 위 고정 문구의 UTF-8 해시3종은 설계 영수증에 결속한다. 임의 prompt/환경변수/CLI override는 허용하지 않는다.
기존 순수 `registration_policy`와 외부 observer가 동일 바인딩을 해석하고, 잘못된 schema/키/타입/hash/조합은 native 전에 거부한다. 선택된 QA의 실제 system hash도 dispatch 전에 확인한다. schema1–4와 직접 호출 기본값은 기존 요청 그대로이며 report/terminal에는 새 선택과 hash를 기록한다. 기존 출력 메타데이터의 추가와 요청 바이트 보존은 구분한다.

후속 모델 없는 검사는 현재 소유자의 회귀 전체를 보존하면서 기존 generic mock으로 다음만 확인한다. 이번 설계에서 검사·새 품질 자료 작성은 하지 않는다.
- old/default 요청 동일, 새 QA에만 정확 지침1회·불변 policy·등록/실제 system 일치; 요약/review/QA grammar3종·원문과 질문 payload·ID map 불변.
- unknown/누락/추가 키·잘못된 hash·schema 혼합은 시작 전 실패;4096 입력 gate·256 출력·60초·EOS·strict parser·echo·내용 거부와 protocol/resource STOP·once/cleanup 경계 보존.
- generic 다중 질문 payload와 조건/예외 문자열을 손실 없이 전달하는지만 검사한다. mock 통과를 실제 모델의 질문 분해·근거 선택·내용 개선 증거로 부르지 않는다.

원문4·질문4·잠긴 기준·고정 순서·Ministral3 3B Q5_K_M·native b11429·greedy/template·ctx6144·compact wire와 문법은 동일하다. QA256/60초, 요약768+review128/공유120초, 최대 생성8/전체12회·요청4608토큰, 입력4096, 시작120/활성900/정리5/전체1025초, native RSS6GiB/시작여유8GiB/활성여유2GiB를 유지한다. 추가 지침의 토큰량은 아직 모르며 실제 입력 gate를 넘으면 축약·재시도하지 않는다.
요약 schema4의 코드 수용과 실제 내용 수용은 별개다. 요약 전용 v6 실제 실행·사후 보존·독립 판단을 먼저 끝내고 그 결과를 보존한 뒤 QA 코드 변경을 시작한다. v6를 동일 요약 정책의 비교 기준선으로 두며, 요약이 실패해도 성공이나 기본 서비스 채택으로 바꾸지 않는다. 요약 변경은 이 QA 설계의 성과에 합산하지 않는다. v5와 비교할 때 요약 정책이 달라졌다면 그 차이를 공개하고 전체 시간 차이를 QA 지침의 인과 효과로 해석하지 않는다.

부모가 계획 수용·공개 후 최소 구현·합성 회귀·독립 검토·정확 소스 CI, 새 schema5 등록/출력/companion과 사전 packet 결속을 거쳐 별도 실제1회를 배정한다. 같은4+4·요약 유효 초안당 review1회 일정을 유지하고, 새 QA 지침 후보만 하나 사용한다. 이번 문서는 구현·실행 승인이나 기존 once 재시작 지시가 아니다.
사전 평가는 기존 잠긴 항목별 기준으로 수용 수/고정QA4, 선택 근거의 전체 주장 지지, 같은 필수13요소의 충족·부분·누락·오류, 자연스러움·적절한 보류를 나누어 기록한다. 형식 통과·실패·미실행·지연도 별도다. 새 성공 임계값이나 유리한 항목 선별은 만들지 않는다.
[기존 packet 규칙](../data/evaluation/meetings-local-format-review-protocol-v1.json)에 따라 EOS/기존 parser 후 실제 저장된 모든 유효 답변(보류 포함)을 후속 outcome과 무관하게 독립 판정한다. 판정자는 추가 실행 정보·자체검토·매핑 전에 개별 판단을 잠그고, 원래 자동 문맥 노출을 밝혀 완전 맹검을 주장하지 않는다.
자원 fresh gate1회 거부면 CLI0, 통과면 공식CLI1회다. 내용 거부는 원본을 남기고 고정 일정으로, 프로토콜/바인딩/자원/시간/정리 실패는 기존 STOP으로 간다. 실행 중 지침/상한 변경·재생성·부분 JSON 수선·실패 후 재시도는 없다.
후속 수용이0/4로 유지되면 이 지침 계열의 미세변형 반복을 멈춘다. 부분 개선도 완료나 서비스 채택으로 부르지 않으며, 다음 판단은 잠긴 집계로 별도 결정한다. 같은 자료는 반복 노출된 개발 진단이므로 일반화·보호 평가·사람 검수의 증거가 아니다.

완료 목표는 여전히 충분하고 근거가 있는 자연어 요약·답변과 권한·갱신·UI다. 개발 내용 기준 충족 뒤에도 격리 평가, Java의 ACL 선필터와 현재 revision·인용 재검증, 실제 모델의 검색 문맥 QA, 취소/오류/복구, React 근거 이동·화면·사용자 검수가 남는다. 서비스 연결이나 배포가 끝났다고 선언하지 않는다.
근거는 위 공개 결과·[결과 해설](MEETINGS-LOCAL-FORMAT-RESULTS.md), 공개 C1 문서·계약과 일반 코드이며 receipt에 입력 해시를 기록한다. 과거 runbook의 오래된 자원 수치는 현재 조건으로 복사하지 않았다. 비공개 QA 및 보호 split·새 자료·모델/native/tokenizer/Java·자원 조회·테스트·Git 작업은0이다.
