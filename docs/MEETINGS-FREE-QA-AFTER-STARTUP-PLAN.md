# 시작 성공 뒤 무료 QA 비교 재개 계획

2026-10-29. **다음 최소 단계는 새 비교 v2에 속한 중립 생성1회다.** [시작 진단 v2](MEETINGS-FREE-QA-STARTUP-V2-RESULTS.md)는 health·props와 정리·보존을 통과했지만 생성·토큰화는0회였다. QA 선행 성공이나 답변 품질 증거로 바꾸지 않는다. 이 문서는 설계이며 새 등록·모델 실행을 승인하지 않는다.

실측 출처는 커밋 `8846d5da27bc7f92de1a77ce404d5edf0a98cc60`이며 이 설계는 같은 공개 소스 바이트를 확인했다. 부모의 결과 문서 게시로 HEAD가 이동하더라도 이를 새 코드 검증으로 세지 않는다. 다음 코드 변경은 게시한 정확 소스 CI를 별도로 확인한다.

이번 시작 성공은 고정 runtime/model/template 조합의 [표현 차이 보완](MEETINGS-FREE-QA-RUNTIME-TEMPLATE-FIX.md)이 적용된 현재 경로에서 확인했다. 원래 props 응답 본문·원시 template 해시는 보존하지 않아 UNKNOWN이며, 과거 [중립 실패](MEETINGS-FREE-QA-NEUTRAL-RESULTS.md)의 정확 원인도 UNKNOWN이다. 실패한 비교 v1과 시작 v1, 소비된 시작 v2의 통제·once·실패 기록은 보존한다.

현재 `load_registration`은 같은 비교 계약에서 중립 생성1회·유효 사례1개, 실제 CLI exit0·정확 stdout·terminal/report·cleanup·deadline·외부 custody를 요구한다. 시작 진단의 다른 terminal 스키마와 생성0은 이를 충족하지 않는다. 별도 진단 도구를 추가하지 않고 기존 `run_epoch`·`PairedQAAdapter`로 이미 고정한 공개 합성 중립1개를 새 계약에서 실행한다. `/apply-template`·`/tokenize`·`/completion`, 고정 grammar·설정 echo·EOS와 시간/자원 경로가 실제로 통과하는지 확인한다. 또 실패하면 품질 호출0으로 중단하고 자동 재시도하지 않는다.

## 최소 구현과 새 권한 경계

공개 소스 변경은 `tools/free_qa/runner.py`의 `TRUSTED_LOCK_FILE`을 `data/meetings/free-qa-trusted-locks-v2.json`으로 옮기는 상수1개와 `tests/test_meeting_free_qa.py`의 회귀 검사로 한정한다. 기존 v1 신뢰 파일을 덮거나 CLI/env로 신뢰 경로를 선택하게 하지 않는다. policy·adapter·schema·terminal·모델·template·prompt·grammar·parser·제한은 유지한다. 기존 comparison lock, GPU/worker/llama lease와 `.local/meeting-free-qa-once`의 계약/epoch 예약을 그대로 사용한다.

새 비교 ID는 `meeting-free-qa-paired-v2`, 계약·등록·출력은 새 `.local/meeting-free-qa-paired-v2` 아래로 분리한다. 새 ID와 변경된 code closure가 새 계약 SHA를 만들며 once는 기존 공식대로 계산한다. 같은 계약/epoch를 다른 output으로 다시 실행하는 우회는 계속 거부한다. v1 계약을 새 성공으로 재해석하거나 소비된 슬롯을 지우지 않는다.

회귀는 실제 고정 신뢰 경로 사용, v1 파일만 있을 때 거부, v2 계약과 소스 해시 결속, v1 bytes 보존, 새 계약 once와 동일 epoch 반복 거부를 확인한다. 기존 선행조건 검사에 시작 진단 terminal/생성0 거부를 명시하고 성공한 중립1을 거친 baseline·candidate의 순서와13회/3328토큰 합계를 보존한다. 기존 테스트의 허용 실패·정리 경계도 유지한다. 좁은 변경 검토와 관련 QA/시작 검사·Ruff, 게시한 정확 소스 CI 뒤 기존 준비·검토·설치 흐름으로 연결한다. 새로운 검증 계층은 만들지 않는다.

## 이미 봉인한6개와 단계별 신뢰 파일

[자료 사전 검토](MEETINGS-FREE-QA-SOURCE-PREPARATION.md)를 통과한6개는 모델에 질문하거나 토큰화하지 않았다. 새6개를 다시 작성하거나 쉽게 바꾸지 않는다. 기존14개 입력/sidecar 경로와 바이트, 질문·messages·계열/좌표·순서·제외 index·criteria·packet을 그대로 참조한다. criteria/packet의 의미를 다시 읽거나 출력에 맞춰 조정하지 않는다. 새 계약의 사전 검토 receipt는 기존 수용 근거와 같은 opaque case/criteria binding을 사용하고 `comparison_id`만 v2에 결속한다. 기존 receipt는 보존한다. 판정 때 새 출력의 바깥 연결 기록을 만들며 봉인된 판정 규칙은 바꾸지 않는다.

미래 predecessor 해시는 만들 수 없으므로, 처음 v2 신뢰 파일의 neutral/baseline/candidate 목록은 모두 비워 둔다. neutral 등록만 설치하며 baseline/candidate는 선행 길이 검사에서 거부된다. 중립의 실제 성공과 외부 custody를 수용한 뒤 baseline 목록에 그 정확 참조1개를 추가한다. baseline 종료·custody 수용 뒤 candidate 목록에 neutral, baseline 순서의 실제 참조2개를 추가한다. 계약 SHA와 나머지 신뢰 필드는 그대로다.

이 전이는 v2 신뢰 파일에만 별도 배정으로 적용한다. 매번 이전 bytes와 해시를 불변 사본으로 남기고, 변경되는 필드는 해당 predecessor 목록뿐인지 대조한다. 실행 중에는 신뢰 파일을 포함한 전체 HOLD를 바꾸지 않는다. 해당 실행이 종료되고 외부 보존 검사가 끝난 뒤 다음 단계만 연결한다. 아직 실행하지 않은 단계의 등록·성공 receipt를 미리 만들지 않는다.

## 실제 실행과 중단 조건

순서는 neutral1 → Ministral3 기준6 → Qwen2.5 후보6이며 한 번에 한 모델만 실행한다. 첫 배정은 neutral만이다. 중립 성공은 전송·형식 진입 조건이고, 내용 수용 여부는 봉인된6개에서 별도로 판단한다. baseline의 내용 거부는 분모6에 남기고 예정된 비교를 계속할 수 있지만 protocol·자원·시간·정리·보존 실패는 전체 비교를 중단한다. 미실행 사례를 다른 성공 출력으로 채우지 않는다.

중립은 startup120/active60/cleanup5/whole185초, 품질 epoch는120/900/5/1025초다. 입력4096·요청60초·출력256·ctx6144·parallel1·GPU99·RSS6GiB·시작 여유8GiB/활성 여유2GiB, 중립 포함 최대13생성/요청 출력상한합3328토큰을 유지한다. 초과 입력을 자르거나 예산을 늘리지 않는다.

이미 검토한 PowerShell wrapper·기한 보완 owned monitor·고정 명령/신원/실제 도구 종료 대조를 재사용한다. neutral의 wrapper240/monitor START+300초를 유지한다. 품질 epoch에는 기존 whole1025초에 같은 관찰 여유를 더한 wrapper1080/monitor START+1140초를 고정한 사본을 사용한다. 이는 관찰 한도이며 모델 실행 예산을 늘리지 않는다. 30초 초기 신원 대기, 종료 후 알려진 PID/생성 시각만 조회, 조회 전후 기한 검사·오류 latch·64개 상태 변경 출력은 그대로다. 품질용 변경은 고정 시간 literal과 QA terminal/custody 연결에 필요한 부분만이며, 가상 시간으로300초 이후의 정상 진행과 최종 마감·누락을 확인한다.

각 단계의 단독 실행자가 새 elevated conflict gate를1회 수행하고 내부 fresh 자원 gate를 거친다. 실패하면 실행0 또는 즉시 STOP으로 보존하며 임의 종료·재시도는 없다. 기존 external custody를 QA 계약의 정확 predecessor 스키마에 연결하고, 실제 session/exit·first fault·필수 증거·late invalidation·소유 정리와 전체 HOLD를 확인한다. 시작 전 계획의 불변 사본까지 정확 목록으로 고정하고 부모의 진행 문서는 목록 밖에 둔다. 관측되지 않은 짧은 자식의 부재까지 주장하지 않는다.

출력 판정자는 실행자와 분리하고 유효 출력 전부를 사전 규칙대로 잠근 뒤 모델 대응표를 결합한다. 부모/구현자는 비공개 질문·기준·답변을 열지 않는다. 기존6/6 선택 규칙과 실패 종료 규칙은 [원래 비교 결정](MEETINGS-FREE-QA-NEXT-DECISION.md)을 그대로 따른다. 성공하더라도 제한된 비교 진입 결과이며 일반 정확도·요약 성공·검색/ACL/revision/UI 통합·사용자 검수를 대신하지 않는다.
