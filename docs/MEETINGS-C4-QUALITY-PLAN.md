# C4 단일 사고 기반 근거 답변 — 새 품질 계획

2026-10-16. 후보 `meeting-answer-single-thinking-c4-v1`의 사전등록이다. 기존 실제 Astra xhigh 설계 역할의 검토를 반영했다. 새 품질 원문·질문·oracle·tokenizer·native 호출은 아직0이다. [자원 후속](MEETINGS-C4-COMPAT-RESULTS.md)은 통과했지만 품질이나 배포 완료를 뜻하지 않는다.

## 문제와 방법

이전 후보는 정확 인용이 있어도 필요한 정보를 빠뜨리거나 근거가 지원하지 않는 사실을 만들었다. 새 후보는 전체 근거를 한 번의 사고 호출에 유지하고, 질문의 요구·주체·시점·조건·예외·상태를 연결한 자연어 답변을 작성한다. 별도 계획 출력→재서술의 두 단계를 없앤다. 사고와 단계 수가 함께 바뀌므로 어느 하나의 효과만 입증하는 비교가 아니다. 닫힌 예전 질문을 다시 실행하지 않는다.

일반 문서, 복수 회의, 일반 문서와 회의의 결합 및 한영 교차언어를 모두 유지한다. 담당자/작업 조회나 인용문 나열로 일반 자연어 답변 완료를 대체하지 않는다. 일부 필수정보가 없으면 전체 보류하며 기술 실패를 근거 부족으로 바꾸지 않는다. 질문이 요구하지 않은 추가 조건을 만들어 보류하지 않고 날짜 순서만으로 변경·인과 관계를 추론하지 않는다.

## 고정된 입력·출력

기존 AnswerRequest와 명시적 `response_language: ko|en`을 입력으로 사용한다. 질문 문자만으로 언어를 다시 추정하지 않는다. 기존 `build_block_catalog`는 전체 문단·목록·표 단위를 원문/순서/metadata/code-point 좌표와 함께 유지한다. oversized block이나 context는 조용히 자르거나 요약하지 않는다. 문서 본문은 근거 자료이며 정책·도구 지시로 따르지 않도록 새 고정 prompt에 경계를 둔다. 기존 질문·예제는 재사용하지 않는다.

최종 모델 JSON은 `{status, claims:[{evidence_ids,text}]}`다. 각 text는 요청 언어의 자연어이며 선택한 evidence ID를 서버가 원문 quote·chunk·절대 offset으로 확장한다. 모델에 quote/offset을 재출력하게 하지 않는다. `grounded_answer_blocks`의 정확 인용·중복 ID·상태·언어 script 검사는 재사용하되 의미 지원·완전성·실제 언어 준수는 독립 판정한다.

native schema에는 object/array/string/enum, 실제 nonblank ID enum, claims≤6, evidence1..4, text minLength1만 사용한다. text maxLength2000은 host 검증에 남기고 큰 반복 수·pattern·조합 분기를 추가하지 않는다. 상태와 빈claims의 대응도 host가 검사한다. 답변을 상한에 맞추려고 잘라 성공시키지 않는다. 이 새 schema의 실제 바이너리 수용은 아직 미검증이며 첫 공식 calibration에서 실패하면 종료한다. 별도 native smoke는 추가하지 않는다.

## 새 adapter와 구현 경계

기존 `ThinkingGenerator`의 정상 validator는 합성 `marker:teal`만 허용하고 일반 `generate_bounded`를 거절한다. 품질에 `stress=True`를 쓰거나 monkeypatch해서 우회하지 않는다. 새 quality adapter가 동일 SETTINGS/request body/identity/template/HTTP/tokenization primitives와 compat launcher를 재사용한다. 공통 native config/cache/token/종료/framing/split guard는 그대로 검증하고 합성 표식 부분만 새 schema/grounding 검사로 교체한다. 공통 guard의 동등성을 합성 테스트로 확인한다.

새 파일은 policy, quality adapter, review contract, offline preparation, probe, audit의6개와 대응 합성 테스트다. 정확한 경로는 [protocol](../data/evaluation/meetings-c4-quality-protocol-v1.json)에 등록했다. 기존 C3 family ID로 C4를 위장해 검사를 통과시키지 않는다. 새 launcher·평가 플랫폼·서비스 기본값 변경도 하지 않는다.

후보 코드만 완료됐다고 자료 작성을 시작하지 않는다. 실행·채점·익명화·동결·경로 검사까지 전체 의존 closure, prompt/schema/metadata를 고정하고 커밋·필수 CI를 마친 뒤 source-first 자료 준비로 넘어간다. 기존52와 모든 이전 동결 자료는 불변이다.

## 새 자료와 격리

[family registry](../data/evaluation/meetings-c4-family-registry-v1.json)는 내용 없는 구성만 등록한다. Cal6은KO3/EN3·answered4/abstained2, val8은KO4/EN4·answered4/abstained4다. 각 split은 서로 다른 새 공개 계열1개와 새 합성 조직1개이며 family마다 다른 날짜의 회의2개+관련 일반 문서1개, 전체 최대12문서다. 공개 출처와 이용 조건은 source 단계에서 확인하고 실제/합성을 분리한다.

각 split의 답변가능4개는 일반 문서 단독·복수 회의·문서+회의를 포함한다. 필수 복수 문서는 최소2건이며 어느 충분한 근거 대안이라도 단일 문서로 해결되면 해당 기준에 세지 않는다. 필수 사실3~6개, 양방향 교차언어 각각 최소1건이다. 보류는 알려진 요구와 없는 필수정보를 함께 포함하며 정보 부재를 family 전체 원문에서 별도 검토한다. 답이 있는 청크를 빼서 보류를 만들지 않는다.

1. source 이용 조건/revision/처리 규칙 → 새 원문 채택/작성 → 별도 coherence 검토 → 실제 Java/Python 전체 청크/좌표 parity → source freeze/commit.
2. 그 뒤 새 질문/oracle/전체 context 선택 → 독립 item prereview → item freeze/commit.
3. 그 뒤 각 split 공식 offline 계수1회. 상한 초과면 원문·context를 자르거나 교체하지 않고 준비 실패를 보존한다.

과거 family/URL/revision/hash metadata를 제외하고 새 원문 간 정규화 중복·공통 긴 블록 및 split별 의미 유사성을 검토한다. 과거 본문을 dedup 목적으로 열지 않는다. 사용할 수 없는 과거 fingerprint는 한계로 기록하며 근접중복0 입증으로 표현하지 않는다. 기존 질문의 번역·재서술·ID 변경도 새 자료로 세지 않는다.

## 판정과 노출 기록

각 split의 작성자와 사전검토자를 분리한다. Validation 본문/oracle/의미 설명은 지정된 custodian만 열고 부모는 hash/count/일반 범주만 읽는다. 부모·설계자·구현자·source/item 작성/검토자·mapping을 아는 실행/audit 담당은 최종 독립 judge가 될 수 없다.

첫 품질 출력 전에 서로 다른 최종 judge2명을 예약하고 실제 모델/effort를 기록한다. Pack 열람 전에 역할 참여, mapping/raw/reasoning/이전 judgment 노출, 자동 AGENTS 포함 모델/가설/이전 결과 metadata 노출을 attestation에 기록한다. 모델 정보를 본 경우 완전 맹검이라 부르지 않는다.

Pack에는 익명 sample ID, 질문, 언어, context, oracle, 최종 claims/citations만 제공한다. Reasoning/native trace/시간/모델명/원래ID/mapping은 제외한다. 모든 필수 사실·추가 사실·인용 관련성·주체/시점/조건/상태/언어·보류를 판정하고 최종 judgment SHA를 잠근다. Reasoning으로 최종 답변 점수를 바꾸지 않는다.

이번 설계 역할은 `MEETINGS-C3-PLAN`의 공개 C2 ID별 실패 요약과 기존 집계에 노출됐다고 보고했다. 격리 source/question/oracle/validation/test 본문을 열었다는 기록은 아니며, 새 예제/질문으로 재사용하지 않는다. 설계 역할의 judge 제외와 이 노출을 registry에 남겼다. 사용자 검수는0이다.

## 실행 한도·선택 조건

전체928/요청사고512/최종JSON재토큰384/입력5120/context6144/요청90초/정리5초/마지막 요청부터정리120초/phase1200초를 유지한다. 512와384는 독립 native hardcap이 아니다. 품질은 EOS만 허용하며 부하 final414/length 종료를 품질 수용으로 가져오지 않는다.88초 관측을 이유로 시간을 늘리거나 예산 사다리를 시험하지 않는다.

Cal≤6, 조건부 val≤8, 새 품질≤14native다. retry/warmup/repair/번역/자기검토/fallback/추가resource는0이다. 첫 structural/native/timeout/language-guard/citation/config 오류에서 해당 phase를 종료하고 미실행분과 부분 결과를 보존한다. 실행 계약을 통과했지만 의미가 틀린 경우에는 등록된 phase 전체를 모아 독립 판정한다. 어느 경우도 같은 pool을 다시 호출하지 않는다.

원본cal6/6 및 운영 무결성을 replay해야 validation body 개방·실행이 가능하다. Validation8/8, 미지원 사실/부적절 보류/언어/운영 오류0을 요구하며 자동 채택하지 않는다. 원래 C4와 compat까지 누적 최대18dispatch/17완성이다.

metadata preflight는 semantic body를 읽기 전에 code freeze/plan/경로/judge attestation/seed를 확인한다. 각 요청의 semantic parse 전과 native dispatch 직전에도 다시 확인한다. Validation은 그보다 먼저 원본cal gate를 replay한다. 요청·응답은 원본 artifact에 연결하고 본문·reasoning·token은 운영 로그에 출력하지 않는다. Compat drain의 emitted0/EOF/error0 조건도 유지한다.

이 작은 고정-context 검사는 검색 품질·Java 전체 지연·일반화·사용자 만족을 증명하지 않는다. 통과 뒤 실제 Java/React 권한·revision·실패/취소·출처 열기 검증도 별도로 필요하다. 유료 사용·공개서비스 배포0이며 전체 goal과 Phase1은 아직 미완료다.
