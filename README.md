# DocTrail

**소규모 개발 조직을 위한 권한 기반 문서 검색과 근거 확인 서비스.**

화면은 **React + TypeScript + Vite**, 서비스 백엔드는 **Java 21 + Spring Boot**다. Python은 데이터 준비·학습·오프라인 평가와 선택적 검색·회의 분석·답변 모델 추론에 사용한다. 기존 Python 서비스와 동결 실험은 보존한다. [Java 전환 범위와 검증](docs/JAVA-MIGRATION.md), [React 선택 이유](docs/decisions/0003-react-frontend.md), [화면 구조와 검증 실행법](docs/FRONTEND.md)을 참고한다.

새 팀원이 온보딩·운영 문서에서 정보를 찾을 때, 볼 수 있는 문서의 어느 부분이 근거인지 확인하는 흐름을 만든다. 한국어·영어 문서를 대상으로 검색 기준선부터 임베딩·하이브리드·리랭킹·미세조정까지 비교하는 개인 AI Engineer 포트폴리오 프로젝트다.

## 현재 범위

후속 관계 근거 요약 후보를 기존 Python 모델 서비스에 연결했다. 관련 합성 회귀761개와 독립 코드 검토를 통과했으며 기존 Java·React 저장 계약과 기본 요약 방식은 유지한다. [연결 검증](experiments/results/meetings-grounded-summary-v2-service-v1.json)은 실제 모델 품질 개선이나 전체 완료의 증거가 아니다. [새 후보의 실제 비교](experiments/results/meetings-grounded-summary-development-v2.json)는 두 회의의 저장·근거 이동 뒤 세 번째 자동 근거 검토 거부로 실패했다. 유효 요약3개의 독립 내용 검토가 진행 중이며 질의응답6건은 미실행이다.

새 근거 연결 요약 방식의 실제 로컬 비교는 두 번째 분석의 자동 검토 거부로 종료됐다. 독립 AI 검토에서도 생성된 두 요약 모두 핵심 조건이나 시점을 충분히 담지 못했다. 인용 위치 확인과 내용 품질을 구분하고 [실행 실패](experiments/results/meetings-grounded-summary-development-v1.json)·[독립 판단](experiments/results/meetings-grounded-summary-review-v1.json)을 보존한다. 이 실행에서 질의응답6건은 미실행이다.

2026-10-23 기준, 문서·회의 관리와 검색/학습 실험은 실제로 연결했지만 **자연어 답변 품질과 1차 전체 완료는 미충족**이다. 기능별 완료 범위, 남은 순서와 일정의 불확실성은 [현재 진행 상황](docs/PROGRESS-OVERVIEW.md)에 따로 정리했다. 아래 기록의 도구 검증·합성 검사·CI 성공을 모델 품질이나 전체 완료로 해석하지 않는다.

평가 도구의64KiB 읽기 후보를 새 합성 Git 자료에서1회 비교했다. 같은 검증을 유지한 시작 경계12.531→10.969초, 전송직전3.141→2.047초를 관측했다. 고정순서 n=1·부하 미통제이므로 실제 서비스 성능이나 C5 성공 가능성으로 일반화하지 않는다. [원본·실측·한계](docs/MEETINGS-PROOF-EPOCH-RESULTS.md)를 보존했고, C6에 이 reader를 연결한 검증 도구를 구현했다. [구현·검사·동결](docs/MEETINGS-C6-IMPLEMENTATION.md)은 새 평가 자료와 실제 답변 품질 검증에 선행하는 단계다. 아직 C6 모델 평가나 서비스 채택은 하지 않았다.

C5는 GPU28 고정 실제 품질 실행에서 두 번째 요청 시간 초과로 종료됐다. [실제 결과](docs/MEETINGS-C5-QUALITY-RESULTS.md)는 전송2/구조 응답1/의미 판정0이며 나머지 calibration4·validation8은 실행하지 않았다. 모델 정답률이나 서비스 채택을 주장하지 않는다. [새 평가 원문12개](docs/MEETINGS-C5-SOURCES.md)를 먼저 확정하고 Java/Python 처리 일치와 독립 AI 검토를 마쳤다. 해시 중복이 없어도 의미가 비슷했던 validation 합성3개는 반려 원본을 보존하고 별도 버전으로 교체했다. 확정 자료와 최종 판정자 등록 커밋 aa7836c의 필수 CI는 통과했으며 [새 질문6/8개](docs/MEETINGS-C5-ITEMS.md)도 별도 AI 검토에서 수정 없이 수용됐다. [공식 입력 준비](docs/MEETINGS-C5-PREPARATION.md)도 두 split 모두 통과했지만 실제 생성에서는 위 시간 제한 실패가 발생했다. 사용자 검수0이다. 자료 검토·소프트웨어 검사와 실제 답변 품질을 구분한다.

최근 무료 로컬 자원 비교에서는 같은5064입력·521출력에서 GPU 배치 요청24→28의 전체시간71.485→63.453초를 관측했다. 각1회 고정순서이며 GPU28 종료시점 여유686MiB라 일반 성능·동시사용·답변 품질을 보장하지 않는다. [원본·실측·한계](docs/MEETINGS-GPU-PLACEMENT-RESULTS.md)를 남기고 서비스 기본값은 유지한다. 제품의 [회의 원문 접근·편집 복구](docs/MEETINGS-SOURCE-ACCESS-RECOVERY.md)는 실제 Java/React52개 검사로 확인했다.

최신 회의 확장은 실제 로컬 분석·관리·UI 흐름을 확인했지만 **자연어 답변 품질이 미달이라 1차 전체 완료는 아니다**. 무료·로컬 모델만 사용한다. 정확 인용 9/9와 의미 통과 2/4가 다르게 나온 실패, 보존한 원본, 다음 검증 경계는 [회의 결과](docs/MEETINGS-RESULTS.md)에 기록했다.

후속 주장 검토 방식도 정확 인용58/58과 별개로 전체 의미 기준0/4에 머물렀다. 문단 단위 C2의 별도 실행 역시 언어 오류로 중단됐으며, 정상 반환된7쌍의 사후 진단은 대조군과 후보 모두 완전 정답1/7이었다. 인용 문자열47/47일치가 답변 완전성을 보장하지 않았다. 이 진단은 모델 metadata에 노출된 AI 검토이며 완전 맹검 비교가 아니다. [C1 실패](docs/MEETINGS-C1-RESULTS.md)와 [C2 원본·진단·한계](docs/MEETINGS-C2-BUDGET-RESULTS.md)를 보존한다.

앞선 C3는 요구사항별 근거 계획 후 자연어로 답하는 두 단계 후보를 고정하고 실제6요청/9추론을 완료했다. 독립 최종답변 판정은2/6이며 정확 인용30/30과 의미 정확성은 달랐다. 검증 split 생성과 서비스 채택은 하지 않는다. [실제 C3 결과](docs/MEETINGS-C3-RESULTS.md), [실행·판정 계약](docs/MEETINGS-C3-EXECUTION-CONTRACT.md), [현재 상태](docs/STATUS.md)를 기준으로 완료 여부를 구분한다. 서비스에서는 AI 답변 오류 뒤 같은 질문과 필터로 [원문 검색을 이어가는 흐름](docs/MEETINGS-SEARCH-RECOVERY.md)을 실제 Java/React에서 확인했다.

C4의 단일 사고 경로는 새 자료로 실제 품질 평가를 시작했지만 두 번째 요청의90초 제한 초과로 종료했다. 전송2회 중 정상 파싱1개, 의미 판정0개이며 나머지 calibration4개와 validation8개는 실행하지 않았다. [실패 결과와 원본 기록](docs/MEETINGS-C4-QUALITY-RESULTS.md)을 보존하고 서비스에 채택하지 않는다. 앞선 [자원 검사 통과](docs/MEETINGS-C4-COMPAT-RESULTS.md)와 실제 답변 품질·시간 조건을 구분한다. 별도 합성 저장소의 [모델 없는 검증 비용 측정](docs/MEETINGS-HOST-PROOF-PROFILE-RESULTS.md)은7회 완료됐으며 재사용6회 중앙값2.933초였다. 이는 실제 C4 지연의 원인이나 서비스 성능을 입증한 결과가 아니다.

제품 화면에서는 접근이 거부된 회의의 오래된 작업 목록을 숨기고, 결정 연결 충돌 후 양쪽 회의를 다시 읽어 재선택하게 했다. 다른 회의 목록을 불러오지 못해도 현재 작성 중인 근거는 보존한다. [상세·연결 복구](docs/MEETINGS-DETAIL-RECOVERY.md)는 실제 Java 브라우저에서 검증했고, 모델 답변 품질과 사용자 검수 여부는 따로 기록한다.

문서 등록 → 검색 → 원문 근거 확인을 로컬에서 구현·검증했다. 로그인·작업공간·나만 보기 권한, 수정·삭제·재처리, 검색 기록·피드백도 실제 API에 연결했다. 기본 BM25 외에 E5 의미 검색·혼합·BGE 재정렬을 선택할 수 있으며 실제 로컬 GPU와 Java·React 연결을 합성 자료로 검증했다. 검색 임베딩의 제한 미세조정도 실제로 수행했다. [현재 상태](docs/STATUS.md), [모델 서비스 실행·한계](docs/MODEL-SERVING.md).

회의 기능은 텍스트 등록과 실제 Qwen 분류 기반 **AI 발췌 요약**, 결정·미해결·담당 작업의 원문 근거, 사용자 편집과 명시적 결정 변경 연결을 제공한다. 회의와 일반 문서를 함께 검색하고 실제 로컬 모델로 근거 답변을 생성하는 실험 경로를 추가했다. 작은 모델의 날짜·주체 혼동과 답변 누락을 성공으로 숨기지 않으며 [실제 실행·실패·완료 상태](docs/MEETINGS-RESULTS.md)를 별도로 공개한다. 녹음·STT·외부 회의 연동·외부 서비스 배포는 포함하지 않는다. [회의 실행·API·복구·시연](docs/MEETINGS-RUNBOOK.md), [자료 출처](docs/MEETINGS-DATA.md), [모델 방식과 한도](docs/MEETINGS-AI.md).

M2에서는 공개 한·영 문서 313개, AI 질문 초안 240개와 리비전 후 활성 질문 239개를 준비했다. 개발용 양성 질문 59개에서 top-5 청크의 필수 근거 완전 회수는 **30/59**, 주석상 교차 언어 질문은 **1/23**이었다. 사용자 검수는 0개이고 test 질문 성능은 열지 않았다. 이 실패를 출발점으로 검색 모델을 비교한다. [실측·실패 분석](experiments/README.md), [데이터 재현](data/README.md), [데이터 카드](docs/DATA-CARD.md)를 제공한다.

M3 첫 로컬 GPU 비교는 같은 입력에서 **BM25 30/59 → E5 임베딩 29/59 → 혼합 27/59 → 혼합+리랭커 36/59**였다. 나빠진 방법도 보존했다. 이 수치는 동결 Python 오프라인 dev 평가이며 Java 서비스 성능으로 재해석하지 않는다. [실행법](docs/M3-RUNBOOK.md)과 [비교 설계](docs/M3-DESIGN.md)를 참고한다.

후속 비교에서는 두 검색기의 후보를 같은 깊이로 읽고 중복을 제외해 50개를 채우는 정책을 사전 고정했다. 같은 BGE로 다시 순위를 매긴 결과 **37/59**로 1문항 회복·추가 퇴보 0문항이었다. 후보 자체에 모든 근거가 있는 질문도 38/59에 그쳐 누락 문제가 남았다. 기존 모델 입력의 잘림과 근거 토큰 보존을 따로 검사한 [후속 분석](docs/M3-CANDIDATE-ANALYSIS.md)에 개선·한계·재현 근거를 함께 남겼다. 모두 사용자 검수 전 dev 결과다.

M4에서는 원래 train 안에서 학습64·내부 검증16개의 AI 질문과 독립 검토를 준비했다. 대체 정답·모호한 후보·잘린 입력을 구분해 검토했고, 첫 GPU 수치 실패도 보존했다. 초기 loss scale만 바꾼 후속 probe를 통과한 뒤 E5 전체 가중치를16회 실제 갱신했다. [준비·실행·품질 기록](docs/M4-READINESS-RESULTS.md)과 [재현 실행법](docs/M4-RUNBOOK.md)에 성공·실패·한계를 함께 남긴다. 학습 완료와 검색 개선·서비스 채택은 별개다.

별도 사전 고정 dev 비교에서 새 E5 base→학습 저장본의 전체 근거 회수는 **후보50 기준34→47/59, 상위5 기준29→37/59**였다. @5에서14개 회복·6개 퇴보했으며, 다중 문서 질문은1→0/7로 나빠졌다. [사례와 한계](docs/M4-MAIN-DEV-ANALYSIS.md)를 보존했다. 사용자 검수0·test 잠금·서비스 미채택 상태이며, 공개 CI는 가중치 없이 저장 결과를 재생한다.

이 학습 저장본을 명시적 실험 실행기로 연결해 실제 Java·React·로컬 GPU 운영 검사16묶음도 통과했다. 모델별 검색 이력, 권한 회수, 문서 갱신·삭제, worker 장애와 기존 모델 복구를 확인했다. [운영 결과](docs/M4-OPERATIONS-RESULTS.md)를 보존하며 기본 BM25/base는 유지한다. 이 검증은 합성 자료를 사용했으며 새로운 검색 품질 평가나 사용자 검수를 뜻하지 않는다.

M5의 첫 로컬 생성 실험에서는 Qwen3-1.7B로 합성11질문을 실제 처리하고 빈 근거1개를 사전 차단했다. 첫 실행의 라이브러리 설정 덮어쓰기를 발견·보존한 뒤, 새 버전에서 실제 적용된 greedy 설정을 확인했다. **인용 검사를 통과한9답변 중3개는 질문 일부 누락·충돌 무시·모호한 대상 선택 문제**가 있었고 정상 모델 보류는0/4였다. [설정 실패와 답변 분석](docs/M5-GENERATION-ANALYSIS.md)을 공개하며, 이를 Java Q&A 기능 완료나 실사용 품질로 주장하지 않는다. [실행·재생 방법](docs/M5-RUNBOOK.md)을 참고한다.

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

## 라이선스와 사실 구분

프로젝트 코드는 MIT License다. 공개 문서·데이터셋은 각 원출처의 이용 조건을 따르며 코드의 MIT 라이선스로 재지정하지 않는다. 합성 예시와 공개 원문, 계획과 실측, 자동 검수와 사용자 검수를 구분한다. AI가 설계·구현·실험·문서 작성을 지원하며, 사용자의 직접 판단·검증은 별도로 기록한다.
