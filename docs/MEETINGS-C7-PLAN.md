# C7: 자료 채택 전에 입력 크기를 확인하는 새 후보

2026-10-20. `meeting-answer-single-thinking-c7-v1`(`c7`)의 설계만 등록한다. [protocol](../data/evaluation/meetings-c7-protocol-v1.json)의 수치는 새 source·질문을 보기 전에 고정한다. 현재 소유권은 설계2뿐이며 구현·자료·역할 배정·tokenizer/native/테스트/Git 실행은0이다. 구현은 설계 커밋 뒤 별도 dispatch를 기다린다. 부모가 root 문서·CI·Git·내용 없는 family registry를 맡는다.

## 근거와 변경 범위

C6는 공식 offline 입력 수용성 관문에서 종료됐다. Cal 준비 통과는 양 split 통과 조건을 대신하지 않는다. Native0이므로 의미 품질·추론 지연·reader 효과를 판정할 결과는 없다. 종료 metadata의 안전한 필드와 SHA `0b1c83869b6ee3978a82a08e9be3b99c31b2accfb4aa921627aa57b2f37712ad`만 근거로 삼으며, C6·모든 옛 pool의 원문/질문/입력/receipt를 재사용하거나 구제하지 않는다.

C7은 입력 수용성 실패에 반응한 새 설계다. C6 held-out 평가와 무관하게 처음부터 고안된 설계라고 주장하지 않는다. 다만 아래 수치는 held-out token 길이에서 역산하지 않고, 동결된 formatter 구조와 별도로 택한 보수적 byte 예산에서 정한다. 두 split은 모두 fresh다. C6의 통과 calibration을 가져오지 않는다.

추론 정책·schema·block parser·64KiB reader·cached Qwen3.5-9B Q5_K_M·pinned build·GPU28 요청은 C6 그대로다. 후보 ID C7와 재사용 policy ID `meeting-answer-single-thinking-c4-v1`를 구분한다. 변경은 새 자료 채택 전 family 크기 검사와 item/offline 단계의 일치 검사뿐이다. Production API의 질문 상한이나 모델 설정을 바꾸지 않는다.

## Tokenizer 없이 가능한 source admission

동결 formatter `answer_messages_thinking`은 system 문구와 `safe_payload({query,response_language,sources})`를 담은 user 메시지2개를 만든다. Source row에는 document/revision/chunk/title/date/page/offset과 모든 block의 ID/text/edge flags가 들어간다. `safe_payload`는 compact JSON·UTF-8 문자와 `<`/`>` escape를 사용한다. 따라서 원문 길이만 세거나 metadata/catalog 비용을 빼지 않는다.

새 prepare의 순수 helper가 family의 **3문서에서 고정 처리기로 얻은 모든 전체 chunk**를 문서 ID, start/end offset, chunk ID의 고정 순서로 모은다. 원문·처리 결과·모든 chunk bytes와 metadata를 동결에 묶는다. 반복/overlap chunk도 출력에 존재하면 모두 센다. 동결 block parser의 whitespace block까지 포함한 catalog를 만들고, 실제 canonical source metadata를 사용한다. Empty query는 `answer_messages_thinking("", catalog, language)`의 크기 측정용 placeholder일 뿐이며 질문이나 유효 AnswerRequest가 아니다. KO/EN 두 rendering을 모두 검사한다. 토크나이저·chat template·HTTP를 호출하지 않는다.

`E(x) = len(safe_payload(x).encode("utf-8"))`로 정의한다. `M0`는 위 empty-query full-family 메시지 배열이다. 바깥 메시지 배열까지 다시 `safe_payload`로 직렬화하므로 role/key/punctuation, system 줄바꿈, user JSON의 nested escaping, source metadata, block ID·text·flags를 모두 센다. 이 값은 실제 chat prompt와 같지 않으며 일부 비용을 더 크게 센다.

| 고정 항목 | 상한/값 | 근거 |
| --- | ---: | --- |
| Engineering rendered envelope | 8192 bytes | 독립적으로 선택한 8KiB 수용 예산; token 환산값 아님 |
| 미래 질문의 직렬화 증분 reserve | 1024 bytes | 같은 catalog의 `E(Mq)-E(M0)` 상한 |
| Chat wrapper reserve | 512 bytes | tokenizer 없이 남기는 미검증 allowance; 실제 길이라고 주장하지 않음 |
| Full-family `E(M0)` | 6656 bytes | 8192−1024−512 |
| 질문 원문 UTF-8 | 512 bytes | item 작성 전 고정하는 평가 자료 제약; 기존 500-codepoint 검사도 유지 |
| 동결 system 문구 | 1720 UTF-8 bytes | 파일 literal의 직접 계산; SHA `b918ad67989cbaa5328974cc6e5c23b3c6a673df4699d5b1e9233f52cbd2f6d2` |

1720 bytes는 이미 `E(M0)` 안에 있다. 별도로 더하지 않는다. 나머지 4936 bytes는 빈 query, metadata/catalog/source와 바깥 직렬화 비용이 함께 공유하며 본문 전용 예산이 아니다. Reserve는 검증된 token/latency margin이 아니다. Token 수·추론 시간에 대한 보장은 하지 않는다.

다음 상한도 동시에 적용한다. 어느 하나라도 넘으면 **intact candidate family 전체를 채택 전에 거부**한다.

- Family당 정확히3문서: 날짜가 다른 회의2+일반 문서1. 처리된 전체 source text는 문서당2048 UTF-8 bytes, family 합계4096 bytes 이하.
- 기존 고정 처리 결과의 전체 chunk는 family 합계6개 이하, 각2048 bytes 이하, text bytes 합계4096 이하. Chunker 설정을 바꾸거나 전체 chunk 일부를 빼지 않는다.
- Catalog는 whitespace 포함24 block 이하. 각 block은 기존1024 codepoint와 새2048 UTF-8 bytes를 모두 만족한다. Block ID는 동결 parser가 생성하며 새 분할은 없다.
- `document_id`≤96 UTF-8 bytes, `chunk_id`≤128, `title`≤128. 원래 Context 타입/ID128-codepoint 검사도 유지한다. 임의 제목 축약이나 실패 후 ID 변경으로 구제하지 않는다. Canonical metadata 생성 규칙은 source 채택 전에 등록한다.
- Meeting date는 유효한 `YYYY-MM-DD`10 ASCII bytes, 일반 문서는 null. Revision1..999999, page null 또는1..999999, offsets0..999999, start<end 및 원래 codepoint 길이/좌표 일치를 유지한다. Extra prompt metadata는 허용하지 않는다.
- 실제 full-family schema의 compact UTF-8 bytes≤4096. 같은 `request_body(messages,schema)`를 기존 `json.dumps` 기본 옵션으로 직렬화한 empty-query request bytes에 질문 reserve4096을 더해32768 이하이어야 한다. 이 별도 wire 예산은 schema/enum/요청 설정/ASCII escaping을 포함한다. 4096=512×8은 두 JSON 계층의 질문 escape를 위한 보수적 allowance이며 item 단계에서 실제 wire bytes도 다시 검사한다. 모델의 기존512KiB request guard는 변경하지 않는다.

상한은 cal/val·KO/EN·공개/합성에 동일하다. UTF-8는 언어별 정보 밀도를 같게 만들지 않으며 한국어 자료에 더 엄격할 수 있다. 긴 문서나 복잡한 formatting을 대표하지 못하는 표본 선택 한계가 생긴다. 엄격한 규칙을 통과하는 공개·연관 family를 찾지 못하면 source adoption을 중단하고 미충족 상태를 보고한다. 상한 완화·합성으로 공개 quota 대체·짧은 task lookup으로 의미 난도 축소는 하지 않는다.

## 채택·질문·공식 offline 준비 순서

동결된 source-only helper는 지정 author/custodian이 prospective family에만 적용한다. 읽기·Git 증명·원문 이용 조건과 provenance를 먼저 확인하고, 기계적 수용 결과·원본 hashes·모든 산출량·거부 사유를 제한된 receipt에 남긴다. 후보 거부는 질문 작성 전이다. 상한을 맞추려고 원문을 자르거나 요약·rechunk·metadata 축약·부분 채택·질문별 context 재선택을 하지 않는다. 거부된 family bytes는 보존하고 같은 실험에서 변형해 재제출하지 않는다. 다른 새 family 탐색은 고정 규칙 아래 source 채택 작업이며 tokenizer 피드백을 받지 않는다.

기계 통과 후 독립 source reviewer가 의미적 연관성·일반문서/회의 구성·시점·조건·상태의 충분한 내용과 신선도를 검토한다. 작다는 이유만으로 적절한 평가 자료가 되지는 않는다. 실제 Java/Python 처리 parity와 source freeze/commit이 완료된 뒤에만 질문/oracle/context를 작성한다.

Item은 질문 UTF-8≤512, 기존 codepoint≤500, 동일 catalog에서 `0≤E(Mq)-E(M0)≤1024`, `E(Mq)+512≤8192`, actual request wire bytes≤32768을 모두 검사한다. Source/metadata는 source freeze와 정확히 같아야 한다. Item이 사용한 whole-chunk subset의 크기 검사도 수행하지만 full-family admission을 대신하지 않는다. Context 선택은 의미 근거에 따라 계수 전에 고정하며 크기 피드백에 따른 추가 제외는 없다. 조건 위반 item은 prereview에서 거부한다. Tokenizer 결과를 보고 수정·재선택하는 경로는 없다.

독립 item prereview·freeze/commit 뒤 공식 offline 준비는 split별 정확히1회다. NEW prepare 안의 작은 local count helper가 같은 cached tokenizer를1회 load하고, item별 **동일한 실제 prompt를 한 번 구성하고 한 번 encode**한다. `apply_chat_template(messages, tokenize=False, add_generation_prompt=True, enable_thinking=True)` 결과의 bytes/hash/token 수를 그 prompt 하나에서 얻는다. Frozen counter를 수정하거나 byte 측정용으로 두 번째 tokenization/template call을 하지 않는다. Frozen count와 동일 입력에 동일 prompt/hash가 나오는 합성 parity를 먼저 검사한다.

그 한 prompt에서 UTF-8 bytes≤8192, 실제 message content 합계 대비 chat wrapper 증분0..512, input tokens1..5120, 기존 preamble/identity 및 request bytes 조건을 확인한다. Wrapper allowance를 실제로 초과하거나 token 상한을 넘으면 준비를 닫는다. Empty-query 또는 full-family를 실제 tokenizer에 따로 넣지 않는다. 한 split의 실패면 C7 양 split 준비 조건이 성립하지 않으며 실행 plan/native를 만들지 않는다. 공식 준비 시작 이후 입력 수정·재계수·retry·추가 resource/profile/neutral 호출은0이다.

## 최소 구현과 불변 조건

설계 커밋 뒤 별도 구현 지시의 범위는 NEW8이다.

- `src/doctrail/meeting_c7_review.py`, `tests/test_meeting_c7_review.py`
- `scripts/prepare_meeting_c7_inputs.py`, `tests/test_prepare_meeting_c7_inputs.py`
- `scripts/probe_meeting_c7_quality.py`, `tests/test_probe_meeting_c7_quality.py`
- `scripts/audit_meeting_c7_quality.py`, `tests/test_audit_meeting_c7_quality.py`

C6는 ID·Literal·등록/출력 경로를 고정했으므로 새 data/root만 넣어 계속하지 않는다. 새 namespace의 계약·helper·합성 검사만 만들고 runtime/policy/adapter/launcher는 복사하거나 바꾸지 않는다. 새 source admission과 single-pass count helper는 prepare 내부에 둔다. 범용 평가 플랫폼·cache·profiling 도구·새 승인 파일은 만들지 않는다. 기존 pure primitive만 명시적 인자로 사용하고 C6/옛 closed orchestration·공식 비교를 호출하지 않는다.

64KiB reader는 inner/caller Snapshots·unchanged·GitProof·committed helper 모두 유지한다. Fresh read/hash/HEAD/committed bytes/path/reparse point/alias/negative imports/final checks와 consumer 순서를 보존한다. 새 cache·monkeypatch는0이다. Unexpected positive/unlisted path는 body read 전에 거부한다. Allowlisted 파일은 raw bytes를 읽어 SHA를 검사한 후 AST/semantic parse를 허용한다.

Toolchain/source-code freeze·commit·정확한 push/PR backend/web/java-service CI와 별도 receipt가 자료 역할 등록보다 먼저다. Freeze는 NEW8·static family registry·설계2·환경 lock·model manifest·같은 runtime 및 전체 dependency/tests·negative import 후보를 포함한다. Committed freeze bytes/HEAD를 먼저 증명하고 discovery한다. CI JSON의 bytes 일치는 외부 GitHub 진위 인증과 구분한다. 실제 role/judge/data는 나중의 execution plan binding이며 freeze를 소급 변경하지 않는다.

합성 검사는 source bounds/metadata/null/numeric/Unicode/escape/nested serialization, 전체 chunk 포함과 whitespace/overlap 계수, 빈 query source-only rendering, 실제 질문 reserve 초과, source drift, one-load/one-template/one-encode 계수, frozen prompt/hash parity, wrapper 초과, offline 단발 실패 보존을 다룬다. 기존 reader·deadline·새 positive prebody·role/ACL/분할·익명화·lock·final-save 회귀도 유지한다. 실제 tokenization·native·옛 공식 실행으로 검사하지 않는다.

## 의미·시간·격리 관문

일반문서/복수회의/혼합 근거, KO/EN 자연어 완전답변·정확 인용·적절한 보류를 유지한다. Cal source6/문항6, val source6/문항8이다. 각 split 공개 family1+합성 family1, family당 회의2+일반1이다. Cal은 KO3/EN3·답변4/보류2, val은 KO4/EN4·답변4/보류4다. 답변가능4개는 일반 단독≥1/복수회의≥1/혼합≥1/모든 충분한 대안이 복수문서 필요≥2/양방향 KO·EN 교차근거≥1씩, 필수사실3~6을 만족해야 한다. 보류는 family 전체에서 필수정보 부재를 확인한다. 질문과 oracle이 쉬워졌다는 이유로 통과 기준을 바꾸지 않는다.

Freshness는 C6를 포함한 모든 closed family/URL/revision/raw/normalized fingerprint metadata만 이용한다. 닫힌 본문/질문을 다시 열지 않는다. 전체 normalized duplicate 및 cross-family/split 긴 문단 중복 거부, 같은 family 반복의 item 전 독립 판단, validation의 cal fingerprint binding과 지정 source reviewer의 근접중복 검토를 유지한다. 과거 metadata coverage gaps를 공개한다.

Validation source size 검사는 source admission 단계의 지정 isolated author/reviewer/custodian이 수행한다. 이는 held-out item 실행 허가가 아니다. 부모·설계·구현자는 validation body·질문·oracle·per-item 길이·신선도 이유를 받지 않으며 public에는 안전한 count/hash/status만 보낸다. 실제 validation execution/audit는 원래 C7 cal6/6+운영 무결성 gate를 metadata/body 전에 replay한다. 양 split 역할·author/prereviewer를 분리하고 self-review를 금지한다.

Cached Qwen/build, GPU28 requested/실효unknown, FA AUTO/실효unknown, seed0/greedy/cache off/parallel1/batch512/ubatch128/fit off/log-disable을 유지한다. Input5120/context6144/output928/requested thinking512/final native-retokenized384, EOS only, 요청90초/cleanup5초/요청 시작부터 cleanup120초/phase1200초다. Thinking/final은 독립 native hardcap이 아니다. 첫 proof부터 callback/tokenization/native/final mapping·필수 persistence까지 같은90초이며 마지막 쓰기 뒤에도 검사한다. Blocking I/O hard preemption은 주장하지 않는다.

Cal≤6→원래6/6 조건부 val≤8, max14 generation, retry/warmup/repair/translation/self-review/fallback/config ladder0이다. 첫 structural/resource/무결성/저장 실패면 즉시 종료하고 최초 원인·부분/미실행·뒤 오류·원래 flags를 보존한다. 구조를 통과한 의미 실패는 phase 독립 판정 후 닫으며 재실행하지 않는다. 전송 예약/send attempt/parsed/archived response/계약 수용을 구분하고 wire 완료를 추측하지 않는다. Owned cleanup와 bounded discard emitted0/EOF/read·join 오류0, raw local evidence와 public safe metadata 분리, terminal exit/summary/receipt/replay 일치를 유지한다.

Final judge2명은 아직 배정하지 않았다. 실제 수락/model/effort/독립64byte seed/노출 attestation을 첫 출력 전에 등록한다. 부모·설계·구현·source/item 작성/검토·mapping-aware 실행/audit 담당은 제외한다. Pack에는 익명 질문/context/oracle와 immutable final answer/citations만 넣고 모델·시간·mapping·reasoning을 뺀다. 최종 judgment SHA lock 이전 mapping/집계/진단 reasoning 공개는 없다. Lock 뒤 진단으로 점수를 고치지 않는다. 원래 cal6/6, val8/8와 미지원 사실·부적절 보류·언어·운영 오류0만 통과다.

Static C7 family registry는 부모가 source 전에 만들고 toolchain에 묶는다. 후속 role/prior-fingerprint/source-admission/source-freeze/item-freeze/offline/judge/execution-plan artifact는 실제 순서대로 생성하며 지금 배정됐다고 표시하지 않는다. Accepted source admission receipt와 각 실제 item의 byte 검사 결과도 execution plan의 source/item/offline hash chain에 묶는다. Fresh 자료/후보 통과를 service adoption으로 자동 연결하지 않는다. Retrieval·ACL 선적용·revision/출처 접근·실서비스 지연/취소/복구·사용자 검수는 별도 완료 조건이다.

## 노출과 한계

기존 승인된 Astra xhigh `/root/free_qa_candidate_review`가 설계했다. 자동 metadata, 과거 공개 C2 case-ID 요약, C3/C4 집계/코드, host/GPU/reader scalar와 C5/C6 실패 집계 노출이 있다. C7 설계 시작 시 AGENTS의 STATUS 확인 과정에서 새 공개 STATUS에 포함된 **C6 validation aggregate min/max**가 도구 출력에 노출됐다. 부모에게 즉시 알렸으며 그 값을 재인용·역산·수치 선택에 사용하지 않는다. Per-item token/문항 ID/receipt·닫힌 원문·질문·oracle·입력·응답·reasoning은 열지 않았다. Pristine/blind 설계라고 부르지 않으며 final judge 제외를 유지한다.

8192/1024/512는 engineering choices이고 bytes≠tokens다. 실제 wrapper 길이·token 수와90초 통과는 아직 모른다. 크기 규칙은 언어 정보량·자료 대표성을 바꾸며 공개 coherent family 부족으로 source 단계에서 멈출 수 있다. C7 품질·reader 효력·Phase1 완성·서비스 배포는 아직 입증되지 않았다.
