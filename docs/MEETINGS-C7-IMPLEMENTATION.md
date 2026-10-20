# C7 자료 수용 검사 구현 기록

상태: NEW8 구현·최종 합성 검사244통과/1skip·독립 코드 검토·77파일 동결을 완료했다. 정확한 구현 커밋의 CI 확인이 다음이다. 실제 C7 자료 채택, 토크나이저 준비, 모델 답변 생성과 서비스 채택은 아직0이다. [설계](MEETINGS-C7-PLAN.md)는 c10b753으로 커밋했으며 [설계 CI 영수증](../experiments/results/meetings-c7-design-ci-v1.json)은 해당 커밋의 backend/web/java-service 성공만 증명한다. 미커밋 구현의 CI로 해석하지 않는다.

## 해결하려는 문제와 선택

이전 후보는 질문을 만든 뒤 실제 입력 크기를 확인하는 단계에서 종료됐다. C7은 공개 원문을 채택하기 전에 문서3개로 이루어진 family 전체의 크기를 검사한다. 문서에서 만들어진 모든 청크와 공백 block, 제목·문서 ID·날짜·좌표, 중첩 JSON escape와 고정 시스템 문구를 함께 센다. 일부 청크를 빼거나 원문을 짧게 고쳐 통과시키지 않는다.

고정 규칙은 메시지 직렬화6656bytes에 미래 질문 여유1024bytes와 chat wrapper 여유512bytes를 남기는8192bytes 예산이다. Byte 수는 토큰 수를 보장하지 않는다. 따라서 독립 검토를 마친 질문은 공식 준비에서 실제 prompt를 한 번 구성하고 한 번 encode해 bytes·hash·tokens를 동시에 기록한다. 실패한 준비를 다시 실행하거나 결과에 맞춰 질문을 수정하지 않는다.

모델이나 context limit을 늘리는 방법과 통과한 이전 자료를 다시 사용하는 방법은 선택하지 않았다. 새 후보에서도 같은 추론 조건과 일반 문서·복수 회의의 의미 평가 범위를 유지한다. 짧은 공개 자료만 채택하게 되는 대표성 한계는 남는다.

## 실제로 연결하는 흐름

자료 담당자는 먼저 고정 코드와 자신에게 부여된 역할의 실제 Git 증명을 확인한다. 아직 채택·커밋되지 않은 prospective 원문에는 현재 파일 snapshot과 hash를 적용한다. 이 단계의 원문을 이미 커밋된 자료라고 기록하지 않는다.

고정 처리기로 전체 source text와 모든 청크를 재생성하고, 두 언어의 full-family 표현을 검사해 수용 또는 거부 영수증을 남긴다. 통과한 영수증은 source freeze에 포함한다. 이후 자료가 실제로 커밋되면 해당 Git 증명과 전체 admission replay가 질문·oracle의 의미 내용을 파싱하기 전에 실행돼야 한다. 문서와 영수증의 연결이 끊기면 후속 준비를 거부한다.

질문의 byte 검사와 공식 prompt 계수는 별도 단계다. 공식 준비에서 첫 실패가 발생하면 그 문항까지의 실제 측정과 나머지 미실행 문항을 구분해 기록하고 종료한다. C6가 모든 문항을 계수했던 방식과 다르며, 미실행 문항의 크기나 통과 여부를 추정하지 않는다.

## 검토와 기여 범위

기존 실제 Astra high `host_proof_profile`이 새 review/prepare/probe/audit와 각 테스트8파일을 소유한다. 새 `c7_implementation_review`는 도구가 실제 수락한 Astra high/fork none으로 코드와 합성 테스트만 독립적으로 읽는다. 부모는 내용 없는 family registry, 이전 파일 보존 확인, 결과 문서와 Git/CI를 맡는다. 이 역할들은 실제 평가 자료 작성자·최종 의미 판정자·사용자 검수자가 아니다.

첫4개 초기 합성 검사는78통과·Windows symlink 권한1skip,12.08초다. Ruff import-order1 실패도 보존한다. 추가100통과/1실패/1skip 검사와 별도 실제 encode-empty·processor-capture2실패를 보존했다. 독립 검토가 지적한 새 출력 디렉터리의 예약 누락, 원문 처리 예외에서 거부 기록 소실, 실패한 family 원본 identity 누락, 선언 page 미검사와 실제0-token 관측 소실을 수정했다.

수정 과정의 전체 검사는118통과/1skip/fixture2실패(12.72초)였고, 마지막 두 테스트가 원래 값과 같은 값을 대입하던 문제를 고친 뒤 해당 transition12개가 통과했다. Ruff도 통과했다. 첫4개 독립 재검토는 최종 prepare be170c43·prepare test17a8fa5b에서 남은 blocker0을 보고했다. 서로 겹치는 검사 수를 합산하지 않으며, 이 수치는 최종8개 전체 결과도 실제 모델 검증도 아니다. Runner/audit4 구현은 이어서 진행한다.

그 뒤 runner/audit 합성50개가244.40초에 통과했다. 마지막으로 NEW4 테스트 모듈과 기존 policy/adapter2 모듈을 함께 실행해 **244통과·1skip,251.30초**, Ruff 통과를 확인했다. NEW8과 재사용 테스트2개의 검사 전후 hash가 같고, 검사 전에 UTF-8/BOM 없음/LF를 확인했다. 검사 후 정규화나 소스 변경은 없다. Windows symlink 생성 권한 때문에 건너뛴1개를 통과로 세지 않는다.

독립 검토는 전체 자료 hash chain, 실제 prompt bytes/hash/token 관측 결합, validation 개방 조건, 익명 판정과 seed64,90초/1200초 및 마지막 저장 검사, 첫 실패 보존,64KiB reader 경로를 다뤘다. 검토자는 테스트나 실제 자료를 실행하지 않았다. 실제 원문·모델·외부 서비스로 이 구현을 검증했다고 주장하지 않는다.

```powershell
uv run --no-sync python -m pytest tests/test_meeting_c7_review.py tests/test_prepare_meeting_c7_inputs.py tests/test_probe_meeting_c7_quality.py tests/test_audit_meeting_c7_quality.py tests/test_meeting_answer_thinking.py tests/test_meeting_thinking_quality.py -q
uv run --no-sync ruff check src/doctrail/meeting_c7_review.py scripts/prepare_meeting_c7_inputs.py scripts/probe_meeting_c7_quality.py scripts/audit_meeting_c7_quality.py tests/test_meeting_c7_review.py tests/test_prepare_meeting_c7_inputs.py tests/test_probe_meeting_c7_quality.py tests/test_audit_meeting_c7_quality.py
```

위는 완료한 합성 검사 범위의 재현 방법이다. 공식 모델 평가나 닫힌 실험을 실행하는 명령이 아니다. 공식 CLI 경로는 모듈 실행 방식을 사용한다.

## 다음 관문과 사용자가 이해할 부분

동일한 최종 파일로 합성 회귀와 독립 검토를 마친 뒤 [전체 도구 동결](../data/evaluation/meetings-c7-toolchain-freeze-v1.json)을 생성했다.77파일·Python66·import 후보1664(부재1598), SHA6f829eeb829b957683fb2a7c4b6182a14aab787d816ede11b1c017bbe69a65ca다. 봉인된 재탐색도 일치했다. 기존 코드123개와 닫힌 C6 공개81개 및 이전 동결6개의 bytes 불변을 확인했다. [구현 영수증](../experiments/results/meetings-c7-implementation-v1.json)은 최종 검사·초기 실패·독립 검토와 각 원본 hash를 함께 남긴다.

정확한 커밋의 필수 CI와 별도 영수증을 보존한 다음 새 자료 역할을 등록한다. 원문 이용 조건·의미적 적합성·중복·Java 처리 일치와 독립 질문 검토를 거쳐야 실제 모델 평가로 넘어간다.

면접에서는 “입력을 줄여 답이 맞게 했다”가 아니라 “자료를 보기 전에 고정한 수용 규칙으로 후보를 거부할 수 있게 했고, 그 규칙을 만족한 새 자료에서도 별도의 의미 평가가 필요하다”고 설명할 수 있어야 한다. 사용자 직접 검수는 아직 수행되지 않았다.
