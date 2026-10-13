# M5 첫 로컬 생성 실험 실행법

현재 범위는 [합성 근거의 제한된 생성·보류 계약](M5-DESIGN.md)이다. Java 질의응답 API나 서비스 채택은 후속 단계다. 완료된 M4 학습·calibration·main-dev를 다시 실행할 필요가 없다. 최종 test는 열지 않는다.

## 모델 준비

Python3.11과 잠금된 선택 의존성을 먼저 준비한다. 실행 중인 학습·추론이 있으면 의존성을 동기화하거나 다른 모델을 올리지 않는다. 현재 계획은 로컬 CUDA/BF16만 사용한다. 유료 API·클라우드나 자동 CPU/다른 모델 fallback은 없다.

```powershell
uv sync --locked --python 3.11 --group retrieval
uv run --locked --group retrieval --no-sync python -m scripts.prepare_generation_model --snapshot models/generation-m5-qwen3-1.7b --download
uv run --locked --group retrieval --no-sync python -m scripts.prepare_generation_model --snapshot models/generation-m5-qwen3-1.7b
```

`--download`를 명시할 때만 공식 고정 revision에서 HTTPS로 받는다. 약4.08GB의11개 파일을 크기·SHA-256으로 확인하고 로컬 weights/LICENSE를 보존한다. 완료된 파일은 다시 받지 않는다. 손상된 기존 파일이나 남은 partial은 덮어쓰지 않고 거절한다. 중단된 파일은 별도 보존한 뒤 원인을 확인한다. 디렉터리 목록의 파일 크기만으로 다운로드가 멈췄다고 단정하지 않는다. CLI의 바이트 진행 기록과 실제 열린 파일의 크기를 확인한다. 가중치·캐시·partial은 Git에 넣지 않는다.

## 고정 실행과 재실행 방지

이 명령은 이미 완료된 결과를 다시 생성하라는 지시가 아니다. 원래 실행 방법의 기록이며, 같은 `run_id`는 다른 출력 폴더를 지정해도 재실행을 거절한다. 먼저 STATUS와 실험 결과, 활성 프로세스·잠금을 확인한다. 새 비교가 필요하면 결과를 보존하고 별도 계획을 만든다.

```powershell
uv run --locked --group retrieval --no-sync python -m scripts.evaluate_generation_smoke --plan data/evaluation/m5-generation-plan-v1.json --snapshot models/generation-m5-qwen3-1.7b --output .local/m5-generation-v1
```

실행 전 입력·모델·프롬프트·소스 바인딩과 깨끗한 Git 상태를 요구한다. 모델 프로세스는 부모가 관리하고 로드는300초, 개별 생성은195초의 외부 감시를 적용한다. 내부 생성 제한180초와 별개다. 종료를 확인하지 못하면 다른 모델 작업이 시작되지 않도록 복구 필요 잠금을 유지한다. 다른 작업의 잠금을 임의로 삭제하지 않는다.

`.local/m5-execution/`의 실행 예약과 기존 `.local/m4-execution/active.lock` 협력 잠금은 재현 통제를 위한 로컬 파일이다. 사용자가 지울 수 없는 OS 보안 장벽은 아니다. 실제 GPU 작업이 끝났는지 확인하기 전에는 수동 초기화하지 않는다. 실행 실패도 예약·보고서·진행 기록을 남긴다.

합성12항목의 결과는 `report.json`, 각 사례 파일, 단계별 `report-*.json`에 저장된다. `journal.jsonl`에는 단계·시간·오류 코드만 남긴다. 합성 원문과 raw 출력은 연구 artifact에서만 공개할 수 있으며 사용자 문서 로깅으로 확대하지 않는다. 형식/인용 거절을 성공한 모델 보류로 계산하지 않는다. 완료하지 않은 사례는 `unfinished_*`로 집계한다. `attempted_model_cases`는 실제 요청을 보낸 횟수여서, 첫 생성 중 자원 실패라면 시도1·완료0·미완료11이다.

## 모델 없는 재생

```powershell
uv run --locked --no-sync python -m scripts.evaluate_generation_smoke --replay experiments/results/m5-generation-v1.json
```

저장 raw 출력에 동일한 스키마·정확 인용 검사와 집계를 적용한다. Torch·Transformers·가중치·GPU를 로드하지 않는다. 재생 통과는 의미 정확도, 원 실행 환경의 완전한 수치 결정성이나 미래 질문 성능을 증명하지 않는다. 별도 AI 의미 검토의 주장·완전성·보류 판단과 사용자 검수0을 함께 읽는다.

자동 검사:

```powershell
uv run --locked --no-sync pytest tests/test_grounded_answer.py tests/test_generation_runtime.py tests/test_generation_smoke.py tests/test_generation_download_progress.py -q
uv run --locked --no-sync ruff check src tests scripts
```

새 모델의 동작을 확인하는 GPU 실행과, 모형을 사용해 오류 경계를 확인하는 위 회귀 검사를 구분한다. CI에는 새 모델 다운로드를 요구하지 않는다.
