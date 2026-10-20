# 서비스 RAG 연결과 검증 범위

2026-10-20. 기존 Java/React 서비스에 새 로컬 답변 worker를 연결하는 opt-in 구현이다. 코드 계약·합성 전송·실제 Java 화면을 검증했으며 **새 Python worker와 실제 native 모델까지 연결한 전체 실행은 아직 하지 않았다.** 품질 수용·기본 채택·Phase1 완료가 아니다.

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

2026-10-20 추가 설계이며 아직 구현/실행 결과가 아니다. 신규 `scripts/serve_meeting_rag_service.py`와 그 합성 검사 한 파일만 추가한다. 기존 native context와 Uvicorn Server를 현재 Python 프로세스에 두고 CPU 검색·Java만 소유 자식 프로세스로 시작한다. 서로 다른 임의 token을 메모리/자식 환경에 전달하고 로그에는 남기지 않는다. 기존 모델·답변90초·분석120초·동결 코드는 그대로 사용한다.

실제 Astra xhigh 검토의 정정에 따라 종료는 Java의 새 요청 차단→CPU 종료 요청→worker 종료 요청과 owned native 정리 선발동→worker join→context 최종 정리 순서다. 진행 중인 요청이 native를 기다리는 상태에서 먼저 worker join을 완료하려 하지 않는다. 모든 자체 wait/join은 하나의 남은5초를 사용하며, 기존 native cleanup의 별도5초를 합산 허용하지 않는다. 초과·미종료·오류는 실패로 남기고 소유 자원 정리는 계속한다. 강제 선점을 보장한다는 의미는 아니다.

전체 startup120초는 인증된 generation health·CPU/base retrieval health·Java HTTP 준비와 소유 thread/process 생존까지 측정한다. 기존 동기 hash/context 진입의 늦은 반환은 수용 실패로 기록한다. Uvicorn thread 예외도 호출자에게 전달한다. Java에는 opt-in/base를 명시적 인자로 전달한다. 현재 Java health는 status/version만 제공하므로 pinned JAR와 실행 인자 확인은 설정 확인이며 실제 opt-in 효과 증거가 아니다. 실제 서비스 요청 검증이 별도로 필요하다.

신규 경계의 주입된 factory·clock·HTTP probe로 시작/실패/종료/비밀값 비노출을 검사한다. 기존 frozen 모듈 전역을 바꾸거나 실제 자료·모델·브라우저를 이 합성 검사에 사용하지 않는다.
