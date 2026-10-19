# C5 검증 도구 구현 기록

상태: 마지막 저장 실패 경로 수정과 관련 합성 회귀를 완료했고 전체 도구 76개를 동결했다. 소스 커밋과 해당 CI 확인이 다음이다. 새 원문 수집, 질문 작성, 실제 tokenizer 준비와 모델 생성은 하지 않았다. 이 문서는 [C5 계획](MEETINGS-C5-PLAN.md)의 구현 기록이며 닫힌 C4와 GPU 배치 비교를 다시 실행하는 지시가 아니다.

## 해결할 문제와 범위

GPU28의 한 쌍 비교가 실제 답변 품질을 증명하지는 않는다. 새 자료에서 동일한 90초·토큰 한도와 원래 의미 판정 관문을 적용할 준비가 필요하다. 기존 모델 정책과 launcher는 바꾸지 않고 C5 전용 준비·실행·검수 도구와 합성 테스트 8개 파일을 추가한다. 모델 설정은 GPU 요청 layers28 하나로 고정한다.

도구는 문서 출처와 이용 조건, 전체 문서의 Java/Python 처리 일치, 질문과 근거의 사전 검토, 실제 역할 분리, 커밋과 CI를 확인한다. 검증 세트 실행은 원래 calibration 6/6 통과를 재생한 뒤에만 허용한다. 격리 담당자의 사전 자료 준비와 tokenizer 계수는 이 실행 관문과 구분한다.

## 익명 검수와 원문 보존

원래 oracle은 c5-f01..04와 실제 작성·검토 역할을 기록한다. 최종 판정자에게 주는 별도 익명 schema에서는 구조적 문서·chunk·fact·case·author ID만 일관되게 치환한다. 공개/합성 구분은 family-public/family-synthetic으로 남긴다. 질문, 원문, 인용 문장, 자연어 사실은 치환하지 않는다.

자연문에 운영용 ID가 있으면 모델 실행 전에 pack 적합성 검사에서 거부한다. 생성 답변에 새 충돌이 생기면 원본 응답을 보존하고 pack 생성 실패로 남긴다. 일반적인 주제명까지 임의로 지우거나 근거 좌표를 고치지 않는다. 역할과 ID를 숨겼다는 사실을 완전한 맹검이라고 표현하지 않는다.

## 실행과 실패 기록

각 요청의 첫 무결성 확인부터 마지막 필수 결과 저장까지 같은 90초에 포함한다. 전송 직전 기록에 시간이 걸려도 남은 시간을 다시 확인한다. 준비·전송 예약·전송 후크·응답 보존·구조 통과 수는 각각 기록하며 후크 실행을 실제 서버 수신 증명으로 취급하지 않는다.

최초 오류와 뒤의 정리·저장 오류를 분리한다. 추가 neutral 생성, 재시도, 복구용 추가 모델 실행은 없다. Phase별 owned launcher 한 번과 종료 정리를 사용하며 다른 프로젝트 프로세스는 종료하지 않는다. Cleanup과 deadline 검사는 수용 조건이며 Windows I/O의 강제 선점을 보장하지 않는다.

최종 `completed` 저장이 시간 제한을 넘고 실패 상태의 재저장도 실패하면 이전 성공 파일이 남을 수 있다. 별도 실패 기록 `failed-final-save.json`가 존재하면 내용의 파싱 가능 여부와 무관하게 재생·검수 준비·calibration 관문을 거부한다. 저장 전에 시간 초과가 확인된 경우도 먼저 최초 원인으로 남겨 후속 저장 오류에 가려지지 않게 한다.

실제 완료 판정은 독립 CLI 관측의 종료코드0, terminal summary와 report 무결성을 모두 확인한 뒤 수행한다. 재생 도구는 이 외부 종료 확인을 대신하지 않는다. 실패 기록조차 저장할 수 없는 전체 파일시스템 오류에서는 기존 disk report만으로 완료를 증명할 수 없다.

최종 판정자는 아직 배정하지 않았다. 실제 등록 때 두 판정자가 각자 생성한 64바이트 seed의 생성·수락 경위, 서로 다른 SHA, 허용 경로와 커밋을 확인한다. 코드의 경로·길이·hash 결합 검사만으로 독립 생성까지 증명했다고 주장하지 않는다. 서로 다른 바이트라는 사실만으로도 독립 생성은 입증되지 않는다.

## 검토와 실제 합성 검증 결과

- 최초 실제 Astra high 구현 역할은 `host_proof_profile`이며, 2026-10-19 핸들과 실제 작업 프로세스 부재를 확인한 뒤 새 실제 Astra high `c5_persistence_recovery`가 probe/test2의 마지막 수정을 인수했다. 부모가 문서·동결·Git/CI를 맡는다.
- 실제 Astra high `meeting_navigation_audit`가 원래 NEW8을, 새 실제 Astra high `c5_persistence_review`가 마지막 delta를 독립 읽기 검토했다. 추가 실질 blocker를 발견하지 못했으며 둘 다 최종 답변 judge에서 제외한다. 읽기 검토는 테스트 실행이나 모델 품질 증명이 아니다.
- 첫 review/prepare 58통과·Ruff, historical paragraph 최초1실패→수정1통과, 준비 중 import 후보 변경 최초1실패→수정1통과를 각각 보존했다. 실제 과거 원문은 열지 않았다.
- 마지막 persistence 수정 전 전체 묶음은 168통과(NEW94+기존 정책/adapter74), 352.62초, Ruff·종료코드0·검사 전후 동일 SHA다. 이 수치를 수정 후 단일 실행 결과로 표시하지 않는다.
- 새 복합 저장 실패는 최초2실패, 저장 전 deadline 원인 유실은 최초1실패로 재현했다. 수정 후 해당3회귀는 43.63초에 통과했다. 최종 probe/audit 전체 회귀37개가 262.10초에 통과했고 NEW8 Ruff·종료코드0·검사 전후 hash 일치를 확인했다. 나머지6파일은 원래168 검사 시점과 같다. 소스 커밋과 필수 CI가 남았다.

초기 테스트 실패와 중간 검사 기록은 `.local/c5-implementation-v1/`에, 마지막 저장 실패의 원본과 수정 증거는 `.local/c5-persistence-recovery-v1/`에 보존한다. 사용자 직접 검수, 새 데이터, 실제 추론 품질 판정은 모두 0이다. Phase1과 PR14는 아직 미완료다.

## 합성 검사 재현

저장소 루트의 잠긴 개발 환경에서 실행한다. 아래 검사는 합성 자료와 HTTP transport를 사용하며 실제 tokenizer나 모델 서버를 실행하지 않는다. 실제 평가의 once-only 출력 경로와는 별개다.

```powershell
uv run --no-sync python -m pytest tests/test_meeting_c5_review.py tests/test_prepare_meeting_c5_inputs.py tests/test_probe_meeting_c5_quality.py tests/test_audit_meeting_c5_quality.py tests/test_meeting_answer_thinking.py tests/test_meeting_thinking_quality.py -q
uv run --no-sync ruff check src/doctrail/meeting_c5_review.py scripts/prepare_meeting_c5_inputs.py scripts/probe_meeting_c5_quality.py scripts/audit_meeting_c5_quality.py tests/test_meeting_c5_review.py tests/test_prepare_meeting_c5_inputs.py tests/test_probe_meeting_c5_quality.py tests/test_audit_meeting_c5_quality.py
```

첫 4개 테스트 모듈은 새 C5 검증 도구를, 나머지 2개는 재사용하는 정책과 adapter의 기존 경계를 검사한다. 마지막 persistence 회귀3개가 추가됐으므로 앞선 168개 실행과 현재 test 수집을 혼동하지 않는다.

## 동결과 다음 단계

[동결 파일](../data/evaluation/meetings-c5-toolchain-freeze-v1.json)의 SHA는 `d76670c9d0515e68f778c4ede3edfbfadd09a8807208e8c6b9eaee1b97a3444d`다. 파일76개·코드65개·import 후보1632개(부재1567개)를 결합한다. 기존 GPU59/C4quality85/host52는 working과 HEAD에서 변경이 없음을 확인했다. [구현 영수증](../experiments/results/meetings-c5-implementation-v1.json)은 검사 범위별 소스 hash, 실패와 수정 증거, 독립 검토 및 한계를 보존한다.

소스/freeze 커밋의 필수3개 CI 성공과 별도 CI 영수증 커밋 뒤에만 새 원문 담당자를 배정한다. 공개/합성 원문을 먼저 확정하고 Java 처리 일치와 별도 원문 검토를 마친 다음 질문을 작성한다. 최종 모델 판정은 이 합성 검증과 별개다.
