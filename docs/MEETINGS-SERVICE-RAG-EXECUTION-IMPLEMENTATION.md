# 실제 화면을 통한 서비스 RAG 실행 구현

2026-10-22. [고정된 실행 설계](MEETINGS-SERVICE-RAG-EXECUTION.md)를 구현한 상태와 확인 범위를 기록한다. 실제 로컬 모델의 통합 실행과 답변 품질 수용은 아직 완료되지 않았다.

## 구현한 경로

`scripts/run_meeting_rag_acceptance.py`는 등록된 한 split의 source/item·코드·JAR·UI·CI·역할 binding을 확인하고, 새 실행 폴더를 한 번만 예약한다. 기존 launcher가 Java·CPU 검색·로컬 모델 worker를 시작하며, Node Playwright companion은 실제 React 화면에서 전체 원문6개를 업로드하고 자동 분석4건을 관찰한 다음 원래 질문을 각1회 전송한다. 모든 반환 인용을 열어 원문·revision·좌표를 확인한다.

실행 전용 observer는 기본값이 꺼져 있다. 공식 실행에 한해 분석·답변 요청과 응답을 split 전용 로컬 폴더에 저장하며, 요청의 기존 시간 예산 안에서 작동한다. 공식 CLI에는 모의 응답·모델·질문·검색 설정을 바꾸는 옵션이 없다. Oracle와 문항 선정 설명은 실행 입력에서 제외한다.

첫 실패는 고정 오류 코드·단계·불투명 ID로 별도 보존한다. Node가 보고한 Chromium PID는 살아 있는 부모·생성 시간을 확인한 뒤에만 소유 자원으로 받아들인다. 확인되지 않은 PID나 재사용된 PID를 임의 종료하지 않는다. 이미 소유권을 확인한 자식은 Node 종료 뒤에도 정리하며, 확인 실패나 잔류를 성공으로 기록하지 않는다.

## 검사 증거의 구분

실행기와 observer의 v3 관련 합성 검사는100개가5.40초에 통과했다. 가짜 시계·프로세스·HTTP와 경계 검사를 포함하며 실제 모델 성능은 측정하지 않았다. 초기80개·수정90개·최종100개는 서로 겹치므로 합산하지 않는다. 최초 회귀 실패와 원래 로그는 `.local/service-rag-execution-implementation-v1/`에 보존한다.

실제 Java/React 화면 검사는 별도 작은 합성6문서·6질문과 명시적인 모델 HTTP fixture를 사용한다. 실제 문서 등록·권한·화면 조작을 확인하지만 로컬 모델·토크나이저·공식 평가 자료를 사용하지 않는다. 아래 실패는 이 화면 검사 자체의 결함이며 실제 모델 품질 실패로 분류하지 않는다.

| 실행 | 실제 진행 | 첫 확인 문제 |
| --- | --- | --- |
| 001·002 | 등록3·분석2·답변0 | 목록의 여러 완료 배지와 상세 배지를 구분하지 못함. 001에는 정상 프로세스 종료 관찰 경합도 발생 |
| 003 | 등록5·분석3·답변0 | 두 번째 사용자의 reload 뒤 첫 workspace가 선택되어 해당 회의 상세를 찾지 못함 |
| 004 | 등록6·분석4·권한12·답변0 | 첫 질문 준비에서 timeout. 실제 답변 POST는 전송되지 않음 |
| 005 | 등록6·분석4·권한12·답변0 | 정확한 예외 관측으로 선택지 텍스트를 포함하는 label과 `exact:true`의 불일치 확인. 모델 검색 capabilities는 ready |
| 006 | 등록6·분석4·질문6·인용6·권한12 | 통과,15.013초. 소유PID9개 부재·전후24binding 일치 |

v4는 reload 뒤 실제 사용자 workspace를 다시 선택하는 변경이며 관련 합성3개·구문 검사와 독립 읽기 검토를 마쳤다. v5는 답변 필터 세 곳을 `.knowledge-form` 안에서 찾고 `exact:true`만 제거한다. strict한 단일 요소 검사는 유지하며 첫 요소 선택으로 우회하지 않는다. 관련 합성3개/0.96초·구문 검사와 별도 독립 읽기 검토를 통과했고006 실제 화면에서 끝까지 동작했다. 같은 실행 폴더를 재사용하거나 기존 실패 결과를 덮지 않는다.

[공개 검증 요약](../experiments/results/meetings-service-rag-execution-v1.json)은 현재6코드 hash, 겹치는 검사 수, 각 실패·성공 시도와 로컬 원본 hash를 기록한다. 부모는006의113개 원본 hash와 desktop 인용/mobile 화면을 확인했다. 실제 인용 클릭마다 전체 원문 API·quote·revision·codepoint와 screenshot을 검사했지만 저장 DOM은 main 영역뿐이다. 후속 감사에서 source panel도 main DOM에 있다고 가정한 assertion 실패를 별도로 보존·정정했다. 원본 실행은 재시도하지 않았다.

## 검증 및 공식 실행 방법

관련 코드 검사는 다음과 같다. 이미 저장된 검사와 같은 소스에 대한 불필요한 반복 실행은 하지 않는다.

```powershell
uv run --no-sync pytest -q tests/test_run_meeting_rag_acceptance.py tests/test_meeting_service_rag.py tests/test_meeting_service_rag_launcher.py tests/test_serve_meeting_rag_service.py
uv run --no-sync ruff check scripts/run_meeting_rag_acceptance.py tests/test_run_meeting_rag_acceptance.py src/doctrail/meeting_service_rag.py scripts/serve_meeting_service_rag.py scripts/serve_meeting_rag_service.py
node --check web/scripts/run-meeting-rag-acceptance.mjs
```

공식 실행은 정확한 구현 커밋의 필수 CI와 수용된 원문·문항, 독립 최종 판정 역할, 별도 실행 등록을 먼저 고정해야 한다. 이 문서의 명령은 실행 증거가 아니다.

```powershell
uv run --no-sync python -m scripts.run_meeting_rag_acceptance --enable-real-service-rag-execution --phase calibration --manifest <registered-manifest.json> --run-dir <new-run-directory>
```

실제 요청·원문·답변·화면은 split 담당자만 읽고 부모는 hash·count·status를 확인한다. 원래 calibration6문항의 독립6/6 판정과 운영·정리 수용 전 validation을 실행하지 않는다. 실제 모델 연결, 자연어 정확성, 종합 운영 검증, 최종 test와 사용자 검수, 공개 배포는 각각 별도 미완료 항목이다.
