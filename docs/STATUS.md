# 진행 상태

기준일: 2026-10-12 (Asia/Seoul).

현재 단계: **M4 train 전용 자료 pilot을 만들고, AI 질문78개(학습64·내부 검증14)의 원문·분할·독립 AI 의미 검토와 결정적 재현을 확인했다.** E5 학습을 첫 가설로 정했지만 아직 학습하지 않았다. 검증 질문2개 부족, 미검토 음성 후보, tokenizer 근거 보존 검사와 실제 자원 probe가 남아 있다. Java 21/Spring Boot·React/TypeScript/Vite의 선택적 모델 검색은 이전 단계에서 검증했다. Python은 추론·데이터·학습·오프라인 평가를 맡고 동결 M2/M3와 이전 서비스를 보존한다. 사용자 질문 검수0·생성 답변0이며 전체 프로젝트 완료나 검색 품질 달성을 뜻하지 않는다. 원격 CI 상태는 각 단계의 실행 기록을 따른다.

선행 확인: 빈 작업 폴더, 별도 상위 프로젝트 지침 없음, GitHub 사용자 인증 확인, Python 3.11·Node·uv 사용 가능, RAM 약 32GB·RTX 4050 6GB 확인. Docker 명령은 설치되어 있으나 엔진은 실행 중이지 않음. 첫 단계는 Docker 없이 실행한다.

## M1에서 구현·검증한 범위

- 계정·세션·작업공간, 워크스페이스/개인 문서 권한, TXT·MD·텍스트 PDF 업로드, 본문·청크 저장.
- BM25 검색 전에 권한 필터를 적용한다. 원문 구절·PDF 페이지·리비전 확인, 수정·삭제와 검색 반영, 실패 이유·재처리, 개인 검색 기록·피드백.
- 자동 테스트 36개 통과. 로그인·권한·변경·삭제·재처리·Unicode/PDF 근거·내용 없는 로그·백업 복구·평가 입력 드리프트·분할 누출 거부를 포함한다.
- 프런트엔드 타입 검사·빌드 통과. 실행 시점 npm audit 0 vulnerabilities.
- 브라우저에서 로컬 검증용 계정 생성 → 합성 문서 업로드 → 검색 → 원문 확인 → v2 수정 → 새 내용 검색 → 피드백을 실제 수행했다. 데스크톱과 390px 화면을 확인했고 모바일 가로 넘침은 없었다. AI가 수행한 점검이며 사용자 검수는 아니다.
- 실제 로컬 서버를 중지·재시작한 뒤 브라우저에서 v2 문서와 개인 검색 기록의 유지를 확인했다.
- 공개 Kubernetes 문서 8개와 AI 작성 smoke 질문 12개를 처리·평가했다. [실측·실패 분석](../experiments/README.md)을 참고한다. 사용자 검수 질문은 0개다.

## 원격·공개 상태

- [공개 저장소](https://github.com/lingter100/doctrail), [M1 PR](https://github.com/lingter100/doctrail/pull/1).
- GitHub API에서 커밋 작성자·커미터 계정이 모두 `lingter100`에 연결되는 것을 확인했다.
- main 필수 검사·선형 이력·강제 푸시/삭제 금지를 설정했다. 통합 규칙은 CONTRIBUTING을 따른다.
- GitHub Actions: 구현 커밋 `357be1a`의 backend/web 검사 모두 [원격 통과](https://github.com/lingter100/doctrail/actions/runs/38196203926). 이후 문서 커밋과 main 통합 상태는 GitHub의 해당 SHA 검사 결과를 기준으로 확인한다.
- 서비스는 로컬에서만 검증했다. 외부 서비스 배포·유료 API·클라우드·GPU 임대는 하지 않았다.

## M1 당시 한계

BM25의 한국어 bigram·어휘 일치는 의미와 답변 가능성을 판단하지 못한다. PDF OCR·원본 레이아웃 편집·파서 프로세스 격리는 없다. 파싱은 동기식이며 검색마다 허용된 코퍼스를 토큰화한다. 1,000문서 부하·GPU 실행·임베딩·리랭커·학습·생성 답변은 아직 검증하지 않았다. Starlette TestClient의 httpx 연동에 deprecation warning 1개가 있으며 현재 테스트는 통과한다.

## M1에서 정한 후속 작업

1. M2: 공개 자료 약 1,000문서를 검토하되 문서 계열·번역·버전 수량을 별도로 센다. 포함 정의·파싱 결함을 검수한다.
2. Train 문서 계열과 dev/test 계열을 먼저 분리하고 학습 질문과 평가 240질문 목표를 별도로 준비한다. AI 작성·자동 검수·사용자 검수 상태를 보존한다.
3. 실패 유형별 BM25 기준선을 고정한 뒤 임베딩·하이브리드·리랭킹을 비교한다. 로컬 GPU 메모리·시간을 확인한 뒤 학습 대상을 확정한다.

실행은 README와 [OPERATIONS](OPERATIONS.md), 이후 단계는 [roadmap](roadmap.md)을 따른다. 유료 사용 및 공개 서비스 배포는 미승인이다. M1 당시에는 자동화나 예약 실행을 설정하지 않았다.

2026-10-12 추가 위임에 따라 현재 채팅의 매시간 후속 실행을 ACTIVE로 등록했다. 예약 실행의 첫 성공은 아직 미확인이다. 실행 조건과 승인 경계는 [AUTONOMY](AUTONOMY.md)에 기록한다. 그 뒤 수행한 첫 M3 비교의 실제 결과를 아래에 기록한다.

## M2 실제 수행 결과

| 항목 | 확인한 결과 |
|---|---|
| 공개 코퍼스 | Kubernetes 고정 커밋, CC-BY-4.0. 2,287개 검사 목록 중 313개 적격 문서, 1,974개 제외 |
| 언어·분할 | EN 235 / KO 78. Train 180 / dev 65 / test 66 / smoke 2 문서 |
| 중복 처리 | canonical 계열 255개, 번역·정확 중복·유사 중복 연결 그룹 212개 |
| AI 질문 | 최초 240개. 검색 실행 전 다중 문서 조건이 불확실한 dev 1개를 별도 버전에서 제외 |
| 현재 활성 질문 | dev 79 / test 후보 160 = 239개. 사용자 검수 0개. Test 검색 평가는 실행하지 않음 |
| 데이터 검사 | 원문·정제 해시, 재정제, 중복 그룹 재계산, 분할, 정확한 근거 오프셋, 출처 검사 통과 |
| BM25 개발 평가 | 313문서·3,588청크. 양성 59질문 중 top-5 청크에 모든 필수 근거가 있는 질문 30개(50.85%) |
| 교차 언어 | 주석상 다른 언어의 근거가 필요한 23질문 중 완전 근거 적중 1개(4.35%) |
| 실제 HTTP | 임시 DB에 로그인·313문서 업로드. 32검색 성공/0실패, p50 255.991ms / p95 385.146ms |
| 검수 도구 | 질문·근거·주변 문맥·전체 코퍼스 탐색 HTML, 실제 검수 JSON 제출/검증. AI가 승인하지 않음 |

수집과 저장된 질문 초안의 재컴파일은 재현 가능하다. AI를 다시 호출해 동일 질문을 얻는 추론 재현은 아니다. 1,000문서 목표는 미달이며 파싱 결함을 통과시켜 수량을 늘리지 않았다. 범위·제외 원인·편향은 [DATA-CARD](DATA-CARD.md), 계약은 [M2-EVALUATION](M2-EVALUATION.md), 실제 수치·실패는 [실험 기록](../experiments/README.md)에 있다.

## M2 검증과 재현

```powershell
uv sync --frozen
uv run ruff check src tests scripts
uv run pytest -q
uv run python -m scripts.prepare_corpus replay
uv run python -m scripts.prepare_corpus verify
uv run python -m scripts.question_dataset --manifest data/manifests/kubernetes-v1.json --questions data/evaluation/m2-dev-v1.1.jsonl data/evaluation/m2-test-a.jsonl data/evaluation/m2-test-b.jsonl
cd web
npm run typecheck
npm run build
```

질문 초안 재컴파일·리비전까지 포함한 전체 명령은 [data/README](../data/README.md)에 있다. 최종 로컬 검증은 **93 tests passed**, Ruff·프런트엔드 타입 검사·production build 통과다. 313문서를 재현·재검증하고 최초 240질문과 활성 239질문의 해시·원문 span·분할 검사를 통과했다. Starlette TestClient 관련 deprecation warning 1개는 남아 있다. 두 측정 보고서의 모든 코드·잠금 파일·입력 해시가 기록된 Git 커밋의 blob과 일치함을 확인했다. 오프라인 평가 커밋은 `65338f2`, HTTP 성공 실행은 `76a20fc`다. `git_dirty=true`는 당시 미커밋 문서·결과가 있음을 그대로 드러낸다.

첫 HTTP 측정은 Windows 임시 DB 정리 시 파일 잠금 오류로 끝났다. 지연시간 결과가 보존되지 않아 인용하지 않는다. [실패 기록](../experiments/results/m2-http-attempt1-failed.json)을 남기고 제한된 정리 재시도를 추가했다. 두 번째 실행은 서버 종료·임시 DB 정리까지 성공했다. 잠금을 잡은 프로세스는 확인하지 못했다.

## M2 한계와 다음 작업

1. 사용자 검수 0개인 현재 점수는 AI 라벨에 대한 예비 회수 지표다. [검수 화면 생성 방법](../data/README.md#실제-사용자-검수)을 제공했다. 확정 정답률·실사용 품질로 말하지 않는다.
2. M3에서 동일 dev·코퍼스로 BM25→다국어 임베딩→혼합→리랭커를 비교한다. 현재 기준선을 유지하며 test 질문으로 튜닝하지 않는다.
3. 현재 청크에 전체 주석 span을 담을 수 없는 dev 질문 3개는 별도 청크 설정 실험으로 다룬다. 순위 모델과 청크 설정을 동시에 바꿔 개선 원인을 혼동하지 않는다.
4. 정제 범위를 넓히면 새 코퍼스 버전·분할 영향을 먼저 검토한다. 미해결 include 때문에 절차 문서가 많이 제외되어 참조 문서 편향이 있다.
5. 모델 라이선스·고정 리비전·로컬 6GB GPU 메모리·지연을 확인한 뒤 학습 대상을 결정한다. Train 문서는 예약만 했고 학습쌍·가중치는 아직 없다.

근거 없음 12질문에도 모두 결과를 반환했다. 답변 보류 기능은 없다. 공개 코퍼스 점수로 최신성 충돌·권한·수정·삭제의 의미적 QA를 검증하지 않았다. 해당 API 회귀 테스트와 검색 품질 평가는 별개다. 동기 파싱, 검색마다 재토큰화, OCR·파서 프로세스 격리 부재, 최고 메모리 사용량 미측정이 남았다. HTTP는 로컬 동시성 1·32건이고 캐시·전원·다른 부하는 통제하지 않았다. 공용 배포·부하 시험 수치가 아니다.

M2에서도 서비스 외부 배포·유료 API·GPU 임대는 하지 않았다. 면접에서 설명할 판단과 한계는 [M2-LEARNING](M2-LEARNING.md)을 참고한다.

## M2 원격 재현 확인

[M2 PR #2](https://github.com/lingter100/doctrail/pull/2)의 구현·결과 커밋 `21c6019`에서 backend/web 모두 [원격 CI 통과](https://github.com/lingter100/doctrail/actions/runs/38200944111)를 확인했다. 새 Linux 환경에서 93개 테스트와 빌드뿐 아니라 313문서의 실제 재수집·해시 검증, 질문 240개 재컴파일, 리비전·활성 239개 검증을 수행했다. 이후 이 확인 기록을 추가한 커밋도 필수 검사를 통과한 뒤 같은 사용자 계정으로 main에 fast-forward한다. 현재 통합 SHA의 최종 상태는 PR과 GitHub 검사에서 확인한다.

## M3 첫 비교 · 실제 로컬 GPU 실행

실행 커밋 `a8fb5a9`, 보고서 [m3-retrieval-dev-v1.json](../experiments/results/m3-retrieval-dev-v1.json), 완료 checkpoint [journal](../experiments/results/m3-retrieval-dev-v1.json.stages.jsonl). 코드·잠금 파일·입력 해시가 해당 Git blob과 일치하며 모델·코퍼스의 실행 전후 해시도 같았다. 질문·청크·라벨을 바꾸지 않았고 이전 BM25 top10 순위·점수·지표와 정확히 일치했다. Journal과 문서 파일 때문에 `git_dirty=true`를 그대로 기록했다.

| 방법 | 양성 59질문의 모든 필수 근거 @5 | 주석상 교차 언어 23질문 |
|---|---:|---:|
| BM25 | 30/59 (50.85%) | 1/23 |
| E5-small 다국어 임베딩 | 29/59 (49.15%) | 1/23 |
| BM25+E5 RRF | 27/59 (45.76%) | 0/23 |
| RRF+ BGE reranker | 36/59 (61.02%) | 6/23 |
| 후보 예산 진단 RRF 25+25 | 30/59 (50.85%) | 0/23 |

혼합+리랭커는 BM25 대비 7질문 개선·1질문 퇴보로 순증 6개다. 전체 원문 근거 회수의 예비 dev 비교이며 답변 정확도·사람 검수·최종 test 개선이 아니다. 단순 임베딩·혼합은 이 조건에서 개선되지 않았다. 리랭커 입력50 안에 모든 근거가 있는 질문도 37/59에 그쳐 후보 회수의 한계가 남았다. 질문별 원문·순위·후보 손실과 면접 설명은 [M3-ANALYSIS](M3-ANALYSIS.md)에 있다.

로컬 RTX 4050 6GB에서 E5 FP32·문서 batch8/query1, BGE FP16·batch1로 실제 실행했다. 문서 벡터 준비 45.08초. 따로 측정한 단계 시간의 합계 p50/p95는 BM25 424/516ms, dense 25/35ms, hybrid 457/542ms, hybrid+reranker 2,556/2,925ms다. 실제 HTTP나 모델 상주 서비스 응답 시간이 아니다. E5 38/3,588개 문서 청크, 리랭커 803/3,950쌍이 512토큰 한도를 넘어 잘렸다. 잘린 뒤 모델이 실제 본 span의 근거 회수는 아직 측정하지 않았다.

E5 문서 준비의 GPU allocator peak allocated/reserved는 794/1,808MiB, 리랭커 질의 단계는 1,123/1,138MiB였다. 리랭커 로드 중 CPU RSS 샘플 peak는 4,353MiB였다. 전체 장치 VRAM·전력·동시 모델 상주 서비스의 메모리 사용량으로 해석하지 않는다.

로컬 **129 tests passed**, Ruff, 프런트엔드 타입 검사·production build 통과. 기본 의존성만 있는 CI에서는 NumPy/Torch에 의존하는 검사 2개를 skip하며 GPU 모델 품질은 검증하지 않는다. 상세 명령은 [M3-RUNBOOK](M3-RUNBOOK.md). Starlette TestClient와 모델의 `torch_dtype` 인자 deprecation 경고가 남지만 실제 실행은 완료했다. 토큰 길이 진단에서 출력된 길이 경고는 실제 forward 전에 512로 자르는 경로와 구분한다.

다음 자동 실행에서는 실패 분석을 바탕으로 후보 회수·잘림의 후속 실험을 제한적으로 설계하고, 새 검색 방법을 명시적으로 선택할 수 있는 서비스 연결을 구현한다. 기본 BM25를 유지하며 ACL 선적용, 벡터의 revision·청크 해시, 수정·삭제·재처리·warm cache 회귀를 확인한다. 이것을 마치기 전 M3 전체 완료로 표시하지 않는다. Train 학습·생성 답변·유료 API·공개 서비스 배포는 하지 않았다.

## M3 첫 비교의 원격 코드·데이터 검사

[M3 PR #3](https://github.com/lingter100/doctrail/pull/3)의 구현·결과·분석 커밋 `0241e4b`에서 backend/web 모두 [원격 CI 통과](https://github.com/lingter100/doctrail/actions/runs/38203764861)를 확인했다. 기본 의존성 Linux 환경에서 **127 passed, 2 skipped**였고 Ruff·프런트엔드 타입 검사·빌드, 313문서 재수집·해시 검증, 최초 240/활성 239질문의 재컴파일·검증이 성공했다. 두 skip은 선택적 NumPy/Torch 검사이며 이 CI가 GPU 모델 추론이나 품질 결과를 재현한 것은 아니다. 실제 모델 실행은 위의 로컬 CUDA 기록으로 구분한다.

이 확인 기록을 추가한 뒤에도 실제 PR head의 필수 검사를 기다리고 사용자 작성자·커미터를 유지해 main에 통합한다. 현재 SHA의 최종 통합·검사 상태는 PR과 GitHub 검사에서 확인한다.

## Java 서비스 전환 · 로컬 검증

사용자의 Java 요청으로 `server/`에 실제 Java 서비스를 구현했다. Spring Boot MVC·JDBC·SQLite, PDFBox 파싱, Java BM25를 사용하며 계정·권한·문서 요청을 Python에 넘기는 구조가 아니다. 기본 실행 `./scripts/start.ps1`은 Java이며 이전 구현은 `-Backend Python`으로 남겼다. Java 기본 DB를 `var/doctrail-java.sqlite3`로 분리해 기존 DB를 자동으로 옮기거나 덮어쓰지 않는다. 실제 사용자 DB 이전은 수행하지 않았다.

- JDK 21.0.12.1, 체크섬 고정 Maven 3.9.16에서 Java 테스트 **20개 통과**. 로그인·세션 회전·만료·제한, 권한 선필터와 숨긴 문서의 점수 불변, 변경·삭제·재처리·피드백, 오류 롤백, 동시 검색, Unicode 원문 위치, PDF 경계를 검사했다.
- Python 회귀 **129개 통과**, Ruff, 프런트엔드 타입 검사·production build 통과. Python TestClient deprecation 경고는 남아 있다.
- [실제 Java HTTP 검증 보고서](../experiments/results/java-migration-v1.json): Python 합성 DB의 복사본으로 기존 계정·세션·문서 호환, Java 변경의 Python 역방향 읽기, Java 재시작 후 데이터 유지, 삭제 반영 등 **11개 검증 묶음** 통과. 이 숫자를 단위 테스트 11개나 사용자 검수로 소개하지 않는다.
- 같은 보고서에서 공개 문서 **313개를 Java API로 등록**, **3,588청크와 dev 79질문의 top10 문서·청크·점수·오프셋**이 기존 동결 Python BM25 결과와 일치했다. 검색 품질 개선이나 Java/Python 성능 우열을 측정한 실험이 아니다. Test 160질문은 검색 평가하지 않았다.
- 길이 헤더가 없는 JSON·multipart 초과 요청, 잘못된 HTTP target·쿠키, 운영 로그의 합성 비밀 표식 미포함을 실제 HTTP·소켓으로 확인했다. 정적 검토에서 발견한 Tomcat의 필터 이전 로거 노출을 설정에서 막았다.

첫 Java HTTP 검증은 Windows Oracle javapath 실행기가 남긴 자식 JVM의 로그 파일 잠금으로 정리 단계에서 실패했다. [실패 기록](../experiments/results/java-migration-attempt1-failed.json)을 보존하고 실제 JDK 실행 파일을 직접 시작·종료하도록 수정했다. 두 작업 전용 잔여 JVM과 검증용 임시 디렉터리는 정리했다. 이후 성공 실행은 종료·정리까지 포함한다.

명령은 아래와 같다. 공개 문서 원문이 없으면 [데이터 재현](../data/README.md)을 먼저 실행한다. 결과 파일은 기존 파일을 덮어쓰지 않는다.

```powershell
./server/mvnw.cmd -B -f server/pom.xml verify
uv run --group retrieval python -m scripts.verify_java_service --full-corpus --output .local/my-java-check.json
```

PDFBox와 pypdf의 일반적인 PDF 텍스트 출력은 동일하다고 주장하지 않는다. 저장된 예전 청크를 시작 시 자동 재처리하지 않는다. JAR의 UI 제공은 HTTP로 확인했지만 이번 전환에서 새 브라우저 시연이나 사용자 검수는 기록하지 않았다. 공개 서비스 배포·새 모델 추론·학습·생성 답변은 별도 후속 작업이다. 다음 자동 실행은 [M3 실패 분석](M3-ANALYSIS.md)에 따른 후보 진단과 Java 서비스의 모델 연결을 이어간다.

## Java 전환의 원격 검사

[PR #4](https://github.com/lingter100/doctrail/pull/4)의 코드·결과·문서 커밋 `09a25e9`에서 `java-service`·`backend`·`web` 모두 [원격 CI 통과](https://github.com/lingter100/doctrail/actions/runs/38206010313)를 확인했다. Linux/Temurin Java 21에서 Java 테스트·JAR 패키징과 실제 HTTP 11개 검증 묶음이 성공했다. 기존 Python 검사는 127 passed/2 skipped이며 공개 313문서 재현과 질문 검증도 통과했다. Java 전체 79질문 순위 대조는 위 로컬 보고서의 결과로 구분한다.

`main` 보호 규칙에 `java-service` 검사를 추가했고 기존 `backend`·`web`, strict, Actions 앱 ID 제한을 유지했다. 마지막 상태 기록 커밋도 필수 검사를 통과한 뒤 사용자 작성자·커미터를 유지하는 fast-forward로 통합한다. 최종 SHA의 통합·검사 상태는 PR에서 확인한다.

## 첫 heartbeat · 후보 선택과 토큰 근거 진단 완료

2026-10-12 05:06:57 UTC에 실제 예약 메시지를 받아 작업을 시작했다. 당시 main `7166c80`은 clean이고 실행 중인 서비스·모델 실험은 없었다. Java 전환과 기존 M3 전체 비교를 반복하지 않고 [사전 설계](M3-CANDIDATE-DESIGN.md)를 `2a6ffa8`에 고정한 뒤 구현을 `52549f7`에 커밋했다.

- [후보·tokenizer 진단](../experiments/results/m3-candidate-diagnostic-dev-v1.json): B/D 합집합의 완전 근거는 40/59, 기존 H50은 37/59. 양성 59문항에는 필수 근거 그룹 72개가 있다. 원래 HR top-5의 전체 근거 회수 36/59와 관련 근거 토큰 보존 36/59가 같았다. 엄격한 문자 offset 합집합은 잘림 전후 모두 27/59로, 이 차이를 잘림 실패 9개라고 읽으면 안 된다. AI 주석·토큰 위치의 자동 진단이며 의미 이해 측정은 아니다.
- [새 후보 선택 실측](../experiments/results/m3-candidates-dev-v1.json): 저장 B50·D50을 번갈아 읽어 중복 없이 50개를 선택했다. 모든 근거를 가진 후보는 **37/59 → 38/59**, 같은 BGE의 최종 top-5는 **36/59 → 37/59**. `m2-dev-017`을 회복했고 완전 근거 지표의 추가 퇴보는 없다. 기존 BM25 대비 8개 회복·1개 퇴보(`060`)로 순증7개다. 교차언어는 6/23 → 7/23이고 다중 문서는 1/7로 남았다. 회복 근거는 사전 고정한 B 우선 순서의 마지막 50번째 자리에 들어왔으므로 분기 순서를 바꿔도 유지되는 이득이라고 주장하지 않는다.
- 기존 다섯 방법의 79문항 결과·집계·paired 비교를 정확히 재계산한 뒤 새 정책을 실행했다. E5/BM25는 재추론하지 않았다. CUDA FP16·batch1로 3,950쌍을 실제 BGE 추론했고 전체 점수·토큰·입력 해시를 저장했다. 이전 top-10과 겹치는 778쌍의 raw 점수가 모두 같았다. 전체 과거 3,950쌍의 동등성을 확인한 것은 아니다.
- 새 BGE 구간만의 p50/p95는 **1,855.325/2,488.538ms**, 입력 잘림은 804/3,950쌍이었다. 이전 검색 시간을 더해 새 HTTP 응답 시간으로 표시하지 않는다. 단일 순회·캐시/전원/부하 미통제이므로 이전 실행보다 빨라졌다는 인과 결론도 내리지 않는다. OOM·묵시적 fallback·유료 API 사용은 없었다.
- 두 보고서 모두 실행 커밋 `52549f7`의 코드·설계·의존성 해시와 일치하고 완료 journal의 출력 hash가 실제 파일과 같다. 결과/journal 생성으로 `git_dirty=true`인 상태를 보존했다. 기존 M2/M3 결과·라벨·test 잠금은 변경하지 않았다.

실제 명령:

```powershell
uv run --locked --group retrieval --no-sync python -m scripts.analyze_candidates --tokenizer-visibility --output experiments/results/m3-candidate-diagnostic-dev-v1.json
uv run --locked --group retrieval --no-sync python -m scripts.evaluate_candidates --output experiments/results/m3-candidates-dev-v1.json
```

로컬 Python **177 passed**, Ruff, Java **20 tests**, 프런트엔드 타입 검사·production build가 통과했다. 새 synthetic 테스트 48개 중 2개는 검증한 로컬 tokenizer 파일을 사용한다. 원격 기본 CI는 GPU 모델을 실행하지 않으며 기존 tensor 검사와 이 tokenizer 검사 총4개를 선택적으로 skip한다. CI에 모델 없는 후보 진단과 기존 다섯 방법의 정확 재생을 추가했다. 테스트를 품질 향상의 증거로 대신하지 않고 위 실제 dev 비교를 별도로 남긴다.

사용자 검수0·test 검색 평가0·학습0·생성 답변0이다. 다음은 Java 서비스에 선택적 모델 추론을 연결하는 구조·토크나이저 호환을 검토하고 ACL 선필터, revision/cache, 수정·삭제 회귀를 검증하는 작업이다. 연구 측면에서는 합집합부터 누락된 근거와 3개 청크 경계 문제를 별도 실험으로 다룬다. 지금 dev에서 후보 정책을 계속 조정하지 않으며 Java 기본 검색은 BM25를 유지한다. [해석과 면접 설명](M3-CANDIDATE-ANALYSIS.md)을 참고한다.

구현 커밋 `52549f7`의 [원격 CI](https://github.com/lingter100/doctrail/actions/runs/38207832080)는 `java-service`·`backend`·`web` 모두 성공했다. Python173passed/4skipped, Java 테스트·실제 HTTP11묶음, 코퍼스 재현·활성 질문 검증과 모델 없는 후보 분석·기존 결과 정확 재생이 통과했다. 실제 GPU 실험은 위 로컬 기록으로 구분한다. 결과·분석 커밋도 실제 PR head에서 세 필수 검사를 통과한 뒤 사용자 작성자/커미터를 보존해 main에 통합하며 최종 상태는 PR에서 확인한다.

## React 전환 · 로컬 검증 완료

사용자의 React 전환 승인을 반영해 `feat/react-frontend`에서 구현했다. 기존 main `d25f623`은 시작 당시 clean이었다. 기존 CSS·한국어 UI, Java API와 Python 연구·동결 데이터는 보존했다. `App`, 계정·목록·검색/이력·원문·모달 컴포넌트, 상태 조정 hook, API·타입·원문 helper로 나눴다. [선택 이유](decisions/0003-react-frontend.md), [구조·실행법](FRONTEND.md)을 제공한다.

- React/React DOM **19.2.8**, Vite **7.3.7**, React 플러그인 **5.2.0**, Playwright **1.64.0**을 잠금 파일에 고정했다. 설치 시 npm audit 0 vulnerabilities를 확인했으며 포괄적인 보안 감사 완료를 뜻하지 않는다.
- 브라우저에서 실제 Java JAR과 production React 번들을 연결했다. 가입·로그인·로그아웃, MD/TXT/PDF 업로드, 검색·Unicode 원문 위치, HTML을 텍스트로 표시, 피드백·이력, 수정·삭제, 작업공간 생성·전환, 별도 회원 권한, 실패 PDF 재처리와 파일 크기 검사를 확인했다.
- 첫 15개 검사를 통과한 뒤 리뷰에서 발견한 초기 목록과 검색 경합, 역순 수정 응답 문제에 검사를 추가했다. 최종 **17 passed / 0 failed / 0 skipped**(브라우저 흐름14·순수 helper3), 자동 재시도0이다. 실제 서버 응답을 보류해 오래된 검색·상세·작업공간·모달 응답, 수정v2 뒤 v3, 수정 응답 뒤 삭제를 재현했다. 새 세션 뒤 이전401은 명시적인 합성 오류로 검사했다.
- 별도 Java 회귀 **20 tests**, 기존 Python **177 passed**, Ruff, 프런트엔드·검사 코드 타입 검사와 production build를 통과했다. Python GPU 실험이나 동결 평가를 반복한 것이 아니다. 기존 Python 참조 의존성에서 Starlette/httpx 사용 중단 예고 경고1건은 남아 있다.
- 최종 [자동 검사 기록](verification/react-frontend.json)에 실제 실행 UTC, 원본 보고서 hash, LF 정규화 소스 hash, 개별 검사명, 결과와 번들 크기를 저장했다. JS 번들233,162bytes/gzip73,096bytes는 빌드 산출물 크기이며 HTTP 지연이나 이전 화면 대비 속도 향상 수치가 아니다.
- [데스크톱](images/react-desktop.png)·[390px 모바일](images/react-mobile.png)을 AI가 확인했다. 합성 계정·문서·피드백이며 사용자 직접 시연이 아니다. 원문 태그가 그대로 보이는 화면은 HTML 실행 방지 검사 자료다.
- 각 실행은 새 합성 DB·임시 localhost 포트를 사용했다. JAR 화면과 현재 빌드 index 일치, 검사 종료 후 소유 JVM 종료를 확인했다. 기존 사용자 DB는 사용하지 않았다. 서비스 인터넷 공개·유료 자원 사용은 없다.

실행 순서는 `npm --prefix web run typecheck`, `npm --prefix web run build`, `./server/mvnw.cmd -B -q -f server/pom.xml verify`, `npm --prefix web run test:e2e`다. 마지막 상태 수정 후 프런트엔드를 다시 빌드하고 Java를 `-DskipTests package`로 재패키징해 최종17개를 수행했다. Java 소스는 이번 작업에서 변경하지 않았다. Python은 `uv run --locked --group retrieval --no-sync pytest -q`와 Ruff로 검증했다.

CI의 기존 필수 `java-service` 작업에 실제 Chromium 검사를 추가했다. 이 로컬 기록 작성 시점에는 새 PR의 원격 검사가 아직이며, 통과·통합은 별도 기록한다. 사용자 검수0·학습0·생성 답변0은 유지한다. 다음 개발은 Java 서비스의 선택적 검색 모델 연결과 ACL·문서 변경 반영 검증이며, 유료 사용·공개 서비스 배포 승인 조건은 유지한다.

## React 전환 · 원격 검사

구현 커밋 `c52cb39`의 [PR #6](https://github.com/lingter100/doctrail/pull/6)에서 `java-service`·`backend`·`web` 모두 [원격 CI 성공](https://github.com/lingter100/doctrail/actions/runs/38211284184)을 확인했다. Ubuntu/Temurin Java 21의 실제 JAR·Chromium 검사가 로컬과 동일한17개를 통과했다. 기존 Python 기본 CI는173passed/4skipped이며 모델 없는 동결 데이터·질문·후보 결과 재현과 Java HTTP11묶음도 통과했다. 로컬 GPU 의존성의 선택적 검사4개와 원격 skip을 구분한다.

이 기록 커밋 역시 실제 PR head에서 세 필수 검사를 통과한 뒤 사용자 작성자·커미터를 유지하는 fast-forward로 main에 통합한다. 최종 통합 SHA·상태는 PR을 기준으로 확인한다. 후속 실행은 React를 다시 전환하지 않고 Java의 검색 모델 연결 단계로 돌아간다.

## M3 · Java 선택적 검색 모델 연결 · 로컬 검증 완료

`feat/model-search`는 clean main `e7b8cf7`에서 시작했다. 기존 실행 중 작업이 없는 것을 확인했다. React 전환과 동결 M2/M3를 보존하고 Java 서비스에 `dense`, `hybrid`, `hybrid_rerank`를 추가했다. 기본 검색은 BM25다. Python은 고정 E5/BGE 추론만 처리하며 Java가 세션·ACL·문서·cosine/RRF·후보 선택·최종 순위·기록을 관리한다. [ADR](decisions/0004-model-serving.md), [실행·복구·면접 설명](MODEL-SERVING.md).

- Java는 현재 허용 청크만 모델에 보내고 추론 중 DB 트랜잭션을 해제한다. 완료 후 쓰기 트랜잭션에서 세션·membership·전체 가시 문서 스냅샷을 다시 확인한다. 수정·삭제·비공개 변경·새 문서·membership 삭제·로그아웃 경합에서 오래된 결과/이력을 거부했다.
- Worker는 고정 revision/hash의 E5 FP32, BGE CUDA FP16을 상주시킨다. 인증된 loopback만 사용하고 cache는 본문 hash·encoder 설정 기반의 메모리 LRU다. 원문/질문·사용자 세션·문서 목록을 cache에 보존하지 않는다. 두 모델의 기존 offline telemetry 누적 배열은 wrapper에서 비운다.
- React에서 검색 방식과 실제 결과 방법을 표시하고 이력 재검색도 원래 방법을 사용한다. Worker 미연결/실패 안내와 명시적인 BM25 선택을 제공한다. 모델 실패를 조용히 키워드 검색으로 바꾸지 않는다. 문서 탐색 디자인은 유지했다.

**실제 로컬 GPU·HTTP:** [보고서](../experiments/results/m3-model-service-v1.json)는 2026-10-12 06:35:30–06:35:56 UTC의 실제 실행이다. 합성 계정·문서로12개 운영 검사 묶음을 통과했고, 그 안의 실제 Chromium 모델 흐름6개에서 가입·업로드·세 모델 방식·원문·피드백·방법별 이력·390px 폭을 확인했다. 모든 모델 요청에서 실제 `cuda`, E5 `torch.float32`, BGE `torch.float16`을 확인했다. 원문 codepoint 위치·revision·private ACL·수정·동일 본문 재처리·삭제를 대조했고, 모델 중단 후503/no fallback/no history 및 기본 BM25 동작을 확인했다. 로그 표식·비밀번호·세션/worker token 미노출 검사도 통과했다.

HTTP 실측은 짧은 합성 문서2개·청크2개에서 방식당2회만 측정했다. E5 첫 요청498.692ms, 반복57.277ms; 재정렬 첫310.724ms, 반복115.201ms였다. 모델 상주 준비19,135.831ms는 요청 시간과 별개다. Passage cache가 빈 시점은 첫 E5뿐이며 이후 방식은 cache를 공유했다. 다른 BM25 브라우저 회귀 프로세스가 동시에 실행되었고, 전원/부하를 통제하지 않았다. 따라서 이 작은 값으로 전체 코퍼스 p95·서비스 SLO·이전 실험 대비 속도 향상·확정 품질을 주장하지 않는다. 별도 cache witness에서 최초 miss1 → 동일 본문 hit1 → 변경 본문 miss1을 실제 관측했다.

**자동 회귀:** Java **59 tests**, Python **220 passed**, Ruff, TypeScript 검사·production build, 실제 Java HTTP 기본/복사 DB 호환 **11묶음**, 모델 없는 Chromium **18 passed / 0 failed / 0 skipped / 0 retry**(브라우저15·helper3)를 통과했다. 첫 브라우저 실행의 disabled option 판정1건은 실제 DOM에 disabled가 있었으므로 속성 검사로 바꾼 뒤 다시 검증했다. Python Starlette/httpx 사용 중단 경고1건은 기존 상태로 남는다. 가벼운 원격 CI에는 모델 가중치를 설치하지 않으며 이 기록 작성 시점의 새 PR CI는 아직이다.

[통합 검증 기록](verification/model-service.json)에 개별 browser 검사, Java 집계, report hash와 LF 정규화 화면 source hash를 남겼다. 실제 모델 보고서의24개 source hash와 JAR hash가 실행 파일과 일치하고 동결 source/input/results가 base와 변경 없음을 확인했다. 모델 보고서는 실행 당시 미커밋 상태(`git_dirty=true`)를 정직하게 보존했다. [데스크톱](images/model-desktop.png)·[모바일](images/model-mobile.png)은 실제 합성 시연 자동 캡처이며, AI가 가독성·가로 넘침·근거 패널을 확인했다. 잠깐 보이는 업로드 알림도 실제 화면 상태다. 사용자 검수는 아니다. 검증 종료 후 소유한 Java/Python 프로세스가 남지 않은 것을 확인했다.

실행 명령:

```powershell
npm --prefix web run typecheck
npm --prefix web run build
./server/mvnw.cmd -B -q -f server/pom.xml verify
uv run --locked --group retrieval --no-sync pytest -q
uv run --locked --no-sync ruff check src tests scripts
npm --prefix web run test:e2e
uv run --locked --no-sync python -m scripts.verify_java_service --output .local/java-model-search-baseline.json
uv run --locked --group retrieval --no-sync python -m scripts.verify_model_service --device cuda --browser --output experiments/results/m3-model-service-v1.json
```

**다음 작업:** train 계열에서 후보 누락과 청크 경계 문제를 분리하고, train 전용 학습쌍·hard negative 품질을 검증한 뒤 임베딩/리랭커 학습 대상을 근거로 확정한다. 최종 test를 열거나 dev에서 계속 후보 정책을 바꾸지 않는다. 사용자 검수0·학습0·생성 답변0·공개 서비스 배포0이다. 모델 검색은 현재4,096청크 상한과 직렬 추론이므로 대규모 운영 검증이 남아 있다. 외관·사용성도 최종 기준에 포함하지만 로드맵 순서를 바꾸지 않는다.

## M3 모델 연결 · 원격 검사

구현 커밋 `1a7babb`의 [PR #7](https://github.com/lingter100/doctrail/pull/7)에서 `java-service`·`backend`·`web` 모두 성공했다. [실제 head push 검사](https://github.com/lingter100/doctrail/actions/runs/38213876293)와 [PR 검사](https://github.com/lingter100/doctrail/actions/runs/38213907700)를 확인했다. Ubuntu/Temurin Java21의 실제 HTTP11묶음과 Chromium18개, Python216passed/4skipped, 코퍼스·질문 재현과 모델 없는 후보 결과 재생이 통과했다. 원격은 GPU 모델을 실행하지 않았으며 로컬220개 검사·실제 CUDA 추론과 구분한다.

GitHub API에서 구현 커밋의 작성자와 커미터가 모두 `lingter100`임을 확인했다. 이 진행 기록도 별도 Conventional Commit으로 필수 CI를 통과한 뒤 사용자 계정을 유지하는 fast-forward로 main에 통합한다. 최종 통합 SHA·상태는 PR에서 확인한다. 다음 실행은 완료한 모델 연결을 반복하지 않고 train180문서·128계열의 검토와 학습 설계를 시작한다.

## M4 train 자료 pilot · 실제 수행

2026-10-12 06:49:58 UTC heartbeat에서 저장소 지침·상태·Git·프로세스를 확인하고 시작했다. Main `f01d8f3`와 PR#7 통합·필수 CI 성공을 확인했으며 실행 중 모델/학습 작업은 없었다. 새 `feat/train-data`에서 설계와 자료를 준비했다.

[M4 설계](M4-DESIGN.md)는 저장된 후보 실패21개/순위 실패1개 집계를 근거로 E5 후보 생성 모델을 조건부 학습 대상으로 정했다. BGE·청크·후보 정책은 고정한다. 이 단계는 원래 train180문서·128연결 그룹만 사용하고 dev/test 질문을 학습 설계에 다시 열지 않는다. 기존 로더가 전체 코퍼스 무결성을 확인한 후 train만 남기는 것과 평가 질문을 읽는 작업을 구분한다.

| 확인 항목 | 실제 결과 |
|---|---|
| Train 내부 분할 | Fit150문서/103계열/1,643청크, calibration30문서/25계열/553청크 |
| AI 작성 질문 | Fit64/16계열, calibration14/4계열; KO59·EN19, 주석상 한국어 질문/영어 근거51 |
| 자동 원문 검사 | 78/78 인용·Unicode 오프셋·동결 청크 전체 포함, 질문 자동 격리0 |
| 양성 후보 | 80쌍; 중첩 청크2개에 든 질문2개가 있어 독립 질문 수78과 다름 |
| 독립 AI 의미 검토 | 별도 역할이78개 모두 accept; 원문·질문·답안 직접성 확인, 사용자 검수0 |
| BM25 음성 후보 | 1,560개 중 알려진 양성/동계열/중복 위험328개 격리, 나머지1,232개 미검토 |
| 확인한 음성·학습 | 음성 라벨0, 학습0, 모든 후보 training eligibility=false |
| 데이터 부족 | Calibration 목표16 대비2개 부족; 링크 모음에 독립 사실을 억지로 추가하지 않음 |
| 재현 | 저장 초안에서4개 compiler 산출물 byte-for-byte replay와 독립 검토 영수증 replay 통과 |

원본 초안은 AI 작성·semantic pending 상태를 보존하고 독립 의미 검토를 별도 파일로 연결했다. 검수자는 작성자와 다르며, 질문 canonical hash·원문 hash·author pack hash가 바뀌면 영수증 검증이 실패한다. 자동 검증은 의미적 진실이나 사람 승인을 대신하지 않는다. 전체 코퍼스의 대체 정답 관련성은 아직 확인하지 않았다.

계획·작성 지침을 `611a66a`에 고정했고 최종 초안 전에 public selection을 기록했다. 초기 pack의 계획 바인딩 및 Windows CRLF/Git LF 해시 차이는 실제 컴파일 전에 해결했다. V1/V3의 전체 문서·허용 ID 일치를 부모와 작성자가 확인했고, 최종 V3 pack 해시만 최종 행에 연결했다. 오래된 inventory/pack은 로컬에 보존하며 게시 자료에는 포함하지 않는다. 변경 이력은 [생성 영수증](../data/training/generation/receipt-v1.json)에 남겼다.

[데이터·재현 안내](../data/training/README.md), [자동 보고서](../data/training/m4-pilot-v1/report.json), [별도 AI 검토 보고서](../data/training/reviews/m4-semantic-report-v1.json)를 참조한다. Compiler 보고서는 의미 검토 전 snapshot이므로 후속 검토 결과를 소급 반영하지 않는다.

실행한 검증은 Java59개, React 타입 검사·production build, 실제 Java 기반 Chromium18개, Python 전체264개와 Ruff다. Python은 기존 Starlette/httpx 사용 중단 경고1건이 있다. 신규 데이터/영수증 검사44개를 포함하며 원격 PR CI 결과는 별도 통합 기록에서 확정한다. 기존 Java/M3 모델 동작은 변경하지 않았으므로 CUDA·동결 dev 비교를 다시 실행하지 않았다. 서비스 회귀 통과와 모델 품질은 별개다.

주요 실행 명령은 다음과 같다. 입력 생성·replay 전체 명령은 데이터 안내에 있다.

```powershell
uv run --locked --no-sync ruff check src tests scripts
uv run --locked --no-sync pytest -q
npm --prefix web run typecheck
npm --prefix web run build
./server/mvnw.cmd -B -q -f server/pom.xml verify
npm --prefix web run test:e2e
```

다음은 기존 pilot을 덮어쓰지 않는 보정 문서 추가 선택, 명시적 음성 검토, E5 tokenizer 근거 보존과 질문당 단일 양성 선택 규칙 동결이다. 조건 통과 후에만 실제1 optimizer step 자원 probe와 제한 학습·동일 calibration 비교를 진행한다. 유료 자원·공개 서비스 배포·최종 test 개방은 수행하지 않았다. UI 완성도는 기존 최종 기준을 유지한다.
