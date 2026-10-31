# 진행 상태

기준일: 2026-10-31. 사용자의 **“완성까지해”** 지시로 재개했으며 goal과 자동 후속 실행은 ACTIVE다. **문서·회의 관리와 화면은 연결했지만, 로컬 AI 요약·답변 품질 및 최종 운영 검증이 남아 있다.** 전체 목표는 미완료다.

**게시:** 사용자 계정 `lingter100`의 작성자·커미터로 `48448bb`를 기능 브랜치에 push하고 [PR14](https://github.com/lingter100/doctrail/pull/14)에 연결했다. 게시 순간20파일의 작업본/Git 바이트와 원격 계정 연결을 확인했다. [정확한 push·PR 필수 CI](../experiments/results/meetings-evidence-plan-ci-v1.json)는 모두 성공했다. 각각 Python6,065개·21제외·브라우저162개(실패/인프라 오류/누락0)와 Java HTTP/운영/웹·동결 파일 검사가 통과했다. 새 질문 범위 참조·안건 추출 작업은 이 CI에 포함되지 않는 미게시 변경이다. PR은 draft이며 모델 채택·통합하지 않았다.

**새 후보 실측:** 사용자 명의 `8bd4104`의 [필수 CI](../experiments/results/meetings-structured-ci-v1.json)는 모두 통과했지만, [첫 실제 회의 분석](../experiments/results/meetings-structured-service-v1.json)은 실패했다. 모델/Java는 준비됐고 분류46회 다음 요약564토큰을 생성했으나 입력 계산3,068/3,069 불일치로 거절됐다. 뒤의 분석1회·답변2회는 실행하지 않았다. 실패·원본 출력·정리·77고정 참조를 보존했으며 원인을 독립 검토한다. [PR14](https://github.com/lingter100/doctrail/pull/14)는 draft다. CI는 각각 Python5,922개·브라우저162개와 Java/운영/웹/동결 파일 검사가 통과한 결과이며 실제 AI 품질 성공으로 해석하지 않는다.

**현재 단계:** [요청 계약 비교](../experiments/results/meetings-qa-request-contract-v1.json)는 기술2/2·내용0/2, [근거 계획v1](../experiments/results/meetings-evidence-plan-service-v1.json)은 질문 구절 검증 실패로 닫혔다. [범위 참조v2](../experiments/results/meetings-evidence-scope-service-v1.json)는 계획 형식은 통과했지만 의무3개/근거2행으로 실패했다. 독립 진단에서도 계획의 범위·시점·종류와 두 주장의 근거가 잘못돼 구조만 고쳐 자동 반복하지 않는다. 두 번째 질문·전이6문항은 미실행이다. 다음 QA 접근의 근거를 검토하면서, 별도 회의 전체 요약/작업 모듈의 집중 검사·귀속 오류 수정·독립 코드 검토를 마치고 실제 연결을 준비한다. 사용자 검수0·기본 모델 미채택이다.

**보존한 실패:** [5d164212 CI](../experiments/results/meetings-startup-source-ci-v1.json)의 동결 추론 파일 충돌은 원본 복원과 별도 개발 진입점으로 해결했다. [실제 검색v5](../experiments/results/meetings-qa-retrieval-development-v5.json)의 시작 실패는 Windows 사용자 이름 변수를 보존해 해결했다. 과거 기준·검증기·실패 결과를 수정하지 않았다.

## 현재 검증된 결과

- [새 구조화 후보와 인접 문맥 구현](../experiments/results/meetings-structured-implementation-v1.json): Python 가상49개·Java 집중68개·HTTP 검증기22개와 Ruff, 독립 코드 검토·화면 빌드·새 Java 패키징을 마쳤다. 게시8bd4104의 필수 CI는 성공했지만 이후 실제 첫 요약은 실패했다. 검사 통과와 모델 내용 품질을 구분한다.

- [실제 검색v6](../experiments/results/meetings-qa-retrieval-development-v6.json): 공개 문서3개·청크13개를 등록하고 두 질문의 BM25/dense/hybrid 총6요청이 모두200으로 완료됐다. 로컬 E5/BGE 준비와 Java 연결, 관련11프로세스 종료를 확인했다. 전체21.781초이며 공유 캐시·다른 프로젝트가 실행 중인 호스트의 관측이다. 생성/분석0회로, 내용 품질을 증명하지 않는다. 독립 AI가 필수 사실의 회수 여부를 검토하며 새 구조화 요약/답변 후보를 구현한다.

진행 경로를 좁혔다. 회의1차 완료에는 정확한 요약·근거·권한·실제 화면 흐름이 필요하며 자체 C++ 문법 검사기 제작은 필수 기능이 아니다. 독립 Astra xhigh 설계 검토에 따라 기존 로컬 실행기의 JSON-schema 경로를 새 서비스 후보로 연결한다. 직접 빌드 실험의 준비v6는 미실행으로 보존하고, 그 실험의 실패·검증 기준을 바꾸거나 통과로 대체하지 않는다. 구조 제한은 내용 정확성의 증거가 아니므로 실제 공개 회의 자료와 독립 내용 검토를 유지한다.

- 사용자 계정 `lingter100`의 `3efa1d12`·`724eb907`을 `feat/meeting-intelligence`에 게시했다. author/committer와19파일의 Git 일치를 확인했다. [PR14](https://github.com/lingter100/doctrail/pull/14)는 draft다.
- [정확한724 필수 CI](../experiments/results/meetings-ninja-ui-ci-v1.json)는 push·PR 모두 backend/web/java-service 통과로 종료했다. 각각 Python5,809통과·21제외, 브라우저162통과·실패/인프라 오류/누락0과 Java/운영/프런트 빌드를 확인했다. 이는 모델 의미 품질의 증거가 아니다.
- [회의 분석 실패 화면 수정](../experiments/results/meetings-ui-analysis-visibility-v1.json)은 타입 검사·빌드·Java 패키징과 집중 브라우저6개를 통과했다.1440/390px에서 잘못된 AI 초안/추출0개 표시 제거를 확인했다. AI 시각 검토이며 사용자 검수가 아니다.
- [오프라인 도구 준비](../experiments/results/meetings-summary-offline-acquisition-v1.json)는 실제 정상 종료했다. 이후 [native v4](../experiments/results/meetings-summary-compat-build-v4.json)는 Ninja의 Windows 셸 호출 제한에서215.906초 후 실패했다. 관련27프로세스와 이번 작업 소유 임시 드라이브 정리를 확인했다. 원본·실패는 보존했다.
- [Ninja 셸 보정](../experiments/results/meetings-summary-ninja-shell-repair-v1.json)은 집중56개·Ruff·독립 Astra xhigh 검토를 통과하고 게시됐다. 실제 컴파일·문법 검사·생성 요약 성공은 아직 확인하지 않았다.

## 진행 중인 다음 작업

1. 새 QA 후보의 구현·집중 검사·독립 코드 검토 후 같은 공개 개발 두 질문을 한 번 실행한다. 기존 순위/인접 문맥·원문/질문/기준은 유지하고 실제 확장 입력·중간 결과를 로컬 개발 산출물로 남긴다. 일반 운영 로그에는 원문을 남기지 않는다.
2. 두 질문 모두 의미 기준을 충족할 때만 독립 출처6문항으로 전이를 확인한다. 검증 실패·잘못된 계획/근거 판단·지연·토큰과 자원을 기록하며 자료를 고쳐 통과시키거나 실패한 실행을 반복하지 않는다.
3. 회의 요약의 안건 경계·담당자·제안/확정·작업 누락을 해결하고 실제 회의 등록·요약·작업·답변·근거 열기 전체를 독립 검토한다. 현재 저장된 두 요약의 독립 수용0/2와 같은 모델의 잘못된 수용 사례를 보존한다.
4. 개발 품질 수용 후 격리 검증·최종 평가, 실제 모델 포함 UI/권한/수정·삭제/복구/새 환경 실행을 마치고 최종 시연·포트폴리오를 완성한다.

## 기능별 완료 경계

| 영역 | 확인한 범위 | 남은 완료 조건 |
| --- | --- | --- |
| 문서 서비스 | Java/React 로그인·작업공간·권한·등록/변경/삭제·검색·원문·기록·피드백 | 실제 모델 포함 최종 회귀·새 환경 실행 |
| 회의 관리 | 텍스트 등록·결정 변경 연결·담당 작업/항목/근거 편집·충돌 보호 | 실제 AI 요약·추출 품질·실제 자료 최종 흐름 |
| 검색 모델 | BM25·임베딩·혼합·리랭커 비교·도메인 미세조정 실험·서비스 연결 | 격리 최종 평가·사용자 검수·기본 채택 판단 |
| 자연어 답변 | 로컬 호출·인용·답변 보류·오류 처리 | 충분한 답변·근거 지지·적절한 보류의 품질 수용 |
| 화면·운영 | 실제 Java/합성 응답 브라우저 회귀·백업·복원 | 실제 모델 전체 흐름·사용성 검수·최종 운영 검증 |
| 포트폴리오 | 설계·실험·실패·실행법·소개/면접/시연 초안 | 최종 비교·시연·사용자 직접 판단 기록 |

[닫힌 QA 비교](MEETINGS-FREE-QA-PAIRED-V3-RESULTS.md)의 독립 AI 내용 수용은 기준·후보 모두0/6이다. 재실행·재채점·같은 질문 튜닝을 하지 않는다. 새 공개 OpenSearch2질문은 개발 자료이며 최종 평가가 아니다. M4 학습 모델은 실험적 상태이고 기본 BM25/base를 바꾸지 않았다.

## 실행·보존·기여

- [README](../README.md), [회의 실행 안내](MEETINGS-RUNBOOK.md), [시연](DEMO.md)을 따른다. 시나리오와 실제 수행 결과를 구분한다.
- 부모·구현자·기술 검토자는 비공개 QA 질문/기준/출력/개별 판정을 읽지 않는다. M5-A/B·격리 validation·최종 test의 원래 개방 조건을 유지한다.
- 무료·로컬만 사용한다. 사용자 계정 소스 게시·PR은 승인 범위이며 공개 서비스 배포는 별도 승인 사항이다. 사용자 검수·피드백·성과를 AI가 만들지 않는다.
- 녹음·STT·실시간·외부 회의 연동은1차 완료 후다. `.local`, `data/meetings/`, 모델·DB·개인 자료를 게시하지 않는다.
- 현재 실제 실행 소유자·고정 해시·프로세스 상태는 [AGENTS](../AGENTS.md)의 짧은 체크포인트를 따른다. 같은 CI·닫힌 모델 실험을 반복하지 않는다.
- [진행 개요](PROGRESS-OVERVIEW.md), [결정](DECISIONS.md), [AI/사용자 기여](CONTRIBUTIONS.md), [완료 기준](MEETINGS-DESIGN.md)을 분리해 기록한다. 한 단계 완료/실패로 전체 goal을 종료하지 않는다.

## 과거 기록

이번 정리 전 STATUS는 [보관본](history/STATUS-2026-10-31-before-current-summary.md)에 원본 바이트 그대로 보존했다. 더 이른 기록은 [기존 보관본](STATUS-2026-10-31-archive.md)에 있다. 과거의 시작 전/진행 중/PAUSED 문구는 당시 상태이며 현재 상태로 해석하지 않는다. 현재 문서는 최신 결과와 다음 작업만 유지한다.
