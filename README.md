# DocTrail

**소규모 개발 조직의 문서와 회의에서 정보를 찾고, 원문 근거와 결정 변경을 확인하는 서비스.**

React·TypeScript·Vite 화면, Java 21·Spring Boot 서비스, Python 데이터·학습·평가·로컬 추론으로 구성한다. Notion·Confluence의 익숙한 문서 탐색 구조를 참고한 개인 AI Engineer 포트폴리오 프로젝트다. 한국어·영어 문서를 다룬다.

## 현재 사용할 수 있는 흐름

| 사용 흐름 | 구현·확인한 범위 |
| --- | --- |
| 문서 등록과 검색 | 로그인·작업공간·접근 권한, TXT/Markdown/PDF 등록·수정·삭제·재처리, 검색 결과에서 원문 근거와 버전 확인 |
| 회의 결정과 작업 관리 | 텍스트 회의 등록, 결정 변경의 명시적 연결, 담당자·기한·상태 편집, 분석 항목과 근거 보정 |
| 자료를 함께 탐색 | 회의·일반 문서 통합 검색, 질문 기록·피드백, 권한·문서 갱신에 따른 근거 재검사 |
| AI 실험과 운영 | 검색 기준선·임베딩·혼합·리랭커·도메인 미세조정 비교, 실제 로컬 AI 호출, 오류·재처리·백업·복원 검증 |

**회의 지능형 관리 1차와 전체 포트폴리오는 미완료다.** 관리·검색 기능의 동작과 AI 내용 품질을 구분한다. 실제 로컬 요약·답변은 연결했지만 정보 누락·근거와 주장의 불일치·잘못된 답변 보류가 남았다. 최근 두 모델의 같은 6문항 개발 비교는 독립 AI 내용 수용이 모두 **0/6**이어서 후보를 채택하지 않았다. 이 작은 비교를 일반 정확도나 사람 평가로 해석하지 않는다.

게시 소스 `0a9819e`의 push·PR 필수 CI가 모두 통과했다. [회귀 기록](experiments/results/meetings-summary-optional-probe-ci-v1.json)은 Python 5,532개 통과·21개 제외, 각 브라우저 158개 통과, 실제 Java HTTP·DB 검사와 합성 회의 운영 검사를 구분한다. 합성 모델 응답을 사용한 화면 검사는 실제 AI 품질의 증거가 아니다.

## 프로젝트에서 설명할 핵심

- **검색을 단계별로 비교한다.** [검색 실험과 실패 분석](docs/M3-ANALYSIS.md), [학습 설계](docs/M4-DESIGN.md)에 데이터 출처·분할·후보 누락·미세조정 선택을 기록한다. 학습 후보의 기본 채택과 격리 최종 평가는 남아 있다.
- **인용 일치와 답변의 충분성을 따로 평가한다.** [최신 로컬 QA 결과](docs/MEETINGS-FREE-QA-PAIRED-V3-RESULTS.md)에 자동 거절·내용 실패·평가 분모를 남겼다. 실패한 출력이나 평가 조건을 성공처럼 고치지 않는다.
- **문서가 바뀌고 권한이 달라져도 근거를 확인한다.** [회의 편집 검증](docs/MEETINGS-MANUAL-CORRECTION-VERIFICATION.md), [백업·복원 검증](docs/MEETINGS-RESTORE-VERIFICATION.md)은 실제 저장·권한·충돌 처리와 모델 품질을 구분한다.

현재는 로컬 요약 도구의 실제 실행 환경을 검증하고 있다. [마지막 취득 실패](experiments/results/meetings-summary-engine-v7-acquisition-v1.json)에서 발견한 [고정 CMake 위치 오류](docs/MEETINGS-SUMMARY-OPTIONAL-PROBE.md)는 수정·집중 검사·필수 CI를 마쳤다. 이후 [v8 실행](experiments/results/meetings-summary-engine-v8-acquisition-v1.json)은 내부 명세 작성까지 끝났지만 최종 게시 전 시간 한도로 실패했다. 원본을 보존하고 이미 확보한 파일을 새 작업공간에서 검증하는 [오프라인 경로](experiments/results/meetings-summary-offline-implementation-v1.json)를 구현해 집중 검사와 독립 코드 검토를 마쳤다. 필수 CI와 실제 오프라인 실행은 별도로 확인한다. 전체 도구 준비·컴파일·문법 엔진 검사와 새 요약 품질은 아직 검증 전이다. 이전 시도와 한계는 [실험 기록](experiments/README.md)에 보존한다.

기능별 남은 일은 [진행 상황](docs/PROGRESS-OVERVIEW.md), 실행 시연은 [시연 안내](docs/DEMO.md), 확인된 경험의 설명은 [포트폴리오 초안](docs/PORTFOLIO-DRAFT.md)·[면접 초안](docs/INTERVIEW-DRAFT.md)에 있다. 사용자 직접 검수·최종 시연·공개 서비스 배포는 완료하지 않았다. 녹음·STT·외부 회의 연동은 2차 범위다.

![로컬 검증 화면: 합성 온보딩 문서 검색과 원문 근거](docs/images/m1-desktop.jpg)

## 시작하기

서비스 실행에는 Java 21과 Node.js 22.12 이상이 필요하다. CI는 Node.js 24를 사용한다. Maven 3.9.16은 저장소 wrapper가 내려받아 체크섬을 확인한다. AI 데이터·실험과 이전 Python 구현의 검증에는 Python 3.11과 [uv](https://docs.astral.sh/uv/)를 사용한다.

Windows에서는 저장소 루트에서 `./scripts/start.ps1` 한 번으로 설치·빌드·실행할 수 있다. 수동 실행은 다음과 같다.

```powershell
cd web
npm ci
npm run build
cd ..
./server/mvnw.cmd -B -f server/pom.xml verify
java -jar server/target/doctrail-server-0.1.0.jar
```

브라우저에서 `http://127.0.0.1:8000`을 열고 계정과 작업공간을 만든다. Markdown, UTF-8 텍스트, 텍스트가 포함된 PDF를 등록하고 검색한다. Java 기본 DB는 `var/doctrail-java.sqlite3`이며 기존 Python DB를 자동으로 옮기거나 덮어쓰지 않는다. 기본 계정이나 고정 비밀번호는 없다. macOS/Linux에서는 위의 `mvnw.cmd` 대신 `mvnw`를 사용한다.

이전 구현은 `./scripts/start.ps1 -Backend Python`으로 실행한다. AI 실험 실행법은 [M3-RUNBOOK](docs/M3-RUNBOOK.md)을 따른다. 두 서비스를 같은 포트·같은 DB에 동시에 실행하지 않는다.

회의 AI와 Q&A는 위 빌드 후 고정 로컬 Qwen 가중치와 retrieval 의존성을 준비하고 `uv run --locked --group retrieval --no-sync python -m scripts.serve_meetings --port 8000`으로 실행한다. `--retrieval`을 추가하면 E5/BGE는 CPU에서 함께 실행한다. 일반 Java 실행만으로는 모델이 연결되지 않으며 AI 실패 상태를 표시한다. 정확한 준비 조건·대안·한도는 [회의 운영 안내](docs/MEETINGS-RUNBOOK.md)를 따른다.

개발 중에는 API 서버와 별도로 `web/`에서 `npm run dev`를 실행한다. 프런트엔드 개발 서버가 `/api`를 로컬 API 서버로 전달한다.

## 검증

```powershell
./server/mvnw.cmd -B -f server/pom.xml verify
uv run --group retrieval pytest
uv run --group retrieval python -m scripts.verify_java_service --output .local/java-check.json
cd web
npm run typecheck
npm run build
```

브라우저 회귀 검사는 **프런트엔드 빌드 → Java JAR 재패키징**을 먼저 마친 뒤 `web/`에서 `npx playwright install chromium`, `npm run test:e2e`로 실행한다. 별도의 합성 DB와 로컬 임시 포트를 사용한다. [검증 범위와 실행법](docs/FRONTEND.md)을 참고한다.

## 문서

- [제품과 사용자 문제](docs/product.md), [기존 서비스·채용 조사](docs/research.md)
- [구조](docs/architecture.md), [데이터·평가 설계](docs/data-evaluation.md), [단계별 완료 기준](docs/roadmap.md)
- [API 계약](docs/API-CONTRACT.md), [결정 기록](docs/DECISIONS.md)
- [Git 협업 규칙](CONTRIBUTING.md), [AI와 사용자 기여 기록](docs/CONTRIBUTIONS.md)
- [실험 실행·실패 분석](experiments/README.md), [운영·복구](docs/OPERATIONS.md), [시연·면접 준비](docs/DEMO.md)
- [M2 평가 계약](docs/M2-EVALUATION.md), [직접 검수와 면접 설명](docs/M2-LEARNING.md)
- [M3 비교 설계](docs/M3-DESIGN.md), [실측과 실패 분석](docs/M3-ANALYSIS.md), [모델 실행](docs/M3-RUNBOOK.md)
- [후보 선택 후속 설계](docs/M3-CANDIDATE-DESIGN.md), [후속 실측·토큰 잘림 분석](docs/M3-CANDIDATE-ANALYSIS.md)
- [Java 서비스 전환](docs/JAVA-MIGRATION.md), [Java 선택 ADR](docs/decisions/0002-java-service.md)
- [React 화면 구조·검증](docs/FRONTEND.md), [React 선택 ADR](docs/decisions/0003-react-frontend.md)
- [Java·Python 모델 연결과 실행](docs/MODEL-SERVING.md), [추론 경계 ADR](docs/decisions/0004-model-serving.md), [실제 로컬 GPU 운영 검사](experiments/results/m3-model-service-v1.json)
- [M4 학습 가설·데이터 기준](docs/M4-DESIGN.md), [train 자료와 재현 방법](data/training/README.md)
- [M5 답변·보류 설계](docs/M5-DESIGN.md), [생성 실측·실패 분석](docs/M5-GENERATION-ANALYSIS.md), [실행·재생](docs/M5-RUNBOOK.md)
- [M5-B 새 자료·정책 비교 사전등록](docs/M5-CALIBRATION-PLAN.md), [자료 준비 검증·한계](docs/M5B-PREPARATION.md)
- [자동 후속 실행과 승인 경계](docs/AUTONOMY.md)
- [회의 확장 설계](docs/MEETINGS-DESIGN.md), [API·실행·복구](docs/MEETINGS-RUNBOOK.md), [실제 결과·한계](docs/MEETINGS-RESULTS.md)
- [통합 기록·피드백 검증](docs/MEETINGS-KNOWLEDGE-HISTORY-VERIFICATION.md), [회의 수동 보정 계획](docs/MEETINGS-MANUAL-CORRECTION-PLAN.md), [실제 보정 검증](docs/MEETINGS-MANUAL-CORRECTION-VERIFICATION.md)
- [요약 엔진 검증 도구](docs/MEETINGS-SUMMARY-ENGINE-PREPARATION.md), [새 무료 QA 준비 계약](docs/MEETINGS-FREE-QA-PREPARATION-PLAN.md)

- [무료 QA 비교 구현 계획](docs/MEETINGS-FREE-QA-ADAPTER-PLAN.md)

## 라이선스와 사실 구분

프로젝트 코드는 MIT License다. 공개 문서·데이터셋은 각 원출처의 이용 조건을 따르며 코드의 MIT 라이선스로 재지정하지 않는다. 합성 예시와 공개 원문, 계획과 실측, 자동 검수와 사용자 검수를 구분한다. AI가 설계·구현·실험·문서 작성을 지원하며, 사용자의 직접 판단·검증은 별도로 기록한다.
