# C3 단일 후보 실행·준비·검토 계약 설계

2026-10-14 · `c2_budget_followup`, 부모가 확인한 실제 Astra xhigh. 설계만 작성한다. 실행 기준은 `docs/MEETINGS-C3-PLAN.md`와 이미 등록한 `meetings-c3-family-registry-v1.json`이다. 새로운 registry나 후보를 추가하지 않는다. 상태 문서, C3 새 모듈2개, registry 메타데이터, 기존 준비/실행/audit 및 review 계산 코드만 읽었다. Held-out 본문/oracle/review·과거 품질 pool 접근, 모델/tokenizer/네트워크/Git/검사 실행은0이다.

부모의 후속 확인: candidate commit `f67beb3`, `data/evaluation/meetings-c3-candidate-source-freeze-v1.json`의28bindings/SHA `6ce55cb17d264f8da7c587c685947da8d95ff1199ef65f7f34de7d1a275798c6`, Python1943passed/6skip·Ruff통과다. 이 freeze는 `execution/review tooling=false`, `data authoring eligible=false` 상태다. **새 toolchain freeze에 이 manifest 자체와 원래28binding을 그대로 연결하고** 새 도구/검사만 추가한다. 원래 freeze의 상태나 hash는 바꾸지 않는다.

## 최소 파일 경계

추가할 구현은 다음4파일과 각 대응 검사4파일로 한정한다. 기존 C2 8/12·두-arm source/contract와 C3 후보 모듈은 이 도구 작업에서 수정하지 않는다. 한 도구에서 다른 도구를 subprocess로 실행하지 말고 명시적 함수 호출로 연결한다.

| 새 파일 | 인터페이스/책임 |
|---|---|
| `scripts/prepare_meeting_requirements_inputs.py` | `prepare --phase calibration|validation --draft --oracle --source-freeze --item-freeze --code-freeze --output`: source/item hash·전체 payload·C3 oracle 구성 확인, **1단계만** 공식 offline count, 새 input/receipt 생성. |
| `scripts/probe_meeting_requirements.py` | `register-neutral`, `check`, `run-neutral`, `run --phase ... [--gate ...]`: C3 전용 plan/limits, 중립4와 단일 후보6/8 실행, stage별 recorder·중단·소유 process 정리. Neutral/quality 경로는 별도 함수로 구현한다. |
| `scripts/audit_meeting_requirements.py` | `prepare`, `lock-answers`, `reveal-plan`, `finalize`: 모델 없는 원본 재생, 최종 답변만 익명 pack, 답변 잠금 이후 계획 pack, 두 판정 연결/단일 후보 gate. |
| `src/doctrail/meeting_requirements_review.py` | C3 oracle/composition, 기존과 동일한 답변 점수 계산, 노출 attestation 및 잠금 후 plan 진단 schema. |

새 source freeze는 위 파일·검사, C3 모듈2/검사2, C3 plan/registry와 실제로 호출되는 frozen parser/prompt/mapper/native/tokenizer/처리 helper의 **정확한 경로 집합과 SHA**를 바인딩한다. 임의 추가/누락 파일도 거절한다. 기존 source freeze를 소급 확장하지 않는다. 실행 plan 자체나 아직 없는 결과를 코드 목록에 넣어 순환 hash를 만들지 않는다. 코드·자료·실행 산출물 binding을 구분한다.

**재사용 경계:** bounded snapshot/path 검증, `count_prompt/load_tokenizer(False)`, frozen C2 catalog, C3 `requirement_messages/parse_requirement_plan/realization_messages/grounded_requirement_answer`, native 응답의 공통 검증, `JudgmentFile`, `exact`, `union_length` 등을 명시적으로 import할 수 있다. 기존 `validate_oracles/summarize/check_model_metadata`와 원래 C2 plan/arm-count guard는 C3용으로 직접 호출하지 않는다. 기존 `score_sample`도 내부 `Oracle`가 `C2-F01..04` literal에 묶여 있으므로 C3를 그대로 받지 못한다. C3 review 모듈에 같은 필드의 `C3Oracle`와 **변경 없는 계산 규칙의 짧은 score 함수**를 둔다. 기존 family를 가짜 C2 family로 치환하지 않는다. 합성 parity 검사로 양 함수의 수치/오류가 동일함을 확인한다.

## 자료를 만들기 전 고정할 순서

1. 현재 candidate4파일 검증을 마치고, 이 실행 도구·검토 schema·합성 검사까지 검증/commit하여 새 전체 코드 freeze를 먼저 만든다. Registry는 이미 존재하므로 다시 등록하지 않는다.
2. Split별 작성자가 해당 registry의 고정 source만 채택한다. 개별 이용 조건/NOTICE, raw/processed bytes·Git blob, 문서/revision/좌표·처리 규칙, 실제 Java/Python whole-document chunk parity를 기존 도구로 확인한다. 합성 원문은 새 조직·새 사실이며 후보 출력이나 닫힌 자료의 숫자/이름 치환이 아니다. Source를 별도 역할이 검토하고 source freeze를 commit한 뒤 문항을 만든다. Metadata의 HOLD를 임의로 수락으로 바꾸지 않는다.
3. Calibration6/validation8 질문·요구 언어·전체 chunk 선택·oracle를 작성한다. 별도 item prereviewer가 답변 가능성·필수 사실/조건/대상/시점·인용 충분성·부분 정보 누락을 확인한다. Source와 질문 작성/AI 자기검토, 다른 역할의 사전검토, 인간0를 각각 기록한다. 거절 초안은 보존하고 수정은 새 파일로 한다.
4. Item freeze가 draft/oracle/context selection/prereview 및 source/code freeze를 묶은 뒤 commit한다. **그 뒤에만** split 담당자가 공식1단계 tokenizer 준비를 수행한다. Validation은 custodian만 body를 읽고 부모에게 hash/count/일반 범주만 전달한다. 토큰 피드백 뒤 context·질문·근거를 교체/절단하지 않는다.
5. 양 split 준비 완료 → 새 neutral plan commit → neutral4 단발 실행 → 통과한 실제 report를 바인딩한 **한 quality plan에 두 split/두 judge/seed/output을 함께 봉인** → calibration6 → 독립 판정·잠금/진단·선택 → 통과한 경우만 validation8. Neutral 실패 시 품질 호출0이다.

Source 최대8문서, C3-F01/F02 calibration 각3, F03/F04 validation 각4의 구성은 기존 registry를 그대로 따른다. Calibration KO3/EN3·answered4/abstained2, validation KO4/EN4·answered4/abstained4, 가족/언어별 보류 배정, answered의 required fact3~6, split별 필수 복수 문서≥2, 양방향 교차언어≥1씩을 검증한다. 복수 문서는 `(document_id, revision)`로 센다. 충분한 모든 대안 조합 중 한 문서만으로 충분한 경우는 필수 복수 문서가 아니다. 보류는 최소한 알려진 요구1개와 없는 필수 요구1개가 있고, 없음은 전체 채택 가족 원문에서 별도 의미 검토한다. 자동 hash/좌표 검사를 의미 검토로 대체하지 않는다.

## 준비 input과 oracle의 형태

Draft는 `{schema_version:1, phase, cases:[{id, response_language, payload}]}`다. `payload`는 기존 `AnswerRequest` 그대로이며 language는 새 실험 envelope의 `ko|en` 필드다. 이를 `RequirementsRuntime.answer(request, language=...)`에 명시적으로 전달한다. Oracle의 언어와 같아야 하며 질문의 script로 재추정해 덮어쓰지 않는다. 원래 DTO 생략필드/null/원문/metadata/순서·좌표가 모두 보존되는지 `exclude_unset`와 raw payload의 canonical hash를 대조한다.

Prepared case는 payload를 그대로 두고 `official_stage1_tokens` 정수만 추가한다. Receipt에는 draft/input/item/source/code freeze/oracle SHA, tokenizer asset/runtime version, ID별 payload·language·stage1 prompt/grammar hash·unit count·공식 count, 원문 보존, errors/측정/미측정 수, generation/download/native0를 기록한다. Input/receipt가 둘 다 완성돼야 준비 통과다. 비어 있지 않은 context, catalog/grammar 제한과 stage1 count1..5120을 전부 만족해야 한다. 전체6/8을 조사하되 오류 항목을 숨기거나 분모에서 빼지 않는다.

C3Oracle는 기존 oracle의 required facts와 OR-of-AND exact evidence alternatives·forbidden inference·한계·작성/사전검토 역할을 유지하며 family literal만 C3로 정의한다. Answered의 모든 필수 사실에는 충분한 근거 대안이 있고, abstained에는 없는 필수 사실의 빈 대안이 있어야 한다. 질문 텍스트의 자연어 요구와 oracle가 맞는지는 item prereview 책임이다. 런타임은 oracle를 입력으로 받지 않는다.

**Stage2는 미리 준비된 count가 아니다.** 준비 receipt에는 `stage2_readiness=dynamic_unmeasured`를 명시한다. 생성된 실제 plan에서 `realization_messages`를 만든 직후 native tokenizer로 세고 dispatch 전에1..5120을 검사한다. 초과하면 오류·stage2 native0이며 plan/context를 줄여 재시도하지 않는다. All-missing/uncertain 분기는 stage2가 `not_required`인 것이지 stage2 count0 통과가 아니다.

## Neutral4와 quality 실행 계약

공통 후보는 `meeting-answer-requirement-plan-c3-v1`; 고정모델/runtime/context6144/24layers/batch512/ubatch128/fit off/greedy seed0/nonthinking/cache0을 재확인한다. 단계별 input5120/output384, 요청별 총 output768/최대2dispatch, **준비→stage1→plan parse→stage2 준비→stage2→답변 검증→adapter cleanup에 한90초**다. 종료 확인5초와 요청 시작~소유 process 정리120초, 전체 phase2400초의 별도 상한을 둔다. Startup/metadata restart는 요청 시간과 별도 계측하되 phase 상한 안에 있다. 다른 활성 모델 job/lease가 있으면 실행을 시작하지 않는다.

Neutral plan의 정상 요청은 새 합성 DTO·toy 예상 사실/언어·stage1 prompt/grammar/공식 count와 **동결된 결정적 stage2 builder**를 생성 전에 바인딩한다. 정상 stage2의 실제 prompt/grammar/count는 실제 stage1 plan에 의존하므로 미리 값이 정해졌거나 계수됐다고 하지 않는다. 실제 stage1 뒤 생성하여 기록하고 dispatch 직전 동적으로 검사하며, audit에서 같은 stage1 raw와 동결 builder로 재생한다. 정상 요청은 C3 실제 두 단계가 모두 실행되고 정상 EOS·원문 인용·toy 예상 사실/언어가 맞아야 한다. Stage1이 보류하면 native1로 종료하고 neutral 실패, 다른 fixture로 다시 시도하지 않는다. 부하는 양 stage의 prompt/grammar/공식 count를 생성 전에 모두 바인딩하며 각 stage 공식 input4992..5120과 output384/length를 목표로 사전 고정한다. Stress stage2는 따로 고정된 합성 plan/입력으로 **정상 stage1 출력에 종속되지 않는 resource 전용 부하**임을 명시한다. 한90초 기한에서 stress stage1→stage2를 연속 실행한다. Normal2+stress2=최대4; 품질 성공으로 해석하지 않는다. 특정 길이 fixture를 만들지 못하면 native0에서 닫는다. 특수 grammar/강제 plan은 quality 경로에서 접근 불가능하게 한다.

Quality plan의 최소 필드는 `candidate/limits/code_freeze/bound_files/registry/tokenizer/runtime_receipt_sha256/resource_plan+report refs/phases/audit/excluded_roles`다. 각 phase는 ordered case IDs, input/oracle/item/source freeze/preparation receipt의 파일+SHA, 새 output_dir을 바인딩한다. Audit에는 split별 서로 다른 judge, seed32..128bytes+SHA, 새 audit_dir, 실제 노출 attestation ref를 넣는다. Source/item/oracle 본문은 shared code list에 넣지 않는다. 모든 경로는 repository-relative이며 output/seed/audit는 `.local` 안이다. Symlink를 포함해 해석한 경로끼리 양 split·입력/출력·seed·metadata alias/중첩을 차단한다.

`check`는 고정 plan/receipt를 검증하는 모델 없는 단계다. `run`은 성공한 preflight 뒤 native 시작 전 새 output_dir을 atomic/exclusive claim하고 최초 report를 저장한다. 기존 output이 있으면 성공/실패와 관계없이 재사용/이어 실행을 거절한다. Native dispatch를 시작하기 **전에** case/stage/global sequence·payload hash·상한·started 상태를 영수증에 쓰고 flush한다. POST 시도 후 결과 저장 실패도 started 호출로 남으며 재시도하지 않는다. Native recorder의 POST 수와 runtime의 `completion_attempts` wrapper 수를 같은 수라고 가정하지 않고 대조한다.

각 stage는 raw native response, 실제 completion payload/token 배열·grammar, apply-template 요청 messages hash/응답 rendered hash·terminal preamble, tokenize 요청/응답 token 배열 연결, 효과적 decoding 설정, count/finish/cache/model identity·native timings를 별도 로컬 report에 기록한다. Stage2 message/grammar/plan hash를 실제 stage1 raw에서 재구성할 수 있어야 한다. 원문은 평가 artifact 안에만 있으며 console/native operational log는0bytes여야 한다. Runtime의 safe `requirements` telemetry를 실제 plan 원문 대신 사용하지 않는다.

정상 quality request는 비어 있지 않은 context의 stage1이1회이며, parsed plan이 unsupported면 stage2 없이 고정 abstention, 전부supported면 stage2가 정확히1회다. 이때 stage2의 최종 abstention도 허용하지만 oracle가 answered이면 의미 실패다. `completed_stages`(native 정상 반환), `validated_stages`(plan/answer parser 통과), 실제 native POST, 실패 전 wrapper attempt를 구분한다. Stage1 schema/언어 오류, stage2 입력상한 오류, stage2 언어 오류 등에서도 확보한 raw를 버리지 않는다.

각 request가90초를 넘기거나 source/config/identity/count/cache/byte 계약 불일치, native 오류/OOM/length/언어·schema·인용 guard 오류가 발생하면 즉시 phase를 닫고 이후 항목은 미실행이다. 소유 process만 종료하고 metadata-only 재시작을 최대1회 수행·정리해 provenance를 남긴다. 실패한 생성 재시작/재시도는0이며 metadata 재시작 성공을 생성 복구로 표현하지 않는다. Runtime cleanup과 소유 process 종료 시간을 따로 기록한다. RSS/system available RAM·가능한 기존GPU 계측의 범위/부재도 별도 보존하고 peak라고 하지 않는다.

품질 결과가 올바른 구조로 반환됐지만 의미가 틀린 경우에는 등록된 phase 전체 결과를 확보한다. 오류 응답을 semantic abstention으로 바꾸지 않는다. Calls는 neutral≤4/cal≤12/val≤16, 전체≤32이며 actual count를 같은 ledger에서 확인한다. Quality phase의 call 수는 fixed12/16이 아니라 각 plan 분기에 의해6..12/8..16이다. 미실행·실패가 있는 report는 공식 complete audit가 거절한다. 자동 partial 성공 경로는 만들지 않는다.

## 원본 재생과 최종 답변 우선 판정

Audit prepare는 생성을 하지 않는다. 모든 source/plan/input/oracle/receipt hash, 전체 case 결과·dispatch 순서·횟수·오류0·source unchanged·소유 process 정리·로그0를 먼저 확인한다. Stage1 catalog/messages/grammar와 원래 raw plan을 재생하고, unsupported 분기는 최종 fixed abstention/1call을, supported 분기는 실제 stage2 messages/grammar·원래 raw realization을 `grounded_requirement_answer`로 재생한다. 저장 답변·plan metadata·native token trace와 정확히 같아야 한다. Native `predicted_n`과 `tokens_predicted`를 임의로 같다고 요구하지 않고 각각 원래 의미로 보존한다.

익명 최종 pack은 `{sample_id, question, response_language, contexts, oracle, answer:{status,reason,claims}}`만 포함한다. Plan·need·stage수·raw trace·시간·model label·worker telemetry·original case ID·이전 점수는 제외한다. Oracle ID만 익명 ID로 치환하고 required facts의 내용은 그대로 둔다. 단일 후보라 arm을 숨기는 비교가 아니다. Shuffle seed는 실행 전에 고정했고 pack/mapping/receipt의 SHA를 독점 저장한다. Mapping에는 sample↔case만 있고 부모/custodian은 이를 알고 있다는 사실을 기록한다.

Judge는 기존8 quality boolean, atomic facts/support offsets, 모든 인용 관련성, required-fact coverage, full_correct·reason을 작성한다. 부가 예시/인과도 분모에 포함한다. C3의 planning을 잘했다는 설명으로 누락 답변을 통과시키지 않는다. Correct abstention의 빈 citation/fact rate는null, error/미실행은 정답이나100%가 아니다.

`lock-answers`는 pack+receipt+judge attestation+판정만 읽으며 mapping/plan/report를 열지 않는다. Sample 전수/중복0/역할 독립/기계적 수치 일관성을 검사하고 판정 SHA를 exclusive 저장한다. **이 잠금 전에는 plan pack을 생성·전달하는 `reveal-plan`도 거절한다.** Calibration/validation judge는 서로 다르고 parent/후보 설계·구현/source·문항·oracle 작성/사전검토자는 모두 제외한다.

자동 AGENTS 주입 등을 포함한 실제 노출 attestation은 각 judge가 pack 열람 전에 등록한다. Field는 역할 비참여, mapping/plan/raw/이전 judgment 노출, 모델/가설/기존 결과 metadata 노출, 시각/자기보고 근거, 실제 모델/effort, human0다. Metadata 노출은 사전에 `metadata-exposed, label-masked`로 정확히 보고하고 완전 맹검을 주장하지 않는다. Mapping 또는 plan의 선행 노출·작성자 역할 충돌은 답변 우선 독립 판정 조건 미충족이므로 gate를 거절한다. 이후 새 노출은 append receipt로 보존한다. 기존 `JudgmentFile`의 두true는 대응표 미열람과 작성·설계 비참여만 뜻한다.

## 잠금 뒤 계획 진단 schema

`reveal-plan --answer-lock ...`는 잠금을 원본에서 재생한 뒤 같은 sample IDs의 plan pack을 새로 만든다. Oracle와 전체 제공 context, 실제 plan/선택한 단위, 잠긴 최종 답변을 포함하지만 original case mapping·모델 집계는 아직 숨긴다. 같은 judge가 별도 진단을 작성할 수 있으며 이는 최종 답변 평가와 독립된 두 번째 실험이 아니다.

`PlanDiagnosticFile`의 필수 필드는 `schema_version/purpose=post_lock_plan_diagnostic/reviewer_id/answer_lock_sha256/plan_pack_sha256/human_review_count=0/items`다. 각 item은 다음을 갖는다.

- `sample_id`, 실제 `plan_sha256`, `requirements`: 실제1..K ID 각각 정확히 한 행. `oracle_fact_ids`(0..N), `need_relevant` boolean, `support_assessment=sufficient|partial|unsupported|not_assessable`, `status_justified` boolean, `reason`, 해당 필요의 실제 선택 단위 안 `support_offsets`를 기록한다.
- `oracle_coverage`: 모든 oracle fact ID 각각 정확히 한 행으로 `requirement_ids`(빈 배열 허용), `need_covered` boolean, reason. 누락 요구를 실제 plan에 새로 추가하지 않는다.
- `realization_checks`: 최종 answered일 때 실제 슬롯마다 `requirement_id`, `fully_realized` boolean, `added_inference` boolean, reason. 최종 abstained이면 빈 배열과 `abstention_branch=stage1|stage2` 및 적절성 판단/reason.
- `failure_categories`: `requirement_omission`, `evidence_misclassification`, `realization_omission`, `added_inference`, `abstention_choice` 중0개 이상과 각 관측 근거. 자동 root-cause 입증이라고 하지 않는다.

Schema/coverage/offset는 코드가 확인하고 의미 판정은 judge가 한다. `not_assessable`에는 이유가 필요하며 성공으로 환산하지 않는다. 이 진단은 gate용 가중치/임계값을 추가하지 않으며 답변 점수는 바뀌지 않는다. Finalize는 plan diagnostic 파일 SHA도 봉인하여 같은 answer-lock과 연결한다. 별도 점수 선택/plan을 보고 답변 judgment 재작성은 금지한다.

## Gate와 검증 대상

`finalize`는 원본/pack/판정 잠금/진단/attestation/mapping을 재생해 전체6/8개의 결과를 집계한다. Calibration은6/6 완전 적합+전체 운영 무결성일 때만 `selected=true`; validation은선택 gate를 재생한 뒤8/8·부적절 보류/근거 없는 추가 사실/오류0일 때 `validation_passed=true`다. Plan 진단 내용은 설명용이며 gate를 완화/강화하지 않는다. Partial 결과는 selection 불가다. 둘 다 서비스 자동 채택·human review를 뜻하지 않는다.

Validation의 **품질 실행용 `check/run/audit`**는 어떠한 validation input/oracle/body 파일 열람보다 먼저 cal gate와 그 원본 연결 전체를 재생한다. Hash 문자열만 믿지 않는다. 이 gate는 앞서 등록한 **custodian 전용 source 작성·사전검토·문항 동결·offline tokenizer prepare**를 금지하지 않는다. 해당 준비는 calibration gate 이전에 허용되며 생성은0이다. 부모/구현자는 그 과정에서도 validation body나 항목별 semantic 설명을 받지 않는다. Code freeze/plan integrity 확인에는 phase별 원문 열람이 필요하지 않게 refs를 구분한다.

필수 합성 검사는 다음에 집중한다. 기존 전체 테스트를 복사해 거대한 새 framework를 만들지 않는다.

1. C3 registry의cal6/val8·불균등cal가족언어할당·answered3..6facts·OR-of-AND 복수 문서·교차언어·partial-missing 확인; C2 validator는 그대로 거절하고 C3 score math parity.
2. Stage1 count4096/5120 경계와5121 실패, payload생략/null/Unicode/전체 원문 보존, official receipt/hash drift, stage2 미측정 표시와 generated plan의 stage2 5121에서native0, explicit language 전파.
3. Missing/uncertain1call, all-supported2calls, stage2abstention, schema/언어 오류의 completed/validated/native 수 분리, request 시작 기준 공유90초/두 번째 deadline reset 거절, started 영수증 후 통신실패의 재시도 금지.
4. Native raw/config/token/apply-template/grammar/source tamper 재생 실패, plan↔stage2 또는 최종 인용 조작 거절, output/byte/path/symlink/phase alias, 소유 process cleanup/watchdog/partial-stop/재실행 lock.
5. Quality에서resource 특수grammar 금지, normal1call이면resource 실패, stress두단계 공유90·각384와전체768,계보native32 초과금지·metadata재시작생성0.
6. Final pack에 plan/stage metadata 없음, 답변 잠금 전에plan reveal 거절, 노출 attestation 미등록/plan선행노출 거절, sample누락/중복/판정불일치 거절, 잠금 후변조 거절, plan진단행/offset coverage, final 점수 불변.
7. Calibration gate 실패/부분6미만/위조 ref/바뀐judgment이면 validation 파일을 **열기 전에** 거절하는 read-spy 검사. 성공처럼 보이는 synthetic6/6·8/8은 도구 검사값으로만 표시.

이 계약 구현·합성 검사·source freeze 전에는 새 source본문/문항 작업으로 넘어가지 않는다. 실제 native/의미 품질·Java/React 운영은 그 이후 단계이며 현재 phase1/PR14는 미완료/draft다. 무료/로컬·기존동결 보존·인간0·서비스 미채택 경계를 유지한다.
