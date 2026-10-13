# Java 검색과 Python 모델 추론

Java 21 서비스에서 기본 BM25와 E5 의미 검색, BM25+E5 혼합 검색, BGE 재정렬을 선택한다. Python은 이미 검증한 공개 모델의 추론만 담당한다. 로그인·권한·문서·분할·검색 정책·이력·피드백은 Java가 처리한다. [구조 결정](decisions/0004-model-serving.md), [API](API-CONTRACT.md)를 참고한다.

## 로컬 실행

먼저 기본 서비스를 종료하고 프런트엔드와 Java JAR을 빌드한다. 같은 DB/포트의 서비스를 중복 실행하지 않는다.

```powershell
npm --prefix web ci
npm --prefix web run build
./server/mvnw.cmd -B -q -f server/pom.xml verify
```

모델 설치는 [M3 실행 문서](M3-RUNBOOK.md)의 고정 manifest와 hash 검증을 따른다. 이미 설치된 retrieval 환경에서는 다음처럼 실행한다. 추론 중 의존성을 동기화하지 않는다.

```powershell
uv run --locked --group retrieval --no-sync python -m scripts.serve_models --device cuda
```

`http://127.0.0.1:8000`에서 로그인하고 검색 방식을 고른다. Worker는 `127.0.0.1:8091`만 사용한다. 실행기가 무작위 내부 token을 생성해 두 자식 프로세스에만 전달하며 출력하거나 파일에 저장하지 않는다. `Ctrl+C`는 소유한 두 프로세스를 종료한다. 모델을 자동 다운로드하거나 유료 자원을 생성하지 않는다. CPU 실행은 `--device cpu`로 명시해야 하며 속도·메모리 검증은 별도로 필요하다.

옵션 `--database`, `--port`, `--worker-port`, `--model-root`, `--log-dir`를 지원한다. 기본 DB는 `var/doctrail-java.sqlite3`; 기존 자료를 초기화하지 않는다. 모델 cache는 메모리에만 있고 재시작하면 비워진다. 기본 실행 `scripts/start.ps1`과 `java -jar ...`는 모델 환경변수 없이 BM25만 제공한다.

별도 프로세스를 직접 관리할 때는 Java에 `DOCTRAIL_INFERENCE_URL=http://127.0.0.1:<port>`와 worker와 동일한 `DOCTRAIL_INFERENCE_TOKEN`(32자 이상 출력 가능한 ASCII)을 설정한다. Token은 비밀 환경변수이며 프런트엔드·Git·명령 기록에 넣지 않는다. Worker 실행은 `python -m doctrail.inference --device cuda --port <port>`다. 원격 주소, 프록시, 리다이렉트는 허용하지 않는다. `/health`도 token이 필요하다.

## 실패와 복구

- 준비 실패: `var/model-service-logs/`의 안전한 시작 오류를 확인한다. 모델 파일 hash·선택 장치·포트 점유·retrieval 의존성을 확인하고 다시 실행한다. 런처는 시작 실패 시 자신이 띄운 프로세스를 정리한다.
- 모델 중단·잘못된 응답: 503을 반환하고 검색 기록을 만들지 않는다. 화면에서 명시적으로 키워드 검색을 선택하면 BM25를 사용할 수 있다. 자동으로 검색 방식을 바꾸지 않는다.
- 동시 모델 검색: Java와 worker 각각 한 번에 하나만 허용한다. 다른 모델 요청은 즉시 busy 오류를 받는다. 자동 재시도 폭주를 만들지 않고 사용자가 다시 검색한다.
- 문서/권한 변경 중 추론: 409를 반환한다. 같은 질문을 다시 실행하면 최신 권한·문서로 계산한다. 삭제 문서의 cache vector는 결과 후보가 될 수 없다.
- 120초 deadline: 504를 반환한다. 진행 중 GPU 연산을 강제 종료한다는 뜻은 아니다. Worker는 실제 추론 종료까지 lock을 유지한다.
- DB 복구: 기존 [백업·복구](OPERATIONS.md)를 따른다. 추가 `search_metadata` 테이블은 v1 문서·이력 스키마를 보존하며 metadata 없는 이력은 BM25로 읽는다. 모델 token/cache는 백업 대상이 아니다.

Java와 worker의 요청 ID는 각각 독립적이다. 분산 추적 전파는 구현하지 않았다. 일반 요청 로그에 질문·원문·비밀번호·세션 token을 넣지 않는다. 사용자가 보는 검색 이력의 질문은 기능을 위한 저장 데이터이며 운영 로그와 구분한다.

## 재현 가능한 검증

가벼운 CI는 합성 벡터·점수로 worker 계약과 권한/변경 경합을 검사하며 무거운 모델을 설치하지 않는다. 아래는 실제 로컬 모델을 실행하는 별도 검사다. 자동 합성 계정·문서와 임시 DB를 만들고 종료 후 자신의 프로세스를 정리한다.

```powershell
# web/node_modules와 Chromium이 준비된 상태에서 실행
uv run --locked --group retrieval --no-sync python -m scripts.verify_model_service --device cuda --browser --output .local/model-service-check.json
```

출력 파일이 있으면 덮어쓰지 않는다. 성공 보고서는 모든 검사를 통과한 경우에만 생성한다. 실행 실패는 성공으로 기록하지 않고 원인을 분석한 뒤 새 실행을 구분한다. 현재 검증 증거는 [STATUS](STATUS.md)에 연결한다.

## 해석과 면접 설명

해결한 문제는 검색 모델을 붙였을 때 문서 권한과 최신성이 깨질 수 있다는 점이다. 추론 전 ACL로 후보를 제한하고, 느린 모델 호출 뒤 DB 안에서 권한·버전을 다시 확인한다. 모델 호출 동안 DB 쓰기를 막는 방식과 비교해 수정 요청을 허용하면서 오래된 결과를 폐기할 수 있다.

ONNX를 Java에서 직접 실행하는 대안도 있다. 지금은 이미 실측한 PyTorch tokenizer·pooling·precision 설정을 유지하고, Java 서비스 전환과 모델 변환 오차를 한꺼번에 바꾸지 않기로 했다. Python에 검색/권한을 맡기는 대안은 Java의 서비스 책임과 어긋나므로 채택하지 않았다.

한계는 명확하다. 전체 가시 청크를 매 검색 인코딩/cache 조회한 뒤 Java에서 정확 cosine을 계산한다. 4,096청크 상한, 메모리 cache 4,096개, 직렬 추론이므로 대규모·고동시성 서비스가 아니다. 벡터 DB·비동기 인덱스·캐시 영속화는 아직 도입하지 않았다. Dense top-k가 나왔다는 이유로 답할 근거가 충분하다고 판단하지 않는다. 답변 생성·보류·상충 문서 판단은 다음 단계다.

사용자는 실제 화면의 문서 탐색과 근거 읽기 편의성을 직접 검토할 수 있다. 이 검토가 끝나기 전에는 사용성 검증이나 사용자 만족도로 기록하지 않는다. 현재 AI/자동 검사와 사용자 검수는 [CONTRIBUTIONS](CONTRIBUTIONS.md)에 구분한다.

## 고정 M4 학습 모델의 명시적 실험 실행

이 경로는 마지막 학습 저장본 하나를 연결하는 별도 로컬 실험이다. 기본 모델 채택이 아니다. [설계와 검사 범위](M4-OPERATIONS-DESIGN.md)를 따른다. 기존 모델 설치와 `.local/m4-e5-train-v2/terminal`의 동일 가중치가 필요하며 자동 다운로드·학습을 하지 않는다. 가중치 없는 공개 저장소에서는 무거운 모델 없이 계약 검사만 실행할 수 있다.

```powershell
uv run --locked --group retrieval --no-sync python -m scripts.serve_terminal_models --device cuda
```

기본 DB는 `var/doctrail-terminal-experimental.sqlite3`다. 일반 DB와 구분되며 `--database`로 명시할 수 있다. 실행기는 Java profile을 `m4-terminal-v1`으로 설정하고 원래 tokenizer와 고정 checkpoint 파일·영수증을 시작 전후 검증한다. 화면은 “학습 실험 모델”을 표시한다. 모델 없는 기본 검색은 계속 BM25다.

기존 base로 복귀하려면 먼저 실험 실행기를 종료하고 같은 DB를 지정하되 서버 기대 profile도 base로 명시한다. 파일을 삭제하거나 학습을 다시 하지 않는다.

```powershell
$env:DOCTRAIL_EMBEDDING_PROFILE = 'base'
uv run --locked --group retrieval --no-sync python -m scripts.serve_models --device cuda --database var/doctrail-terminal-experimental.sqlite3
```

추가 `search_model_metadata` 테이블은 성공한 검색 당시의 모델 식별자를 보존한다. 모델 정보가 없는 과거 이력은 추정하지 않는다. 다른 모델의 이력은 화면 안내를 확인한 뒤 새 검색으로 실행한다. 서버는 `expected_embedding_profile` 불일치를409 `embedding_profile_changed`로 거부하며, 이 실패로 새 검색 이력을 만들지 않는다.

실제 로컬 GPU 운영 검증은 새 출력 폴더를 요구하며 임시 합성 DB를 정리한다. 실패도 report·단계 journal을 보존한다. Raw 자식 프로세스 로그는 개인 경로가 포함될 수 있어 `.local`에만 남기며 공개 보고서와 구분한다.

```powershell
uv run --locked --group retrieval --no-sync python -m scripts.verify_terminal_service --browser --output-dir .local/m4-terminal-service-new-attempt
```

보고서는 worker+Java 준비 시간과 HTTP 요청 시간을 구분한다. 소수의 순차 요청은 cache를 공유하므로 속도 우위나 부하 성능의 근거로 사용하지 않는다. 실제 결과·실패·시도 이름은 STATUS를 따른다. 완료된 calibration/main-dev와 최종 test는 이 명령으로 실행하지 않는다.
