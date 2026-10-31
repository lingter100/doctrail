# 진행 상태

기준일: 2026-10-31. 사용자 지시 **“완성까지해”**로 재개했으며 goal과 기존 doctrail 자동 후속 실행을 ACTIVE로 확인했다. 2026-10-30의 일시정지는 과거 기록이다. 회의 지능형 관리 1차와 전체 포트폴리오는 미완료다.

## 현재 작업

요약 엔진 도구를 매번 다시 다운로드하지 않도록, **실패 원본을 보존한 별도 오프라인 검증 기능 `verify-closed`**를 구현한다. 실패 원본의 고정 목록·해시·blob·라이선스를 새 작업공간에서 검증·복사하고, 새 정상 종료와 별도의 수용 기록을 얻어야 기존 빌드로 연결한다. 실패한 raw 명세를 성공 명세로 바꾸지 않는다.

재개 시 준비 스크립트에는 347줄의 부분 변경이 있었고 검사 파일은 게시 HEAD와 같았다. 현재 구현자는 부분 작업과 기존 원본을 보존한 뒤 CLI·외부 수용·runtime origin 연결을 완성했다. [구현·검사 결과](../experiments/results/meetings-summary-offline-implementation-v1.json)는 81통과 후 Windows hardlink fixture 준비 실패1건을 수정해 해당1개가 통과한 고유82개다. 한 번의82개 전체 통과로 합치지 않는다. Ruff와 독립 Astra xhigh 검토(차단0·권고0)를 마쳤고 세 소스는 검사 사본과 같다. **실제 오프라인 실행·컴파일·모델 품질은 아직 미검증이다.**

- 담당: 도구가 수락한 `gpt-6-astra high` 에이전트 `offline_resume_impl`.
- 공개 소유 파일: `scripts/prepare_summary_grammar_engine.py`, `tests/test_summary_grammar_engine.py`, `tools/summary_grammar/runtime.py` 세 개. 오프라인 원본과 새 실행 기록의 직접 결합을 위해 runtime의 선택적 origin 전달만 추가 배정했다. 기존 online·legacy·build 동작은 유지한다. 부모는 문서·공개 결과·Git 게시 담당이다.
- 로컬 구현 기록: `.local/meeting-summary-engine-offline-resume-v1`; 중단 전 사본은 `.local/meeting-summary-engine-offline-implementation-v1`에 보존한다.
- 수용된 설계: `.local/meeting-summary-engine-after-v8-diagnosis-v1/DIAGNOSIS.md`. 새로운 설계·승인 문서 사슬을 만들지 않고 이 범위에서 마무리한다.
- 현재 source3는 검토 후 동결했다. 같은 구현자는 별도 `.local/meeting-summary-engine-offline-observer-preparation-v1`에서 기존 외부 관찰 도구의 offline 후보·작은 합성 검사만 준비한다. 미래 실제 참조는 placeholder이며 실제 input binding·WORK·once는 만들지 않는다. 실제 과거 payload 전체 조사·복사, 다운로드, 컴파일, native·모델 실행도 아직 하지 않는다.
- 다음: 집중 검사·독립 변경 검토 → 검증된 소스와 대기 문서를 한 번에 게시 → 해당 소스의 필수 CI → 별도 실제 오프라인 검증 → 수용 후 빌드·문법 엔진 확인.

## 마지막 실제 실행과 확인된 원인 범위

[v8 실측](../experiments/results/meetings-summary-engine-v8-acquisition-v1.json)은 **전체 취득 실패**다. 소스 1,687개를 준비하고 raw 명세를 썼지만 최종 acquisition.json을 게시하지 못했다. 내부 worker는 정상 종료했고, 외부 CLI는 시간 경계에서 강제 종료15·자연 종료 미관측으로 남았다. 전체 wrapper 시간은1810.985초다.

13개 단계의 END와 manifest END1733.469초, 내부 supervisor1783.172초를 확인했다. 고정 소스 제어흐름과 raw의 CMake 모듈 해시·61행을 근거로 이전 위치 오류의 정적 검사 통과를 추론할 수 있다. native 실행이나 전체 성공의 증거는 아니다. 정확한 중단 행·단일 성능 원인은 미확정이고 내부·외부 scan 시간은 겹치므로 합산하지 않는다.

15,675파일·845,711,438바이트와 고정461행을 보존했다. 알려진 소유 신원은 부재이며 실행·관찰 세션은 닫혔다. 초기 경로 표기 비교4건도 원본을 유지하고 별도 정정했다. 부모 closeout `aca783e9…`로 실행 중 HOLD를 해제했다. 닫힌 v3~v8와 소모된 once는 재실행·덮어쓰기하지 않는다.

## 제품과 AI의 완료 범위

| 영역 | 확인한 범위 | 남은 완료 조건 |
| --- | --- | --- |
| 문서 서비스 | Java/React 로그인·작업공간·권한·문서 등록/변경/삭제·검색·원문 근거·기록·피드백 | 실제 모델을 포함한 최종 회귀와 새 환경 실행 |
| 회의 관리 | 텍스트 등록, 결정 변경 연결, 담당 작업·항목·근거 편집과 충돌 보호 | 실제 AI 요약·추출 품질과 실제 자료의 최종 흐름 |
| 검색 모델 | BM25·임베딩·혼합·리랭커 비교, 도메인 임베딩 미세조정과 서비스 연결 | 격리 최종 평가·사용자 검수·기본 채택 판단 |
| 자연어 답변 | 실제 로컬 호출, 인용 복원·답변 보류·오류 처리 | 충분한 답변·근거 지지·적절한 보류의 독립 품질 수용 |
| 화면·운영 | 실제 Java와 합성 응답을 포함한 브라우저 회귀, 백업·복원 | 실제 모델의 전체 화면 흐름, 외관·사용성 검수, 최종 운영 검증 |
| 포트폴리오 | 설계·실험·실패·실행법, 소개·면접·시연 초안 | 최종 비교·시연과 사용자의 직접 판단·설명 확인 |

[최신 QA 비교](MEETINGS-FREE-QA-PAIRED-V3-RESULTS.md)는 기준·후보 모두 독립 AI 내용 수용 **0/6**으로 종료됐다. 작은 개발 비교이며 일반 정확도나 사람 검수가 아니다. 입력·출력 한도 거절과 정상 종료 후 의미 오류를 분리한다. 원문 중복과 인용문 출력은 이미 줄였으므로 길이 변경만으로 내용 문제가 해결된다고 가정하지 않는다. 같은6개·닫힌C1~C5/v7 재튜닝·자동 모델/프롬프트 탐색을 하지 않는다. 새로운 QA 개입의 근거는 별도로 필요하며 요약 엔진 작업을 기다리게 하지 않는다.

## Git와 검증 상태

마지막 게시 소스는 `0a9819e26f4320dedc76aa3d219b52a23a5936b8`, 브랜치는 `feat/meeting-intelligence`, [PR14](https://github.com/lingter100/doctrail/pull/14)는 마지막 확인 시 draft다. 사용자 `lingter100`의 author/committer로 게시했다. 새 부분 구현은 미커밋이며 이 CI에 포함되지 않는다.

[0a 필수 CI 기록](../experiments/results/meetings-summary-optional-probe-ci-v1.json): push41021278586·PR41021284378의 backend/web/java-service 모두 통과. Python5532통과·21제외, 각 브라우저158통과, 실제 Java HTTP/DB11개와 합성 회의 운영 검사를 구분한다. 같은 관찰 세션은 종료됐고 통과 검사를 반복하지 않는다. CI 통과는 AI 내용 품질 증명이 아니다.

대기 중인 변경은 현재 구현, v8 실제 실패 결과, 이전 CI 결과, README·시연·진행·결정·기여 문서다. 검증 후 명시한 파일만 묶어 게시한다. `data/meetings/`, `.local`, 모델·DB·개인 자료는 Git에 넣지 않는다. 미검증 회의1차를 main에 통합하지 않는다.

## 실행과 보존 경계

- 사용자 화면 실행은 [README](../README.md), 회의 모델 준비는 [회의 실행 안내](MEETINGS-RUNBOOK.md), 현재 확인 가능한 시연은 [시연 문서](DEMO.md)를 따른다. 시연 초안을 실제 수행으로 기록하지 않는다.
- 본 실행 환경의 집중 Python 검사는 기존 `.local/meeting-qa-inference-python312-v1/venv/Scripts/python.exe`를 사용한다. 오래된 `.venv` Python은 연결 문제가 있었으므로 새 동기화·설치 없이 기존 확인 환경을 사용한다. 이 로컬 선택을 공개 설치 조건으로 일반화하지 않는다.
- 부모·구현자·기술 검토자는 비공개 QA 질문·기준·출력·개별 판정의 내용을 읽지 않는다. 공개 집계와 불투명한 해시·ID만 확인한다. 격리 validation·최종 test와 M5-A/B·M4 후보의 원래 개방 조건을 유지한다.
- 무료·로컬만 사용한다. 유료 API·GPU 임대·클라우드·크레딧과 공개 서비스 배포는 실행하지 않는다. 소스 게시와 사용자 명의 Git 작업은 승인된 범위다.
- 녹음·STT·실시간·외부 회의 연동은 1차 완료 후다. 사용자 검수·피드백·성과를 AI가 대신 만들어 기록하지 않는다.
- 완료율·완료일을 산정할 근거는 없다. 요약 도구 검증 → 실제 요약·답변 품질 수용 → 실제 모델을 포함한 전체 흐름·운영·최종 시연을 각각 확인한다. 일부 실패나 한 단계 완료로 전체 goal을 종료하지 않는다.

## 기록 안내

기능별 설명은 [진행 개요](PROGRESS-OVERVIEW.md), 이유와 대안은 [결정](DECISIONS.md), AI 지원·사용자 확인 구분은 [기여](CONTRIBUTIONS.md), 전체 요구는 [회의 설계](MEETINGS-DESIGN.md)에 있다.

이전 STATUS 전체는 [2026-10-31 보관본](STATUS-2026-10-31-archive.md)에 원본 바이트 그대로 보존했다. SHA256: `1b427423a3a56b48b5d00ce862c09b2cd4e17436144bdd5bd47ebf35795da7a1`. 과거 ACTIVE/PAUSED·소유권·중간 결과는 당시 이력이며 현재 지시로 다시 실행하지 않는다. 상세 오류·해시가 필요할 때 해당 기록만 검색한다.
