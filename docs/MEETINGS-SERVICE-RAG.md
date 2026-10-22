# 서비스 RAG 연결과 검증 범위

## 현재 확인된 상태 — 2026-10-22

명시적 `batch-v2` 개발 실행은 실제 로컬 모델로 회의4개 분석과 질문6개 응답까지 진행했다. 기본 정책은 여전히 `single`이며 `batch-v1`과 닫힌 실행도 보존한다. 전체 원문·분석120초·답변90초·동일 모델 예산을 유지했다. 원래 종료 검사가 실패했으므로 전체 운영 통과나 기본 채택은 아니다.

답변6건의 독립 사후 AI 검토는 문제 없음5건/불필요한 인용1건이다. 원문 단독 기준 뒤 추출159개를 비교한 결과는 우선138/허용11/명확불일치10이며, 요약4개 핵심 범위 부족·제목2개 누락·작업 확약3개 분류 누락이 남았다. 원문 인용179개 일치만으로 충분한 요약이나 올바른 분류가 증명되지는 않는다. 작은 합성 개발 자료의 결과로 공식 평가·실제 조직 품질·사용자 검수를 대신하지 않는다.

클릭부터 응답JSON까지 질문6건 평균52.758초이며 회의분석 worker 관측4건 평균29.332초다. 렌더 완료·운영p95·전체 비용은 측정하지 않았다. 현재 지식검색 UI는 보류 사유와 요청 실패를 구분하고 원문 검색/명시적 재시도를 안내한다.

- [실제 실행과 원래 실패](../experiments/results/meetings-analysis-scope-development-v2.json)
- [답변 판정](../experiments/results/meetings-analysis-scope-answer-review-v1.json), [추출 판정](../experiments/results/meetings-analysis-scope-extraction-review-v1.json), [실측 구간](../experiments/results/meetings-analysis-scope-performance-v1.json)
- [화면 안내와 Java 경계 검사](../experiments/results/knowledge-answer-recovery-messages-v1.json)

요약·제목 후처리 후보는 새 경로로 구현하고 서비스 선택까지 연결했다. 저장된 실제 분류의 기계 비교4회와 독립 의미 검토를 마쳤지만 요약 충분성은0/4로 그대로다. 새 실제 서비스 실행은 아직 하지 않았다. 아래 single 연결과 최초 구현 검증은 이전 시점의 기록이다.

## 요약·제목 조립 후보의 실행 설정

`--analysis-policy batch-v2 --extraction-assembly coverage-v1`을 두 launcher에 명시하면 새 발췌 요약/제목 조립을 선택한다. assembly 생략은 `legacy`이며 기존 single/batch-v1과 새 assembly의 조합은 시작 전에 거부한다. 같은4개 요약 슬롯을 유형별로 순환 선택하고, 모델이 제목으로 분류한 원문의 literal 값을 투영한다. 전체 항목·근거 좌표·분류 모델/프롬프트·기존 한도를 유지한다. 동일 분류 비교에서 요약 충분성은 개선되지 않았으며 분류 정확성은 변경 대상이 아니다.

```powershell
uv run --no-sync python -m scripts.serve_meeting_rag_service `
  --enable-service-rag --jar-sha256 $ragJarHash `
  --database .local/service-rag-coverage-demo.sqlite3 `
  --log-dir .local/service-rag-coverage-demo-001 `
  --analysis-policy batch-v2 --extraction-assembly coverage-v1
```

위 명령은 모델 캐시·설치·정확한 JAR hash가 준비된 경우의 사용 예시이며 실행 성공 증거가 아니다. 실행 이력이 있는 경로는 재사용하지 않는다. Health의 `extraction.assembly`와 lifecycle의 `extraction_assembly`로 실제 선택을 확인한다. 평가 도구에는 CLI 덮어쓰기 옵션이 없으며 plan·registration·calibration gate의 effective assembly가 같아야 한다. 새 module은 legacy에서도 code binding에 포함한다.

[구현 검증](../experiments/results/meetings-extraction-coverage-implementation-v1.json)은 최종452개 합성/MockTransport 및 Node 계약 검사·Ruff·독립 코드 검토를 기록한다. 실제모델·Java/브라우저서비스·저장된 분류의 품질 비교는0이다. 기존57개 단독 검사는 최종452개와 겹치므로 더하지 않는다. 정확한 source22e945c의 push/PR 필수 CI는 [별도 기록](../experiments/results/meetings-extraction-coverage-ci-v1.json)처럼 모두 통과했다. [동일 분류 비교](../experiments/results/meetings-extraction-coverage-comparison-v1.json)에서 요약4개·제목2개가 바뀌고 나머지 항목·근거는 유지됐으며, [같은 기준의 의미 검토](../experiments/results/meetings-extraction-coverage-review-v1.json)에서는 주요 결정 노출이 늘어도 핵심 누락4/4·충분성0/4가 유지됐다. 제목 누락2개는 해소됐지만 접두어 잔존으로 정확값 일치2/4는 그대로다.

```powershell
uv run --no-sync pytest -q tests/test_meeting_extraction_coverage.py tests/test_meeting_service_rag.py tests/test_meeting_service_rag_launcher.py tests/test_serve_meeting_rag_service.py tests/test_run_meeting_rag_acceptance.py tests/test_meeting_analysis_batch.py
```

## 이전 연결 기록

이전 single 정책 연결 기록: 기존 Java/React 서비스에 새 로컬 답변 worker를 연결한 opt-in 구현이다. 코드 계약·합성 전송·실제 Java 화면을 검증했고 실제 native까지 연결했다. 시작45.485초, 첫 회의 분석114.182초 이후 두 번째 분석이120.047초에 실패했다. 실제 답변은 아직 미실행이며 전체 흐름 수용·기본 채택·Phase1 완료가 아니다. [실행 실패 기록](../experiments/results/meetings-service-rag-analysis-timeout-v2.json)을 따른다. 아래의 최초 구현·합성 검사 결과는2026-10-20 기준 이력이다.

## 구현한 동작

Java `DOCTRAIL_RAG_ANSWER_ENABLED=true`일 때 답변 요청에 하나의90초 예산을 부여한다. 검색의 기존 제한과 남은 답변 예산 중 작은 값을 사용하고, 모델 전송 전후와 마지막 권한·문서 revision 검사 뒤에도 만료를 확인한다. 내부 `X-DocTrail-Request-Budget-Ms`는 서버가 계산하며 사용자 입력으로 늘릴 수 없다. 기본값false에서는 기존 검색·답변·분석 경로를 유지한다.

Python은 기존 `QualityThinkingGenerator` 답변과 `Qwen35Generator` 회의 분석을 조립한다. 모델·prompt·decoder를 복제하지 않는다. 답변은 기존 thinking928/최종384/90초, 분석은 기존 nonthinking 분류/input4096/output768/label4/120초 정책이며 서로 다른 작업이다. 한 native instance/GPU lease와 공유 잠금으로 직렬 처리한다. 입력 초과·busy·시간 초과·정리 실패를 답변 보류 성공으로 바꾸거나 자동 재시도하지 않는다.

이전 분석 요청의 watchdog이 다음 답변 요청을 중단할 수 있는 잠금 해제 순서를 검토 중 발견했다. 공유 outer lock을 watchdog 취소·join이 끝날 때까지 유지하도록 고쳤고, 그 구간에서 다음 요청의 진입을 막는 결정적 검사를 추가했다. Startup identity 확인에도 남은 시간을 전달한다. Timeout·transport 실패 뒤에는 readiness를 실패로 바꾸고 재시작 전 새 모델 작업을 받지 않는다.

화면은 근거 분량 초과, 검색 시간 초과, 다른 AI 요청 처리 중, 정리 실패를 구별한다. 원문은 보존하고 사용자가 명시적으로 원문 검색이나 재요청을 선택한다.

## 확인한 결과

| 검증 | 실측 결과 | 범위 |
| --- | --- | --- |
| 새 Python worker/launcher | 23통과,1.06초, 기존 TestClient 경고1; Ruff 통과 | 실제 기존 mapper/classifier 코드와 합성 native HTTP transport. 실제 tokenizer·모델0 |
| Java 시간·HTTP·권한 경계 | 41통과, Maven16.224초 | 제어 시계/격리 SQLite와 실제 로컬 HTTP. 만료 뒤 전송·응답 차단, private/비가입 자료 제외, 수정·삭제·로그아웃 재확인 |
| 기존 Java 호환성 | 별도11통과, Maven5.423초 | 언어·검토·선정된 회의 서비스 검사 |
| 새 설정을 켠 실제 화면 | 1통과, 검사6.8초/suite8.0초 | 실제 Spring/패키징 React. 등록·편집·작업·결정 연결·답변·인용·desktop/mobile. 기존 합성 전송으로 analyze2/answer1 |
| 타입·화면 빌드·Java package | 통과 | package는 `-DskipTests`; Java 테스트 결과와 별개 |

Python 초기 Ruff 지적과 수정 과정은 보존했다. Java 이번 검사의 실패는0이며 경고는 기록에 남았다. 서로 다른 범위의 검사 수를 모델 품질 점수로 더하지 않는다. 소유 Java 프로세스 종료를 확인했고 다른 프로젝트의3개 Java는 유지했다.

[검증 요약](../experiments/results/meetings-service-rag-implementation-v1.json)은 local receipt에서 만든 LF JSON 요약이다. 원본 byte-copy라고 주장하지 않으며 원본 hash, 코드10개, Java 증거25개·화면4개, Python 로그10개를 연결한다. 이전 동결77개는 그대로다. 정확한 구현 커밋 CI는 별도 확인한다.

## 실행 설정

2026-10-22 추가: `--analysis-policy batch-v1`은 전체 단위를 최대8개씩 분류하는 새 개발 후보를 선택한다. 두 launcher 모두 이 옵션을 지원하고 기본은 기존 `single`이다. 새 정책은 입력4096·출력128·EOS·분석 전체120초를 검증하며, 긴 입력은 생성 전에 묶음을 나누고 단위 하나도 들어가지 않으면 실패한다. 원문을 축약하거나 실패 뒤 개별 호출로 돌아가지 않는다. 기존 Purpose heading의 추론용 정규화와 원문 근거 좌표는 구분한다. 자연어 답변 정책은 그대로다.

```powershell
uv run --no-sync python -m scripts.serve_meeting_rag_service `
  --enable-service-rag --jar-sha256 $ragJarHash `
  --database .local/service-rag-batch-demo.sqlite3 `
  --log-dir .local/service-rag-batch-demo-001 --analysis-policy batch-v1
```

위 명령은 기존 JAR hash·설치·모델 캐시 준비 뒤의 사용 예시이며 실제 실행 성공 기록이 아니다. 같은 경로를 재사용하지 않는다. Health의 `extraction.classification`과 lifecycle의 `analysis_policy`로 실제 선택을 확인한다. 선택한 정책과 health의 prompt/grammar 정책 hash·상한이 다르면 시작을 거부한다. `single`로 복귀할 때는 정상 종료한 뒤 새 로그 경로에서 옵션을 생략한다.

새10파일은 관련208개 합성 검사·Ruff와 독립 코드 검토 blocker0을 마쳤다. [검증 요약](../experiments/results/meetings-analysis-batch-implementation-v1.json)은 이전191개와 실패 이력을 함께 보존한다. 실제 native grammar·속도·의미 정확성은 아직 검증하지 않았다. 공식 평가는 plan과 등록에 같은 정책을 명시하며 모든 정책에서 새 adapter 코드도 고정한다. Validation에는 같은 정책의 calibration 통과가 필요하고 생략된 정책은 기존single만 뜻한다. 닫힌 원래 v1/v2를 새 정책으로 재실행하지 않는다.

```powershell
uv run --no-sync pytest -q tests/test_meeting_analysis_batch.py tests/test_meeting_service_rag.py tests/test_meeting_service_rag_launcher.py tests/test_serve_meeting_rag_service.py tests/test_run_meeting_rag_acceptance.py
```

기존 로컬 설치와 모델 캐시가 필요하며 launcher는 다운로드하지 않는다. Java와 worker 터미널에 같은 `DOCTRAIL_GENERATION_TOKEN`을 설정하되 값을 로그·커밋에 남기지 않는다. 실제 모델 검증은 [계획](MEETINGS-RAG-ACCEPTANCE-PLAN.md)의 새 자료/실행 등록 뒤 수행하며 아래 명령 자체는 실행 증거가 아니다.

```powershell
# Worker: 아직 사용하지 않은 로그 디렉터리를 지정한다.
uv run --no-sync python -m scripts.serve_meeting_service_rag --enable-service-rag --log-dir .local/service-rag-manual-001 --port 8092

# 같은 token을 설정한 Java 터미널의 추가 환경 설정
$env:DOCTRAIL_RAG_ANSWER_ENABLED = 'true'
$env:DOCTRAIL_GENERATION_URL = 'http://127.0.0.1:8092'
```

Java 기동은 기존 [실행 안내](../README.md)를 따른다. 기존 경로로 복귀할 때는 새 worker를 정상 종료하고 opt-in을false로 바꾼 뒤 기존 worker 설정으로 Java를 다시 시작한다. DB를 초기화하거나 Docker를 재설정하지 않는다. Worker 정리 실패 시 소유 프로세스와 lock 상태를 확인한 뒤 재시작한다.

합성 코드 검사의 재현:

```powershell
uv run --no-sync pytest -q tests/test_meeting_service_rag.py tests/test_meeting_service_rag_launcher.py
./server/mvnw.cmd -o -B -q -f server/pom.xml '-Dtest=GenerationClientTest,KnowledgeDeadlineTest' test
```

## 남은 확인

- Java→새 Python HTTP worker→실제 native→화면의 전체 연결 및 기존 분석과 thinking 답변의 실제 호환성.
- 새 자료에서 검색 근거 누락과 생성 오류를 분리한 독립 판정·최종 평가·사용자 검수.
- 인증된 HTTP health까지 startup120초와 worker/handler를 포함한 정리5초의 실제 확인. 현재 `native_adapter_startup_seconds`는 native/adapter 준비만 측정한다.
- 현재 Java budget은 `KnowledgeService.execute` 진입 기준이다. 그 전 HTTP decoding, 반환 뒤 serialization, 동기 CPU/DB 작업의 hard preemption은 보장하지 않는다. 전체 사용자 지연은 외부에서 따로 측정해야 한다.
- 클라이언트 timeout/취소가 실제 native 중단 완료를 증명하지 않는다. 합성 watchdog 검사만으로 hard preemption이나 실제 모델 성능을 주장하지 않는다.

## 함께 실행하는 최소 launcher 설계

2026-10-20 추가한 설계를 아래처럼 구현했다. 신규 `scripts/serve_meeting_rag_service.py`와 그 합성 검사 한 파일만 추가한다. 기존 native context와 Uvicorn Server를 현재 Python 프로세스에 두고 CPU 검색·Java만 소유 자식 프로세스로 시작한다. 서로 다른 임의 token을 메모리/자식 환경에 전달하고 로그에는 남기지 않는다. 기존 모델·답변90초·분석120초·동결 코드는 그대로 사용한다.

실제 Astra xhigh 검토의 정정에 따라 종료는 Java의 새 요청 차단→CPU 종료 요청→worker 종료 요청과 owned native 정리 선발동→worker join→context 최종 정리 순서다. 진행 중인 요청이 native를 기다리는 상태에서 먼저 worker join을 완료하려 하지 않는다. 모든 자체 wait/join은 하나의 남은5초를 사용하며, 기존 native cleanup의 별도5초를 합산 허용하지 않는다. 초과·미종료·오류는 실패로 남기고 소유 자원 정리는 계속한다. 강제 선점을 보장한다는 의미는 아니다.

전체 startup120초는 인증된 generation health·CPU/base retrieval health·Java HTTP 준비와 소유 thread/process 생존까지 측정한다. 기존 동기 hash/context 진입의 늦은 반환은 수용 실패로 기록한다. Uvicorn thread 예외도 호출자에게 전달한다. Java에는 opt-in/base를 명시적 인자로 전달한다. 현재 Java health는 status/version만 제공하므로 pinned JAR와 실행 인자 확인은 설정 확인이며 실제 opt-in 효과 증거가 아니다. 실제 서비스 요청 검증이 별도로 필요하다.

신규 경계의 주입된 factory·clock·HTTP probe로 시작/실패/종료/비밀값 비노출을 검사한다. 기존 frozen 모듈 전역을 바꾸거나 실제 자료·모델·브라우저를 이 합성 검사에 사용하지 않는다.

## 실행기 검증과 사용 방법

최종 신규29개 합성 검사가0.86초에 통과했고 Ruff도 통과했다. 별도 Astra xhigh 코드 검토가 native 시작 실패 시 내부 정리의 시간·오류를 외부 판정이 놓치는 문제를 발견했다. 수정 전7개 회귀 실패를 보존하고, 이미 소비한 정리 시간과 오류를 전체5초 판정에 포함하도록 고쳤다. 수정 후 독립 delta 검토에서 남은 blocker는0이다. 이전21개와 최종29개는 겹치는 검사이므로 합산하지 않는다.

최종 LF 코드의 검사 전후 hash가 같고 부모가 코드·증거13개 및 이전 로그6개, 기존 동결77개를 확인했다. 초기 Ruff16 지적과 추가 스타일1 지적, 원래 소스·receipt·실패 로그는 별도로 보존했다. [공개 검증 요약](../experiments/results/meetings-service-rag-launcher-v1.json)은 원본에서 만든 LF JSON이며 원본 byte-copy가 아니다.

기존 설치·화면 빌드·Java package와 무료 로컬 모델 캐시가 필요하다. 아래는 실행 방법이며 실제 native 통합 성공 증거는 아니다. 공식 평가는 별도 source/item 검토와 실행 등록을 먼저 따른다.

```powershell
$ragJarHash = (Get-FileHash -LiteralPath ./server/target/doctrail-server-0.1.0.jar -Algorithm SHA256).Hash.ToLowerInvariant()
uv run --no-sync python -m scripts.serve_meeting_rag_service `
  --enable-service-rag --jar-sha256 $ragJarHash `
  --database .local/service-rag-demo.sqlite3 `
  --log-dir .local/service-rag-demo-001
```

로그 폴더는 사용하지 않은 경로여야 한다. 시작 후 표시된 로컬 주소에서 로그인하고, 검색 방법을 `hybrid_rerank`로 선택한다. 답변 근거 상한은 기존 화면의5개이며 launcher가 요청을 강제로 바꾸지 않는다. Ctrl+C로 종료하면 소유 자원을 정리하고 지정 폴더의 `lifecycle.json`에 시작·정리 수용 여부를 남긴다. 정리 초과/오류는 실패이며 자동 재시작하지 않는다.

```powershell
uv run --no-sync pytest -q tests/test_serve_meeting_rag_service.py
uv run --no-sync ruff check scripts/serve_meeting_rag_service.py tests/test_serve_meeting_rag_service.py
```

현재 검증은 가짜 프로세스·시계·HTTP를 주입한 경계 검사다. 실제 native 호환성·HTTP 전체 흐름·모델 품질·5초 이내 실제 종료·사용자 검수는 미완료다. Windows Java/CPU 프로세스 종료는 강제 종료이며 JVM의 graceful shutdown 증거가 아니다.
