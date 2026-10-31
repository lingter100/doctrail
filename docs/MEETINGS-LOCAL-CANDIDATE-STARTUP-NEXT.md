# 로컬 후보 시작 실패 후 다음 단계

2026-10-26 · 기존 Astra xhigh의 generic 설계 · 준비 제안만 작성

**다음 행동 하나는 기존 candidate driver에서 실행 중 준비 작업을 제거하고, 이미 검증한 자산 연결과 실제 RAM gate 값을 전달·기록하는 최소 수정이다.** 동일 후보·원문·질문·프롬프트·내용 기준은 유지한다. 소비된 등록 `df2e819e…`와 결과는 불변이며 재시작하지 않는다.

확인한 사실은 다음과 같다.

- 실제 CLI 1회가 exit 1로 끝났다(CLI 38.282초, driver report 37.172초). 첫 실패는 `local_candidate_startup_ram`; native 생성시도·tokenizer·completion은 0이고 요약 4/QA 4 모두 미실행이다. 품질 실패나 모델 로딩 실패로 해석하지 않는다.
- 외부 관찰기의 실행 직전 가용 RAM은 11,164,737,536B로 10GiB 기준을 통과했다. 내부 gate의 실제 수치는 저장되지 않았다. 코드·오류로 그때 기준 미만이었다는 조건은 알지만 정확한 감소량·원인은 복원할 수 없다.
- 현재 `verify_registration`은 등록된 62개 자산을 이미 크기/SHA로 검증한다. 이어 `launch`가 `prepare(..., allow_download=False)`를 호출하고, 준비 helper는 기존 runtime이 있어도 임시 디렉터리에 전체 압축 해제 → 임시·기존 runtime inventory 비교 → 임시 삭제를 수행한다. 그 뒤 RAM gate가 실행된다.
- `digest`와 압축 복사는 1MiB 단위이며 native loader의 파일 검증도 streaming이다. 가중치 전체 `read_bytes`가 원인이라는 근거는 없다. RAM gate·준비 단계별 시각/메모리가 없어 전체 38초를 준비 시간으로 간주할 수도 없다.

중복 준비 제거는 확실히 불필요한 디스크 추출·설치 작업을 줄인다. 파일 캐시, CLI 메모리, 다른 앱의 변동 등이 내부 RAM 저하에 얼마나 기여했는지는 **미확인**이다. 이 변경이 10GiB 통과를 보장한다고 주장하지 않는다.

후속 구현은 기존 candidate script/test 2개에만 한정한다. frozen helper, 기존 mode probe, 모델 프로필·자산은 수정하지 않는다.

1. `verify_registration`의 **기존 62자산 full hash 검증 한 번**에서 얻은 checked path/receipt를 작은 준비 완료 연결값으로 반환하고 같은 실행의 `launch`에 전달한다. `prepared: true`나 과거 receipt만 믿지 않는다. launch에서 `prepare`를 다시 호출하거나 별도 validator로 전체 파일을 재해시하지 않는다.
2. 연결값은 고정 profile SHA와 receipt의 manifest SHA, 모델 파일명·크기·SHA, runtime/license metadata 및 등록 참조가 일치해야 한다. server는 등록·검증된 runtime 내부의 유일한 `llama-server.exe`, model은 검증된 GGUF 경로여야 한다. 미검증 `server_path` 문자열을 그대로 실행하지 않는다.
3. 기존 준비 함수의 무결성 경계를 보존한다. 실제 runtime의 **경로 집합**은 등록된 55파일과 정확히 같고 symlink/reparse·누락·추가 파일은 거부한다. 이는 제한된 이름/경로 대조이며 이미 검사한 파일의 두 번째 hash inventory가 아니다. 준비 시 확정된 receipt·공식 archive binding과 현재 등록 자산의 관계를 검사하되 실행 중 압축 해제·설치·다운로드는 0이다.
4. 소유 lease 확보 후 **Popen 바로 전 gate에 실제 사용할 단 한 번의 RAM sample**을 단계·경과시간·기준·통과 여부와 함께 metrics에 남긴다. 비교와 기록은 같은 sample을 사용하며 실패해도 report/terminal에 남긴다. RAM이 10,737,418,240B 미만이면 Popen 0으로 종료한다. 재샘플 통과 대기·다른 앱 종료·자동 재시도는 하지 않는다.
5. 기존 native loader의 build/alias/model 신원 확인, 소유 핸들·lease·cleanup, 사후 등록 자산 hash, 원본 first failure와 terminal/late-invalidation을 유지한다. 시작 120/활성 900/정리 5/전체 1025초의 시계는 준비 제거를 이유로 새로 시작하지 않는다.

의미 있는 synthetic 회귀는 정상 준비 연결에서 prepare/extract/download가 호출되지 않고 같은 검증 경로로만 launch되는지, 자산/receipt/profile 불일치·미등록 server·추가 runtime 파일·reparse가 Popen 전에 거부되는지, RAM 기준 경계와 기준 미달 sample이 **실제 값 기록 + Popen 0**으로 끝나는지를 확인한다. 기존 종료·예산 회귀를 유지하며 RAM 저하의 실제 인과관계를 mock으로 입증했다고 쓰지 않는다.

검증이 필요한 것은 변경 후 실제 환경에서의 gate 값, 준비 제거의 경과시간 영향, native/API 적합성이다. 이번 설계에서는 준비 재실행·추가 모델 hash·native/tokenizer·프로세스 종료를 수행하지 않았다. 새로운 모델·자료·프롬프트 실험을 제안하지 않는다.

부모의 설계 수용 → 같은 구현자의 최소 source2 수정과 synthetic 검증 → 독립 delta 검토·정확 소스 CI → **별도 새 등록과 명시적 실행 배정** 순서로 진행한다. 새 실행 전에도 고정 RAM·자원 조건을 다시 확인하고 조건 미달이면 기록 후 멈춘다. 원래 소비된 실패를 덮어쓰거나 다시 실행하지 않으며 요약 4/QA 4와 Phase1 전체 목표는 유지한다.
