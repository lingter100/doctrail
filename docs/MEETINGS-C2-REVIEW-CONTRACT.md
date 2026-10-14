# C2 비교 실행·자료 준비·독립 검토 계약

2026-10-14. 새 비교 코드의 계약이며 **실제 품질 질문·답변·점수는 아직 없다**. 합성 테스트의 8/8·12/12는 도구 동작을 확인하는 인위적 값이다. 실제 비교는 [사전 계획](MEETINGS-C2-COMPARISON-PLAN.md)을 따른다. C2-P0 자원2회와 과거 후보 결과를 다시 실행하지 않는다.

## 동일 조건과 정확한 prompt 차이

L0는 원래 `meeting_answer_spans.ANSWER_PROMPT`를 그대로 쓴다. C2는 그 문자열 뒤에 줄바꿈2개와 아래 문자열만 붙인다. 조건·언어·완전 답변·보류 지시는 동일하다.

```text
Evidence IDs here identify preserved paragraphs or structural blocks.
touches_context_start/end marks contact with a supplied context boundary; text may be
incomplete there. Neither an internal block boundary nor a larger block proves semantic
completeness. Do not invent text outside the supplied context.
```

사용자 payload는 질문·응답 언어·source 제목/회의일·단위 ID/text 구조가 같다. C2의 각 단위에는 원래 context의 시작/끝과 닿는지 나타내는 boolean 두 개가 추가된다. 이 표시와 단위 분할 때문에 직렬화 토큰 수가 달라진다. 질문·context 원문·순서·metadata는 같은 DTO를 쓰며 양쪽 호출 직전 payload hash를 다시 비교한다. 원문을 잘라 예산을 맞추거나 출력 이후 인용을 넓히지 않는다.

## 질문 작성 전후의 순서

1. 비교 runner, 입력 준비, review 계약·audit, 관련 합성 검사와 문서를 먼저 검증·commit한다. Registry는 이미 `8a424be`에서 질문보다 먼저 등록됐다.
2. 각 split 담당자는 등록된 공개 원문의 개별 이용 조건/NOTICE·본문 적합성을 확인하고 원본/처리본 hash와 처리 규칙을 먼저 남긴다. 새로운 질문/oracle를 작성하고 별도 AI가 사전 검토한다. Validation 담당자는 부모에게 본문·oracle를 보내지 않는다.
3. `prepare_meeting_blocks_inputs`는 모델 가중치를 열지 않고 고정된 공식 tokenizer만 로컬에서 사용한다. 두 역할의 원문 보존·catalog·grammar·입력 상한을 확인하고 `input.json`, `receipt.json`을 새 디렉터리에 쓴다. 실패한 원문을 자동 절단·요약·재작성하지 않는다. Validation의 이 준비는 격리 담당자만 수행한다.
4. 두 split의 최종 input/oracle·tokenizer metadata, source 목록, 원본 자원 영수증, 실제 runtime receipt, seed hash와 담당자/경로를 한 실행 계획에 봉인한다. 그 뒤 calibration16회만 실행한다. 한 번 시작한 출력 디렉터리는 성공/실패와 무관하게 재사용하지 않는다.
5. Calibration이 독립 판정을 포함해 선택 기준을 통과한 경우에만 validation12회로 진행한다. 검증 입력을 읽기 전에 선택 영수증의 전체 연결을 재생한다. 기본 서비스 채택은 별도 운영 검증 이후의 결정이다.

## 입력과 oracle

입력은 `schema_version:1`, `phase`, 순서 있는 `cases`로 구성한다. 각 case는 `id`, Java/worker와 같은 `payload`, `official_input_tokens:{L0,C2}`다. 준비 전 draft에는 마지막 token 필드가 없다.

Oracle의 실행 가능한 엄격 schema는 `doctrail.meeting_comparison_review.OracleFile`이다. 각 항목에 다음을 기록한다.

- ID·family ID·public/synthetic 구분·질문 언어·기대 상태.
- 필수 사실의 ID/text, 허용 근거의 OR 대안. 각 대안 안의 여러 exact span은 함께 필요한 AND 근거다. 위치는 원문 code point의 반열린 구간이다.
- 없는 필수 사실은 대안 배열을 비우고 보류 이유를 적는다. 근거가 없는 사실을 가짜 인용으로 채우지 않는다. 모든 필수 사실에 근거가 있으면 answered다.
- 금지 추론·한계·질문 작성자·oracle 작성자·별도 사전 검토자·실제 인간 검수 수.

Calibration 각 family는4항목/KO2·EN2/answered3·abstained1, validation은6항목/KO3·EN3/answered4·abstained2다. 실제 query의 응답 언어 판정과 oracle 표기가 같아야 한다. 답변 가능한 복수 필수 사실 항목은 최소4/6, 복수 source 필요 항목은 최소2/4다. 각 family에 복수 사실·복수 source·일부만 근거가 있는 보류가 적어도 하나씩 필요하다.

복수 source 필요란 **허용 대안의 어떤 충분한 조합을 골라도 서로 다른 `(document_id, revision)` 두 개 이상이 필요한 경우**다. 한 문서의 chunk 두 개를 합쳐 수를 채우지 않는다. 모든 사실에 대해 한 source만으로 충분한 대안의 교집합이 존재하면 복수 source 필수 항목이 아니다. 자동 검사는 이 표기와 위치의 일관성을 검사한다. 대안의 의미적 충분성은 별도 검토자의 판단이다.

## 실행 계획의 추가 필드

`probe_meeting_blocks_comparison`의 `FILES`와 `LIMITS`가 실행 가능한 source/예산 계약이다. 계획은 두 split 모두를 처음부터 포함한다. Runtime은 실제 weights/launcher 검증 receipt의 canonical JSON SHA256과 공식 tokenizer metadata로 식별한다. 완료된 자원 raw 파일의 경로·SHA도 고정한다.

각 `phases.calibration|validation`에는 `case_ids`, `input_file`, `input_sha256`, `oracle_file`, `oracle_sha256`, `output_dir`가 필요하다. 원문/oracle는 전역 shared source 목록에 넣지 않는다. 각 `audit.calibration|validation`에는 `seed_file`, `seed_sha256`, `reviewer_id`, `output_dir`가 필요하다. Seed는32~128bytes이며 hash를 호출 전 등록한다. 두 독립 scorer는 서로 다르고 모든 구현/설계/작성/사전검토 역할에서 제외한다. `excluded_reviewer_ids`를 등록한다.

경로는 저장소 안의 상대 경로이며 native 출력·audit 출력·seed는 `.local`에 둔다. 두 split의 입력/oracle/native 출력/seed/audit 출력은 서로 같거나 중첩할 수 없다. 실제로 해석한 경로도 검사해 symbolic link가 다른 split을 가리키는 경우 차단한다.

Audit 파일 이름은 고정한다: `review-input.json`, `mapping.json`, `receipt.json`, `bundle.json`, `judgments.json`, `judgments-lock.json`. Calibration 최종 선택은 해당 audit 디렉터리의 `selection.json`, validation 최종 결과는 `validation.json`이다. 임의 gate/artifact 경로를 먼저 읽은 뒤 거절하는 순서를 허용하지 않는다.

## 익명 판정과 수치

별도 scorer에게 `review-input.json`과 `JudgmentFile` schema만 전달한다. 입력에는 익명 sample ID·질문·전체 context·고정 oracle·반환 주장과 실제 선택 인용만 있다. 모델명·arm label·시간·원시 로그·역할 대응표·이전 판정은 없다. 질문 중복과 인용 길이로 역할을 추측할 수 있으므로 추측 여부/확신/이유도 기록한다. 완전한 맹검이나 인간 검수라고 부르지 않는다.

Scorer는 모든 주장을 최소 사실 단위로 나누고 **부가 예시·이유도 분모에 포함**한다. 각 사실의 지지 여부, 그 주장에 선택된 인용 안의 최소 지지 위치, 모든 주장-인용 연결의 관련성, 필수 사실별 포함 여부, 시간·대상·조건·언어 판단을 남긴다. 주장이 여러 인용을 함께 요구해도 허용하지만 선택하지 않은 이웃 문장을 대신 근거로 쓰지 않는다.

8개 품질 boolean과 전체 적합은 서로 일관돼야 한다. Citation exact·상태·주장별 사실 판정/필수 사실 판정의 집계는 코드가 대조한다. 의미 판정을 코드가 새로 생성하지 않는다. 전체 적합에는 모든 차원과 불필요한 인용 연결0이 필요하다. 올바른 보류의 빈 인용/사실 rate는 `null`(N/A)이며100%로 바꾸지 않는다. 오류 응답은 보류가 아니다.

인용 발생/고유/중복 길이, source 발생/고유 길이, 선택 근거의 source 비율, 최소 지지 위치의 고유 길이와 인용 폭 비율을 따로 남긴다. 고유 길이는 문서/revision별 좌표 합집합이다. 폭은 보조 계측이며 사후 합격 기준으로 쓰지 않는다.

`lock`은 review·judgments·receipt 세 파일만 읽어 판정 SHA를 독점 생성한다. 그 다음 custodian이 mapping을 열어 `finalize`한다. 이 순서는 역할 운영과 기록에 의존한다. 해시는 사람이/AI가 이전에 무엇을 보았는지를 암호학적으로 증명하지 않는다.

## 재생과 실행 예시

다음 경로는 **실제 질문이 준비되기 전의 예시**다. 등록된 최종 경로로 대체하며 이미 실행한 디렉터리를 재사용하지 않는다. 모든 모델 명령은 로컬 무료 실행이다.

```powershell
# Split 작성자: tokenizer만, 생성/다운로드0. Validation은 격리 담당자만.
uv run --locked --group retrieval --no-sync python -m scripts.prepare_meeting_blocks_inputs --phase calibration --draft .local/c2-cal-draft.json --output .local/c2-cal-input

# Calibration 실행 계획을 별도 commit한 후 한 번만 실행.
uv run --locked --group retrieval --no-sync python -m scripts.probe_meeting_blocks_comparison check --plan data/evaluation/meetings-c2-execution-plan-v1.json --phase calibration
uv run --locked --group retrieval --no-sync python -m scripts.probe_meeting_blocks_comparison run --plan data/evaluation/meetings-c2-execution-plan-v1.json --phase calibration

# 원본+oracle+seed에서 익명 pack. 실제 source와 원문 응답의 재생을 포함.
uv run --locked --no-sync python -m scripts.prepare_meeting_comparison_audit prepare --phase calibration --plan data/evaluation/meetings-c2-execution-plan-v1.json --report .local/c2-cal-native/report.json --oracle .local/c2-cal-oracle.json --seed .local/c2-cal.seed --output .local/c2-cal-audit

# 독립 scorer가 모든 판정을 마친 후 mapping을 열기 전에 실행.
uv run --locked --no-sync python -m scripts.prepare_meeting_comparison_audit lock --review .local/c2-cal-audit/review-input.json --judgments .local/c2-cal-audit/judgments.json --receipt .local/c2-cal-audit/receipt.json --output .local/c2-cal-audit/judgments-lock.json
uv run --locked --no-sync python -m scripts.prepare_meeting_comparison_audit finalize --plan data/evaluation/meetings-c2-execution-plan-v1.json --bundle .local/c2-cal-audit/bundle.json --judgments .local/c2-cal-audit/judgments.json --lock .local/c2-cal-audit/judgments-lock.json --output .local/c2-cal-audit/selection.json
```

검증 runner의 `--phase validation --gate <등록된 selection.json>`는 선택 gate를 먼저 재생한다. 검증 audit의 `prepare`/`finalize`에도 같은 `--gate`가 필요하다. 전체16결과·전체 독립 판정이 있어야 하며 C2 8/8·개선≥1·퇴보0만 선택된다. 둘 다8/8이면 미개선이다. 검증은 C2만12/12여야 한다.

원본 native content를 해당 동결 mapper로 다시 처리한 결과가 보고된 답변과 같은지 검사한다. 실제 native 설정/EOS/잘림/토큰/cache/model identity와 worker telemetry도 대조한다. Native `predicted_n`은 `tokens_predicted`와 같다고 가정하지 않는다. 기존 실제 runtime에 첫 token 계산 차이가 있으므로 각각 원본 값을 보존한다.

실제 timeout/OOM·새 모델 품질·Java/React 운영은 이 합성 코드 검사의 결과가 아니다. Phase1은 계속 미완료이며 PR14는 draft다.
