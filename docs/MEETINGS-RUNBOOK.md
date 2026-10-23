# 회의·지식 Q&A 운영 가이드
## 2026-10-23 다음 진단 준비

[summary-mode-development-v1 설계](MEETINGS-SUMMARY-QUALITY-NEXT.md)는 수용됐지만 실행 준비는 미완료다. 신규 probe/test2의 검증·정확한 source CI, 새 공개 원문4개/독립 기준과 설정 동결 후 별도 once를 배정한다. 실제 실행 명령은 아직 안내하지 않는다. 서비스120초·현재 기본값·닫힌 v3 run은 유지한다. 아래는 이미 소비한 후보의 재현 범위와 역사 기록이다.


## 2026-10-23 원문 대조 재작성 후보

이번에 비교한 명시 후보는 `--analysis-policy batch-v2 --extraction-assembly grounded-summary-v3`다. 초안768·재작성768·최종검토128의 최대3회가 분류를 포함한 같은120초 기한을 공유한다. health와 실행 설정에서 alignment prompt/grammar 해시, 호출상한3·수정1·단계순서가 일치해야 한다. Java/React의 summary_version2와 기본 선택은 바뀌지 않는다.

[서비스 연결](../experiments/results/meetings-grounded-summary-v3-service-v1.json)의849합성 검사와 독립 코드 검토, [정확한 소스 CI](../experiments/results/meetings-grounded-summary-v3-integration-ci-v1.json), 실행기240합성과 [실행 준비](../experiments/results/meetings-grounded-summary-v3-preparation-v1.json) 뒤 실제 once를 마쳤다. [실제 결과](../experiments/results/meetings-grounded-summary-development-v3.json)는 세 번째 자동검토 거부로 실패·소비 상태다. 두 요약 저장·원문 UI만 확인됐고 질문6건은 미실행이다. `run-grounded-summary-v3`/`cli-grounded-summary-v3`는 닫힌 원본이며 재사용·덮어쓰기·재실행하지 않는다. 새로운 후보나 실행은 별도 근거와 사전 계획을 따른다. [독립 쌍 판단](../experiments/results/meetings-grounded-summary-review-v3.json)에서도 핵심충분0/3→0/3·회복0이므로 수용하지 않는다. [성능 관측](../experiments/results/meetings-grounded-summary-performance-v3.json)의 추가 호출 비용과 품질을 구분한다. 아래 v2는 과거 기록이다.

현재849개 합성 검사의 재현 범위는 다음5개 파일이다. 모델·Java·브라우저를 기동하지 않는다.

```powershell
.venv/Scripts/python.exe -X utf8 -m pytest -q tests/test_meeting_grounded_summary.py tests/test_meeting_service_rag.py tests/test_meeting_service_rag_launcher.py tests/test_serve_meeting_rag_service.py tests/test_run_meeting_rag_acceptance.py
```

## 2026-10-23 관계 근거 요약 후보

이전 개발 후보는 `batch-v2` + `grounded-summary-v2`다. 기존 `scripts.serve_meeting_service_rag`와 `scripts.serve_meeting_rag_service`의 선택 인자는 `--analysis-policy batch-v2 --extraction-assembly grounded-summary-v2`이며, 기본 선택을 바꾸지 않는다. v1과 v2의 프롬프트·문법 해시가 다르므로 실행기와 worker health가 같은 후보를 보고해야 한다. 불일치 시 준비 또는 요청을 거부한다.

v2는 조건·예외·시점 등의 관계와 그 양끝 원문을 먼저 연결하고 각 요약 문장에 근거를 붙인다. 저장·화면의 `summary_version=2` 계약은 기존과 같다. [핵심 모듈 검증](../experiments/results/meetings-grounded-summary-v2-module-v1.json)은 합성 검사와 코드 검토이며 실제 요약 개선의 증거가 아니다. 서비스 연결의 관련 합성 회귀761개와 정확한 소스의 push/PR 필수 CI도 통과했다. [실제 v2 비교](../experiments/results/meetings-grounded-summary-development-v2.json)는 세 번째 분석의 자동 검토 거부로 실패했으며 [독립 내용 판단](../experiments/results/meetings-grounded-summary-review-v2.json)은 핵심충분1/부족2이며 선택인용지원9/17로 전체 후보 수용 조건을 충족하지 못했다. 원래 실패와 미실행 질문6건은 유지한다.

모델을 실행하지 않는 회귀 재현은 다음과 같다. 이미 설치된 잠금 환경을 사용하며 명령이 실제 모델이나 브라우저를 시작하지 않는다.

```powershell
.venv/Scripts/python.exe -X utf8 -m pytest -q tests/test_meeting_service_rag.py tests/test_meeting_service_rag_launcher.py tests/test_serve_meeting_rag_service.py tests/test_run_meeting_rag_acceptance.py tests/test_meeting_grounded_summary.py tests/test_meeting_analysis_batch.py tests/test_meeting_extraction_coverage.py
```

실제 비교는 [후속 설계](MEETINGS-GROUNDED-SUMMARY-NEXT.md)의 정확한 소스 CI·실행 설정 고정·별도 한 번 실행 절차를 따른다. v1과 v2 모두 이미 소비된 실행이므로 다시 실행하거나 기존 출력 폴더를 재사용하지 않는다. 후속 후보는 원인·독립 판단을 확인한 뒤 새 계약으로 결정한다. 아래 기존 발췌 요약 실행 경로와 구분한다.

회의 편집 충돌의 서버본 비교·초안 유지·명시적 재저장은 [편집 복구](MEETINGS-EDIT-RECOVERY.md)를 따른다. 이전 답변 후보 C3의 실제2/6 실패와 검증 미개방은 [C3 결과](MEETINGS-C3-RESULTS.md)에 기록했다.

Phase 1의 로컬 운영 절차다. 실행 명령이 준비되어 있다는 사실과 실제 모델·서비스 검증 성공을 구분한다. 최종 실행 결과와 실패, 실제 모델 호출, 합성 회귀, 의미 검토는 [MEETINGS-RESULTS](MEETINGS-RESULTS.md)를 따른다. 이 문서는 검증 통과나 생성 품질을 선언하지 않는다.

## 현재 검증한 회의 관리 실행 경로

실제 분석·회의 관리·화면 검증을 통과한 별도 실험 경로는 **4B GGUF 후보**다. 아래의 의존성·프런트·Java 빌드를 먼저 마친 뒤, 고정 모델/runtime이 준비된 환경에서 실행한다. `--retrieval`은 별도로 준비된 base 검색 모델을 CPU에서 사용한다. 생략하면 BM25로 실행한다.

```text
uv run --locked --group retrieval --no-sync python -m scripts.prepare_meeting_gguf --download
uv run --locked --group retrieval --no-sync python -m scripts.serve_meetings_candidate --retrieval
```

첫 명령은 고정 공개 모델과 runtime을 로컬에 내려받아 해시를 검증한다. 이미 준비된 환경은 `--download` 없이 검증할 수 있다. 기본 실험 DB는 `var/meetings-experimental.sqlite3`, 로그는 `var/meeting-candidate-logs`다. `http://127.0.0.1:8000`에서 계정·작업공간을 만든 뒤 회의를 등록한다. 이 경로에서 실제 분석 4건·운영 33개·브라우저 9개 검사를 통과했다. 자연어 답변 품질은 여전히 미승인이며 이 실행 명령을 전체 1차 완료로 해석하지 않는다. 아래 1.7B 경로는 이전 구현 비교를 위해 보존한다. 새 9B/C0 코드는 현재 오프라인 후보 비교에 한정되며 이 launcher를 자동 교체하지 않는다.

## 기능과 AI의 역할

회의 원문은 기존 문서 저장·파싱·청크·권한 체계를 사용한다. UTF-8 TXT·MD·텍스트 PDF 또는 직접 입력을 등록하면 원문 저장 후 비동기 분석을 요청한다. 파일 저장 성공과 분석 성공은 별개다. 분석에 실패해도 텍스트 추출이 성공한 원문은 조회·키워드 검색할 수 있다.

회의 분석은 Qwen의 **원문 단위 분류**와 결정적 필드 추출을 조합한다. 실제 모델의 다음 token 점수로 열 개 범주 중 하나를 고르고, 선택한 원문에서 인용·위치를 복원한다. 최대 네 구절을 규칙에 따라 선택한 `AI 발췌 요약`은 새로운 문장으로 작성하는 자유 생성 요약이 아니다. 날짜·참석자·담당자·기한·우선순위 값은 모델이 선택한 구절에서 제한된 문법으로 읽는다. 세부 규칙과 누락 가능성은 [MEETINGS-AI](MEETINGS-AI.md)에 있다.

원문에 없거나 규칙으로 확인하지 못한 담당자·기한은 `null`, 참석자는 빈 배열로 남긴다. 화면의 ‘확인 필요’는 오류를 감추기 위한 기본값이 아니다. 문서 소유자는 등록 사용자지만 작업 담당자를 로그인 사용자로 채우지는 않는다. 등록 시각을 회의 날짜로 사용하지 않는다. AI 항목은 `needs_confirmation`으로 시작하며, 모델이 `decision`으로 분류해도 사용자 확정과 다르다.

Q&A는 검색한 원문을 바탕으로 짧은 답변 문장과 인용을 실제 모델이 생성한다. 후보가 없으면 모델을 호출하지 않고 보류한다. 잘못된 JSON·잘린 출력·인용 불일치는 실패이며, 근거 부족 보류와 구분한다. 인용문 일치는 그 답변의 의미가 올바르다는 증거가 아니다.

## 로컬 준비와 실행

저장소 루트에서 Java 21, 고정 Maven wrapper, Node.js, Python 3.11·잠금 의존성을 사용한다. 기존 로컬 Qwen 파일과 retrieval dependency group이 준비되어 있어야 한다. 다른 모델 작업·GPU 점유·실험 lock을 먼저 확인하고, 진행 중 추론과 의존성 동기화를 겹치지 않는다. 잠금을 삭제하거나 기존 작업을 강제 종료해 실행 공간을 만들지 않는다.

처음 설치하는 환경은 CUDA/BF16을 지원하는 NVIDIA GPU와 해당 PyTorch 환경이 필요하다. 현재 생성 경로에는 CPU 자동 대체가 없다. 고정 공개 모델 약 4.08GB를 받는 준비 과정은 아래와 같으며, 이미 파일이 있다면 마지막 명령으로 검증한다. 이전 M5 실험을 다시 실행할 필요는 없다. 인터넷 다운로드와 로컬 디스크·전력은 필요하지만 이 경로는 유료 모델 API를 호출하지 않는다.

```powershell
uv sync --locked --python 3.11 --group retrieval
uv run --locked --group retrieval --no-sync python -m scripts.prepare_generation_model --snapshot models/generation-m5-qwen3-1.7b --download
uv run --locked --group retrieval --no-sync python -m scripts.prepare_generation_model --snapshot models/generation-m5-qwen3-1.7b
```

선택적 E5/BGE 검색은 별도로 `uv run --locked --group retrieval --no-sync python -m scripts.prepare_models --model all --output-dir models`로 고정 가중치를 준비한다. 서비스 실행기가 가중치를 자동으로 내려받지는 않는다. GPU 없이 기본 Java를 실행하면 문서·BM25·회의 원문은 사용할 수 있지만 AI 분석/답변은 미연결 상태다.

```powershell
npm --prefix web ci
npm --prefix web run typecheck
npm --prefix web run build
./server/mvnw.cmd -B -q -f server/pom.xml verify
uv run --no-sync --group retrieval python -m scripts.serve_meetings --port 8000 --worker-port 8092 --no-retrieval
```

마지막 명령은 빌드·다운로드·의존성 설치를 하지 않는다. 기존 JAR와 `models/generation-m5-qwen3-1.7b`를 사용해 Java와 CUDA 생성 worker를 시작한다. 기본 DB는 `var/doctrail-java.sqlite3`, 로그는 `var/meeting-service-logs`다. 각각 `--database`, `--log-dir`, 모델 경로는 `--model-root`, JAR는 `--jar`로 변경한다. 회의 실행기는 지정한 `--database`를 사용하므로 환경변수만 바꿔 복구본을 선택하지 않는다.

`--retrieval`은 E5/BGE 검색 worker를 **CPU**에 추가한다. 기본 `--no-retrieval`에서는 BM25를 사용한다. 이 실행기는 두 모델을 6GB GPU에 함께 올리지 않는다. 검색 방법은 화면에서 선택하며, 모델 검색 장애를 BM25 성공으로 자동 대체하지 않는다. 일반 `scripts/start.ps1`은 웹·Java 실행 경로이며 회의 모델 worker를 자동 시작하지 않는다. `-Backend Python`은 과거 참조 서비스이며 새 회의 Java API를 대신하지 않는다.

브라우저에서 `http://127.0.0.1:8000`을 연다. 종료는 실행 터미널의 Ctrl+C다. 실행기는 자신이 만든 자식 프로세스만 정리한다. 생성 worker의 OS lease는 프로세스 종료 시 해제되며 파일 삭제가 복구 절차가 아니다. 준비 확인 `/health`는 모델 적재 확인이지 답변 품질 확인이 아니다.

## 실제 API

아래 경로는 Java의 `/api` 기준이다. 사용자 식별자는 서버 세션에서 얻는다. 별도 `user_id`를 받아 권한을 부여하지 않는다.

| API | 요청·반환과 제약 |
|---|---|
| `POST /workspaces/{id}/meetings/text` | `{title,content,visibility}`. `201` 회의 상세; 원문 등록 후 분석 자동 요청 |
| `POST /workspaces/{id}/meetings` | multipart `file,title,visibility`. `201` 회의 상세; 파싱 실패도 원문 상태와 구분 |
| `GET /workspaces/{id}/meetings` | 현재 접근 가능한 회의의 `{items}`. 별도 전체 회의 목록 API는 없음 |
| `GET /meetings/{id}` | `{document,meeting}`. 원문·청크, 상태·오류, `source_revision`, 편집 `version`, `ai_analysis`, 활성 `analysis`, `provenance` |
| `POST /meetings/{id}/analyze` | `{expected_revision}`. `202` 비동기 요청; 문서 소유자만 가능, 같은 회의 진행 중 중복 요청은 `409` |
| `PUT /meetings/{id}/analysis` | `{expected_revision,expected_version,analysis}` 전체 스냅샷. 현재 ready 분석의 소유자 편집; 버전 경합은 `409` |
| `GET /meetings/{id}/runs` | 해당 회의의 실행 상태·모델·revision·오류·시각. UI 전용 실행 이력 화면은 없음 |
| `GET /tasks` | 선택 조건 `workspace_id,assignee,status`. 현재 revision의 ready 분석에서 작업을 모아 반환 |
| `GET /meetings/{id}/links` | 양쪽 회의에 현재 접근 가능한 유효 결정 연결. 날짜·제목·결정 문구 포함 |
| `POST /meetings/{id}/links` | 아래 연결 계약. 소유한 현재 회의와 접근 가능한 상대 회의의 사용자 확정 결정 연결, `201` |
| `DELETE /meetings/{id}/links/{linkId}` | 연결 출발 회의 소유자만 해제; 상대 회의 접근권한도 다시 확인, `204` |
| `POST /knowledge/search` | 회의·문서 통합 검색. 필터를 후보 생성 전에 적용 |
| `POST /knowledge/answer` | 같은 필터로 검색 후 생성·인용 검증. 답변 또는 보류; 실패는 오류 상태 |
| `GET /documents/{id}` / `DELETE /documents/{id}` | 기존 원문 조회·소유자 삭제. 회의 삭제도 이 문서 API 사용 |

작업 변경 전용 PATCH는 없다. 회의 상세의 전체 분석을 읽어 항목 ID를 유지하면서 수정하고 CAS PUT으로 저장한다. 분석은 제목·날짜·참석자·목적·요약, `summary_evidence`, `metadata_evidence`, `items`를 포함한다. 각 항목은 `id,type,text,quote,start_offset,end_offset,assignee,due_date,priority,status`를 갖는다. 비작업 항목의 담당자·기한·우선순위는 null이다. 원문 인용은 **Unicode code point** 기준의 정확한 연속 구절이어야 한다.

연결 요청은 `target_meeting_id,source_item_id,target_item_id,relation,expected_revision,expected_version,target_expected_revision,target_expected_version,quote,start_offset,end_offset`를 보낸다. 관계는 `related` 또는 `supersedes`; 후자는 현재 source 결정이 target 결정을 변경한다는 사용자 확인이다. 양쪽 항목은 모두 `decision/confirmed`여야 하고 근거는 source 원문에서 제공한다. 비슷한 문장이나 나중 날짜만으로 변경 연결을 생성하지 않는다.

지식 요청 필드는 `query,workspace_id,kind,meeting_id,date_from,date_to,participant,assignee,item_type,method,limit,expected_embedding_profile`이다. `workspace_id:null`은 현재 접근 가능한 모든 작업공간, `kind`는 `all|meeting|document`, `item_type`은 `decision|action|unresolved` 또는 null이다. 날짜·참석자·작업 조건을 쓰면 일반 문서는 제외된다. 이름 조건은 서버에서 정확히 일치하는 문자열로 비교하며 사용자 계정 연결이 아니다. 검색은 최대 50개, 답변은 최대 10개 후보를 허용한다. 화면은 원문 검색에 10개, 답변에는 관련도 상위 5개를 요청하고 이를 안내한다. 5개라도 전체 prompt 한도를 넘으면 명시적으로 실패하며 후보 본문을 몰래 자르지 않는다.

새 `/knowledge/*` 요청·답변은 현재 검색 이력에 저장하지 않는다. 기존 워크스페이스 문서 검색 이력은 유지하지만 전체 작업공간 Q&A를 그 이력에 임의로 넣지 않는다. 사용자 수정 요약은 검색 근거 본문으로 사용하지 않는다. 검색·인용 대상은 원문 청크이고 분석 메타데이터는 조건 적용에 사용한다.

Python 내부 worker는 Bearer 인증이 있는 `GET /health`, `POST /analyze`, `POST /answer`를 제공한다. DB·사용자 세션·전체 코퍼스에 접근하지 않으며 Java가 허용한 원문만 받는다. Java의 worker URL은 `http://127.0.0.1:<port>`로 제한되고 실행기가 임시 token을 자식 환경에 전달한다. 브라우저는 worker를 직접 호출하지 않는다.

## 저장 구조와 이전 데이터

현재 SQLite `user_version=1`을 유지하면서 시작 시 `CREATE TABLE IF NOT EXISTS`로 아래 테이블을 추가한다. 별도 ORM migration이나 버전 번호를 올리는 변환은 없다. 기존 문서를 자동 회의로 변환하지 않는다.

| 저장 위치 | 역할과 연결 |
|---|---|
| 기존 `documents`, `chunks` | 원본 파일·추출 원문·revision·청크·소유자·공개 범위. 회의도 같은 문서 ID를 사용 |
| `meetings` | document ID에 1:1 연결. 현재 상태·원문 revision·편집 version·최신 AI 초안·활성 분석·provenance |
| `meeting_runs` | 시도별 결과·실패·모델 정보. 새 재시도는 새 run이며 과거 성공·실패를 보존 |
| `meeting_edits` | 사용자 저장마다 분석 스냅샷·편집자·version 기록 |
| `meeting_links` | 두 문서·두 항목·revision·생성 시 version·관계·인용·작성자 |
| `meeting_link_evidence` | 연결 당시 두 결정 항목의 스냅샷. 현재 항목과 비교해 유효성을 확인 |

별도 `meeting_items`나 작업 테이블은 없다. 항목은 분석 JSON에 저장하고 `/tasks`에서 모은다. 날짜·참석자도 활성 분석 JSON에서 읽는다. 이 구현 이름은 초기 설계 문서의 개념 테이블과 구분한다. 과거 연결에 항목 스냅샷이 없으면 현재 연결 목록에서 제외한다. 지원하지 않는 DB 버전은 시작 시 거부한다. 이미 존재하는 테이블의 다른 열 구조를 자동 수선하는 범용 migration은 아니다.

## 재시도·편집·삭제

`queued → running → ready/failed`로 진행한다. Java는 분석 실행 한 개와 대기 여덟 개를 제한한다. 완료 전 세션·멤버십·원문·분석 버전을 다시 검사하며 변경되면 결과를 현재 분석으로 저장하지 않는다. 화면 polling은 상태 조회만 하고 분석을 반복 요청하지 않는다. 자동 무한 재시도는 없다.

동일 원문 재분석 시 사용자 수정본은 유지하고 `ai_analysis`만 새 초안으로 갱신한다. 사용자가 초안을 적용할 때 활성 분석을 바꾼다. 최초 분석 실패와 달리, 같은 revision의 이전 정상 분석이 있는 재분석 실패는 **ready를 유지하면서 `analysis_error`에 최근 실패를 표시**한다. 따라서 ready만 보고 마지막 실행까지 성공했다고 판단하지 않는다. 실행 이력과 오류를 함께 확인한다.

서버 재시작 때 남아 있던 queued/running run은 `generation_interrupted`로 종료 처리한다. 유효한 이전 분석이 있으면 보존하고, 없으면 failed로 남긴다. 사용자가 다시 로그인하고 오류·원문을 확인한 뒤 명시적으로 재시도한다.

회의 화면의 원문은 읽기 전용이며 분석 수정은 원문 revision을 올리지 않는다. 기존 문서 API로 원문 교체·재처리가 발생하면 청크를 교체하고 분석을 stale로 만든다. 오래된 분석의 작업·메타데이터 조건·결정 연결은 현재 결과로 쓰지 않는다. 인용을 열 때도 최신 문서를 다시 읽어 revision과 정확한 구절을 대조한다.

결정 연결은 문서 revision, 현재 확정 상태, 연결 당시 항목 내용으로 유효성을 판단한다. 연결한 결정이 바뀌면 목록에서 제외하고, 관계없는 작업 상태·요약 수정만으로 연결을 버리지는 않는다. 편집 version 경합은 저장 시 CAS로 검사한다. 문서 삭제 시 회의·작업의 원천 분석·run·수정본·양쪽 연결은 외래키 cascade로 삭제되어 더 이상 검색할 수 없다. 휴지통·항목별 복구 기능은 없다.

## 백업과 장애 대응

DB에는 계정·세션·업로드 원문과 모든 회의 기록이 포함된다. 공개 저장소에 넣지 않는다. 운영 변경 전 SQLite backup API로 새 경로에 일관된 백업을 만들고 무결성을 검사한다. 실행 중 DB 파일만 임의 복사하거나 기존 백업을 덮어쓰지 않는다.

```powershell
uv run --no-sync python scripts/backup_db.py --source var/doctrail-java.sqlite3 --output var/backups/before-meetings.sqlite3
```

복구는 서비스 종료 후 새 경로로 한다. `--restore`는 복구본 세션을 삭제하므로 재로그인이 필요하다. 원래 DB와 실패 기록을 보존한다.

```powershell
uv run --no-sync python scripts/backup_db.py --source var/backups/before-meetings.sqlite3 --output var/restored-meetings.sqlite3 --restore
uv run --no-sync --group retrieval python -m scripts.serve_meetings --database var/restored-meetings.sqlite3 --port 8000 --worker-port 8092 --no-retrieval
```

복구 뒤 문서·회의 조회, 작업, 연결, 원문 인용을 점검한다. 모델 파일과 실행 로그는 DB 백업에 포함되지 않으며 별도 관리 대상이다. 모델 파일은 공개 커밋 대상이 아니다.

| 증상 | 확인과 대응 |
|---|---|
| 원문 처리 실패 | 지원 인코딩·텍스트 PDF·파일/페이지 제한 확인. OCR로 우회하지 않음 |
| `generation_disabled` | 원문은 보존됨. 모델 실행기·설정을 확인한 뒤 명시적 재시도 |
| `generation_unavailable` / 응답 검증 실패 | worker 적재·안전한 오류 코드 확인. 성공한 분석이나 답변으로 표시하지 않음 |
| `generation_queue_full` / busy | 중복 모델 작업을 만들지 말고 진행 중 요청 확인 후 재시도 |
| timeout·메모리·입력 한도 | 원문/후보 분량과 GPU 점유 확인. 실패 기록을 남기고 필요하면 자신이 시작한 서비스만 정상 종료·재시작 |
| `409` 버전·검색 문맥 변경 | 최신 원문·분석을 다시 읽고 변경을 확인. 낡은 결과나 편집을 강제 덮어쓰지 않음 |

파서는 5MiB·PDF 100페이지·추출 300,000 code points까지 허용하지만 모델 분석 한도는 더 작다. 현재 worker는 원문 24,000 code points, 최대 6개 토큰 분할·160개 단위, 요청 합계 120초를 제한한다. Q&A 입력은 전체 prompt 4,096 tokens, 출력은 768 tokens다. 조용히 잘라 성공시키지 않는다. **worker의 상세 4xx/5xx가 Java에서는 `generation_unavailable` 등 안전한 일반 오류로 축약될 수 있으므로**, Java 오류 문자열만으로 구체적인 원인을 단정하지 않는다. 원문·질문·token을 운영 로그에 추가해 원인을 추적하지 않는다.

## 보안 경계와 데모

Java는 모든 목록·상세·작업·연결·검색·수정·삭제에서 현재 멤버십과 문서 ACL을 검사한다. 수정·재분석은 문서 소유자만 가능하다. 전체 작업공간 검색도 권한을 적용한 후보만 모델에 전달하며, 생성 전과 응답 반환 전 원문·권한·필터 상태를 다시 확인한다. 프런트엔드는 작업공간/화면 전환 시 이전 요청·poll을 무효화한다. 이미 브라우저가 받은 원문을 권한 변경과 동시에 회수하는 기능은 아니다.

원문은 텍스트로 렌더링하며 업로드 HTML을 실행하지 않는다. HTTP 로컬 쿠키 설정과 loopback worker를 인터넷 배포 보안으로 해석하지 않는다. 공개 배포·유료 API/GPU/cloud 사용은 별도 사용자 승인 대상이다.

데모는 격리된 DB에서 진행한다. 합성 fixture는 합성이라고 밝히고, 공개 회의 자료는 [MEETINGS-DATA](MEETINGS-DATA.md)의 출처·이용 조건을 보존한다.

1. 두 날짜의 회의와 일반 문서를 등록하고 원문 저장·분석 상태를 각각 확인한다.
2. 발췌 요약·제안·결정·미해결·작업의 원문 인용을 열어 의미를 대조한다. 없는 정보는 확인 필요 상태로 둔다.
3. 사용자 수정본을 저장하고 AI 원본이 남아 있는지 확인한다. 작업 상태·담당자·기한을 바꾸고 다시 조회한다.
4. 양쪽 결정만 사용자 확인 후 확정하고, 명시적인 변경 근거로 연결한다. 날짜가 늦다는 이유만으로 연결하지 않는다.
5. 회의와 문서를 함께 검색하고 범위·날짜·참석자 조건을 바꾼다. Q&A의 답변·보류·실패를 구분하고 실제 최신 원문을 연다.
6. 다른 사용자·개인 문서로 누출 여부를 확인한다. 원문 변경 후 stale, 삭제 후 검색 제외를 확인한다.

면접에서는 ‘LLM이 모든 필드를 생성한다’보다 **어디를 모델에 맡겼고 어디를 규칙·권한·원문 검증으로 제한했는지** 설명한다. 발췌 요약을 선택한 이유, 인용과 의미 정확도의 차이, 원문 revision과 분석 version의 차이, 편집 보존·CAS·권한 재검증, 같은 단어의 제안/확정 오분류와 답변 보류 실패를 사례로 설명할 수 있어야 한다. Python 모델 시간과 Java HTTP 전체 응답 시간도 별도 측정치다. 성공 수·실패와 실제 검토 수준은 결과 문서를 인용한다.

## Phase 2 이후 범위

실시간 녹음·음성 전사·화자 분리, 스캔 PDF OCR, 캘린더/회의 도구 자동 수집, 외부 업무 도구 동기화·알림, 자동 결정 변경 추론, Q&A 대화 이력·지속 저장, 자동 자연어 날짜 해석, 생산 서비스 공개 배포·부하 확장·범용 DB migration은 이번 완료 범위에 포함하지 않는다. 기존 M2/M3/M4와 M5 동결 평가를 다시 실행하거나 새 기능의 품질 근거로 대체하지 않는다.


## 실제 분석·라이프사이클만 확인하는 후속 검사

자연어 답변 품질은 아직 실패다. 다음 경로는 기존 전체 서비스 검사를 대체하지 않는다. 고정4B GGUF 준비가 완료된 로컬 환경에서 실험용 native/Python/Java와 선택적 CPU 검색을 함께 켜고, 공개 회의2건·별도 합성 회의2건의 실제 분석과 사용자 편집·결정 연결·작업·권한·revision·삭제를 확인한다. `--ui`는 실제 서비스 세션으로 브라우저를 검사하며 전송 대역을 쓰지 않는다. 쿠키·DB·스크린샷은 무시되는 `.local` 아래에만 저장한다. 새 결과 경로를 사용한다.

```powershell
uv run --locked --group retrieval --no-sync python -m scripts.run_meeting_operations --output .local/meeting-operations-v1 --retrieval --ui
```

분석·작업을 눈으로 볼 수 있도록 ready 회의 삭제 검사는 UI 확인 뒤 수행한다. 모든 자식 프로세스는 해당 실행기가 정리한다. 이 경로는 자연어 답변 호출0이며 성공 상태도 `passed_analysis_lifecycle_only`다. 사람 검수나1차 전체 완료로 기록하지 않는다.
