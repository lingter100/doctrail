# C6 검증 도구 구현 기록

상태: NEW8 구현·독립 검토·소스 동결과 정확한 소스 CI를 완료했다. 최종 로컬 검사는195통과·1skip·Ruff 통과이며 그 뒤 네 파일의 CRLF만 LF로 통일했다. 정규화 소스d3e4e2e의 push39357782029/PR39357786578은 backend/java-service/web 모두 성공했다. [설계](MEETINGS-C6-PLAN.md)의5657bb1 CI와 별도 증거다. 이 문서는 닫힌 실험을 다시 실행하는 지시가 아니다.

## 해결하려는 문제와 선택

C5는 두 번째 요청에서90초를 초과했다. 별도 합성 비교에서는 같은 검사를 유지하며 파일 읽기 요청을64KiB로 제한했을 때 시작12.531→10.969초, 전송 직전3.141→2.047초가 관측됐다. 고정 순서 한 번의 비교라 실제 질의응답의 절감이나 원인을 증명하지는 않는다.

C6는 이 읽기 방식만 새 검증 경로에 연결한다. 검사를 없애거나 시간 제한 밖으로 옮기는 방법, 새로운 hash 캐시, 모델 설정 변경은 선택하지 않았다. 비교할 변화가 작고 현재 바이트·Git 이력·경로·의존 파일의 무결성 조건을 유지할 수 있기 때문이다. 실제 모델의 정확성·답변 지연과 서비스 채택은 이후 별도 검증 대상이다.

## 연결 범위와 소유권

새 review/prepare/probe/audit와 각 테스트의8파일을 기존 실제 Astra high host_proof_profile이 구현하고 반환했다. 독립 기존 Astra high c5_persistence_review는 코드와 합성 검사만 읽어 최종 blocker0을 보고했다. 부모는 내용 없는 family registry·동결·결과 문서·사용자 명의 Git/CI를 담당한다. 새로운 모델 설정 수락이나 사용자 검수로 표현하지 않는다.

Reader는 내부와 호출자 snapshot, 마지막 변경 확인, Git 증명의 현재 파일 읽기와 committed helper의 추가 읽기까지 연결한다. 동결된 기존 구현을 수정하거나 전역 함수를 치환하지 않는다. 허용목록 밖 새 경로는 본문 전에 거부하고, 허용 파일의 hash는 bytes를 읽어 확인한 뒤 AST 또는 의미 파싱을 허용한다. Bytes를 읽지 않는 hash 검증이나 atomic snapshot을 보장하지 않는다.

## 검증 결과와 현재 한계

새 합성 회귀는 숨은 기존 reader 경로, 동일한 검사 순서·횟수, short read/overflow/오류 우선순위, 관측 가능한 중간 변경, Git HEAD/committed bytes, 비허용 import, 요청 deadline, 최초 실패와 마지막 저장 실패를 다뤘다. Remote 없는 임시 Git 저장소에서 실제 바이트/commit 불일치도 확인했다. 실제 모델·tokenizer·새 평가 원문과 closed pool은 사용하지 않았다.

로컬 최종6모듈은195통과·1skip,220.87초였고 Ruff도 성공했다. NEW8 및 기존 정책/adapter 테스트2개의 검사 전후 hash가 같았다. Windows symlink 생성 권한이 없어1개를 건너뛴 사실은 통과로 세지 않는다. 독립 읽기 검토는 테스트 실행이 아니며 fake clock/HTTP 검사는 실제 native90초 성공을 입증하지 않는다.

초기65통과/Ruff4, safe-prefix 원본1실패(1.01초), 중간71통과(9.80초)/108통과(189.72초), seed/reader 원본5실패·27deselected(5.63초)를 별도로 보존했다. 서로 겹치는 검사 수는 합산하지 않는다. C6 오류 prefix·입력 저장의 최초 원인, exact push/PR CI 상태,64byte seed, trusted reader 오류의 최초 원인 보존은 등록 계약을 충족하기 위한 metadata 수선이다. 모델/추론 정책 변경으로 표현하지 않는다.

부모의 동결 준비에서 CRLF를 발견해 첫 helper가 출력 생성 전에 거부됐다. 검사한 네 파일의 원본은 `.local/c6-normalization-originals-v1/`에 그대로 보존하고 CRLF→LF만 적용했다. 부모는 AST/위치 동일·Ruff를 확인했고 독립 검토자는 원본 변환 bytes와 현재 파일4개의 exact 일치를 확인했다. 따라서195개 결과는 정규화 전 소스의 결과다. 최종 bytes는 뒤이어 정확한 소스의 양쪽 전체 CI 성공으로 확인했다. 원본 실패·검사 로그·hash는 [구현 영수증](../experiments/results/meetings-c6-implementation-v1.json)에 결합했다.

```powershell
uv run --no-sync python -m pytest tests/test_meeting_c6_review.py tests/test_prepare_meeting_c6_inputs.py tests/test_probe_meeting_c6_quality.py tests/test_audit_meeting_c6_quality.py tests/test_meeting_answer_thinking.py tests/test_meeting_thinking_quality.py -q
uv run --no-sync ruff check src/doctrail/meeting_c6_review.py scripts/prepare_meeting_c6_inputs.py scripts/probe_meeting_c6_quality.py scripts/audit_meeting_c6_quality.py tests/test_meeting_c6_review.py tests/test_prepare_meeting_c6_inputs.py tests/test_probe_meeting_c6_quality.py tests/test_audit_meeting_c6_quality.py
```

위는 완료한 합성 검사 범위의 재현 방법이다. 공식 one-shot 모델 평가 명령은 이 단계에서 제공하지 않는다.

## 다음 관문

내용 없는 registry는c6-f01..04 구성과12문서/cal6·val8 계획만 기록하며 실제 출처·작성자·원문은 없다. [도구 동결](../data/evaluation/meetings-c6-toolchain-freeze-v1.json)은77파일·Python66·import후보1648(부재1582), SHA939731a4941a78e5e00b812120b50d8c488b939823c6f5e8df0921986791600b다. 기존 frozen union112는 그대로이며 봉인된 재탐색도 일치했다.

정확한 source commit의 push/PR 필수 CI 성공을 [별도 영수증](../data/evaluation/meetings-c6-toolchain-ci-v1.json)에 보존했다. 그 영수증을 커밋한 뒤 새 자료 역할을 등록한다. 원문 검토와 Java 처리 일치, 문항 독립 검토, 공식 offline 준비를 차례로 거친다. 최종 답변의 의미 판정과 실제 Java/React 서비스 통합·사용자 검수는 여전히 미완료다.
