# C3 실행 계약의 잠금·정리 경계 명확화

2026-10-14 · `c2_budget_followup` · 부모가 확인한 실제 역할 설정 `gpt-6-astra / xhigh`. 부모 모델을 변경했다는 뜻이 아니다. 이 역할은 후보/실행 계약 설계에 참여했으므로 이후 독립 출력 채점에서 계속 제외한다.

원본 `docs/MEETINGS-C3-EXECUTION-CONTRACT.md`의 SHA-256은 `25258b88f8cfba96a70ff24f5803d113ede7c405fe5b41238d685ffb863758b7`이며 변경하지 않았다. 이 문서는 원본과 `MEETINGS-C3-PLAN.md`, 새 `scripts/probe_meeting_requirements.py`·`scripts/audit_meeting_requirements.py`만 대조한 좁은 설계 명확화다. 코드 전체 검증이나 실제 실행 통과 판정이 아니다. 실제 자료·문항·held-out/pool 열람, tokenizer/native/검사/네트워크/Git 실행은 이 작업에서0이다.

## 1. 답변 잠금의 열람 금지는 현재 split에 적용한다

원본의 `lock-answers`가 “mapping/plan/report를 열지 않는다”는 문장에서 `plan`은 **현재 split의 모델 생성 requirement plan**을 뜻한다. 코드·경로·hash·역할을 등록한 **execution plan 메타데이터**와 구분한다. 현재 split의 requirement plan, raw native report/trace, sample↔case mapping을 읽어 답변 판정이나 잠금을 만들지 않는다는 경계는 유지한다.

Validation의 `lock-answers`는 다음 순서로 처리한다.

1. 고정 audit 경로의 현재 receipt와 execution plan 메타데이터를 확인한다. Receipt의 phase·경로·hash 연결을 검증하고, 임의 경로를 받아 원문을 여는 통로로 사용하지 않는다.
2. **현재 validation answer pack을 열기 전에** calibration selection을 해당 calibration의 원본 input/oracle/report/pack/mapping/answer lock/판정/잠금 후 plan 진단까지 연결하여 모델 없이 전부 재생한다. Calibration의 complete6/6·운영 무결성·selected/validation_eligible과 원본 일치를 확인한다. Gate JSON의 성공 flag/hash 문자열만으로 대체하지 않는다.
3. Gate가 통과한 뒤 현재 validation의 사전 등록 노출 attestation·최종 답변 pack·판정만으로 answer lock을 생성한다. 현재 validation requirement plan/raw/mapping은 이 단계에서 열지 않는다. Gate가 실패하면 validation answer pack 열람 전에 거절한다.
4. 현재 validation answer lock의 원본 연결을 확인한 **뒤에만** `reveal-plan`이 현재 plan pack을 기록·전달한다. Judge가 plan을 보고 최종 답변 판정을 고치거나 잠금 전에 plan을 받는 것은 계속 금지한다.

Calibration originals의 gate 재생은 audit/custodian 도구 내부 동작이다. 그 원문·계획·대응표·점수 상세를 validation judge에게 전달할 필요가 없으며, 이 예외는 그런 전달을 허용하지 않는다. 실제 AGENTS/모델·가설·과거 결과 metadata 노출은 사전 attestation에 그대로 기록한다. 표본 대응표 미열람과 저자/설계자 역할 비참여를 모델·가설 완전 맹검으로 확대 해석하지 않는다.

Audit `prepare`가 custodian 경계 안에서 현재 raw를 재생하여 답변 pack을 만드는 것과, judge의 plan 선행 열람은 다르다. `prepare` 단계에서는 현재 plan pack을 파일로 공개하지 않는다. Judge에게 현재 plan이 노출되었으면 독립 답변 우선 조건 실패이며 이 문서로 구제하지 않는다.

**판정:** 원본의 validation gate-before-body와 answer-lock-before-plan-reveal을 동시에 만족시키는 해석이다. 새 audit의 `locked`·`verify_validation_gate`·`replay_locked`는 이 구분을 명시하고 있다. 원본의 “pack+receipt+attestation+판정만”은 현재 split 의미 자료의 범위이며 calibration gate 원본 재생을 생략하라는 뜻이 아니다.

## 2. 서버는 phase 안에서 재사용하고 요청 기한은 각각 유지한다

서버 하나를 해당 phase의 순차 요청에서 재사용한다. 정상적으로 끝난 각 요청 뒤 서버 process를 종료하거나 재시작할 필요는 없다. 각 요청의 준비→stage1→plan parse→stage2 준비/실행→답변 검증→**요청 adapter cleanup 전체**는 여전히 공유90초 안에 끝나야 한다. Stage2에 새90초를 주지 않으며 다음 요청은 이전 요청 정리가 끝난 뒤 시작한다.

| 경계 | 적용 범위 |
|---|---|
| 요청90초 | 각 요청의 두 단계와 준비·후처리·adapter cleanup. 단계/호출별 독립90초가 아니다. |
| 요청 시작→소유 process 정리120초 | 오류가 난 요청, 또는 phase의 마지막 요청 시작부터 최초 실행 서버의 종료 확인까지. 실패하면 이후 요청은 미실행으로 남기고 즉시 정리한다. |
| 소유 process kill/wait5초 | 최초 실행 서버 정리 및 metadata 재시작 서버 정리에 각각 적용한다. Adapter cleanup 기록과 별도다. |
| 전체 phase2400초 | 서버 startup, 모든 요청, 최초 process 정리, metadata-only 재시작과 그 정리까지 포함한다. |
| metadata-only 재시작≤1회 | 최초 process 정리 뒤 identity/설정 확인만 수행한다. 추가 생성·warmup·실패 요청 재시도는0이다. |

120초는 **모든 과거 성공 요청의 시작부터 phase 종료까지**를 각각 재는 규칙이 아니다. 마지막 요청의 `last_request_through_cleanup_ms`와 각 요청90초 기록을 구분한다. Metadata 재시작은 최초 process 정리 뒤의 별도 계측이며 전체 phase2400초와 자체 kill/wait5초 안에 있다. 정상 완결 report는 등록된 metadata 복구 확인까지 성공해야 한다. 허용 재시작 횟수가 최대1회라는 이유로 복구 증거가 없는 report를 성공 처리하지 않는다.

최초 요청 전에 startup/identity 등에서 실패하면 존재하지 않는 요청 시작 시각을 만들지 않는다. 소유 process 정리·phase 상한·실패 기록을 유지한다. 시간 초과나 정리 실패를 뒤늦은 정상 종료로 상쇄하거나 다음 요청으로 이어가지 않는다.

**판정:** 재시도0·동시성1·단계 공유90초와 phase 단위 소유 서버 수명에 맞는 명확화다. 새 probe의 `execute`는 phase 단위 서버를 사용하고 `last_request_through_cleanup_ms`, `owned_cleanup_ms`, `recovery_cleanup_ms`, `elapsed_seconds`를 구분한다. 이 문서는 watchdog/실제 지연의 검증을 대신하지 않으며 어떤 상한도 늘리지 않는다.

## 3. 메타데이터·실행·audit 경로를 분리해 동결한다

`phase`는 `calibration|validation`만 허용한다. 새 코드가 정한 다음 경로와 artifact 역할을 전체 toolchain freeze/quality plan에 유지한다.

- 실행 출력: `.local/meetings-c3-run-{phase}-v1/report.json`.
- Audit 디렉터리: `.local/meetings-c3-audit-{phase}-v1`; 내부 이름은 `answers.json`, `mapping.json`, `receipt.json`, `judgments.json`, `answer-lock.json`, `plans.json`, `plan-reveal.json`, `plan-diagnostics.json`, `selection.json`으로 고정한다.
- Seed/노출 receipt: `.local/meetings-c3-review-metadata-v1/{phase}/seed.bin`, 같은 디렉터리의 `attestation.json`.
- Validation gate: `.local/meetings-c3-audit-calibration-v1/selection.json`만 허용하고 등록 execution plan과 원본을 재생한다.
- 준비 receipt: `data/evaluation/meetings-c3-{phase}-inputs-v1/receipt.json` 또는 `.local/meetings-c3-{phase}-prepared-v1/receipt.json` 중 plan에 봉인한 하나다. Source/item/input/oracle refs는 해당 split namespace에 있으며 **개별 정확한 경로와 SHA**를 봉인한다. Prefix가 맞는 다른 파일로 바꾸는 권한이 아니다.

Execution plan 자체도 등록한 정확한 경로·SHA 하나에 연결한다. 공유 code/registry/resource metadata 참조에 validation 의미 자료를 끼워 넣거나 receipt의 snapshot 목록으로 우회해 열지 않는다. Split 간 참조, 입력/출력·seed/metadata 중첩, symlink/hardlink alias 거절을 유지한다. 경로 검사는 파일 내용을 읽는 허가와 구분한다.

이 새 문서는 앞으로 만들 전체 toolchain freeze의 **정확한 허용 binding 집합에 추가**한다. 새 tooling의 집합 검증도 같은 경로를 요구해야 하며 임의 추가 문서를 허용하는 방식으로 넓히지 않는다. 기존 candidate28·원본 계약 hash·닫힌 실험 freeze는 그대로 둔다. 이 작업에서는 코드나 기존 문서를 수정하지 않았다.

두 모호성의 위 해석은 기존 설계 의도와 일치한다. 최종 답변 점수·cal6/6/val8/8·사전 자료 격리·생성 최대32회·실패 시 중단·인간0·자동 채택 금지는 모두 유지한다. 새 toolchain freeze 이전의 실제 source/문항 작성 또는 실행을 이 명확화만으로 허용하지 않는다.
