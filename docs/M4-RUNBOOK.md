# M4 자료·학습·평가 재현

이 경로는 로컬 Python 연구용이다. Java 서비스 실행법은 README를 따른다. 원래 M2/M3와 첫 실패를 보존하며, AI 질문·독립 AI 검토·사용자 검수는 구분한다. 현재 사용자 검수는 0개다. 실제 결과와 해석은 [준비 결과](M4-READINESS-RESULTS.md)에 있다.

## 저장된 자료 증거 재생

새 환경에서 Python 3.11과 잠금 의존성을 준비한다. 실행 중인 모델 작업이 있으면 의존성을 동기화하지 않는다.

```powershell
uv sync --frozen --python 3.11
uv run --locked --no-sync python -m scripts.prepare_corpus replay
uv run --locked --no-sync python -m scripts.replay_training_readiness --download-tokenizer-only --version all
```

고정 공개 코퍼스와 tokenizer/config JSON 네 개를 내려받아 해시를 확인한다. 저장된 초안·판정·토큰 영수증에서 원문 pack과 준비 보고서를 재생한다. v1은 `data_ready=false`, v2는 `true`여야 한다. 이 명령에는 모델 가중치·GPU가 필요 없으며 tokenizer 추론을 다시 실행하거나 의미 판정을 다시 하는 것은 아니다. CI도 이 범위다.

## 실제 tokenizer 재실행

```powershell
uv sync --frozen --group retrieval
uv run --locked --group retrieval --no-sync python -m scripts.prepare_models --model e5 --output-dir models
```

모델의 출처·파일 해시는 `data/models/m3-models.json`에 있다. 기존 가중치를 재사용하며 새 학습 가중치는 공개 저장소에 넣지 않는다. 새 환경에서는 아래 명령으로 실제 잘린 입력 pack과 임시 토큰 영수증을 재생한다. 기존 pack이 있으면 기존 공개 영수증 경로에 `--verify`를 사용한다. 일부 출력만 있는 상태에서 덮어쓰거나 지우지 말고 경로와 실패 기록을 먼저 확인한다.

```powershell
uv run --locked --group retrieval --no-sync python -m scripts.prepare_training_ready_v2 tokenize `
  --pilot-dir data/training/m4-pilot-v2 `
  --drafts data/training/generation/m4-fit.draft.jsonl data/training/generation/m4-calibration.draft.jsonl data/training/generation/m4-calibration-supplement-v1.draft.jsonl `
  --author-packs .local/m4-author-fit-v3.json .local/m4-author-calibration-v3.json .local/m4-author-calibration-supplement-v1.json `
  --positive-reviews data/training/reviews/m4-fit-semantic-v1.jsonl data/training/reviews/m4-calibration-semantic-v1.jsonl data/training/reviews/m4-calibration-supplement-semantic-v1.jsonl `
  --negative-reviews data/training/reviews/m4-negative-a-v1.jsonl data/training/reviews/m4-negative-b-v1.jsonl `
  --token-receipt .local/m4-tokenizer-receipt-v2.rebuilt.json
Get-FileHash .local/m4-tokenizer-receipt-v2.rebuilt.json
Get-FileHash data/training/m4-tokenizer-receipt-v2.json
uv run --locked --no-sync python -m scripts.replay_training_readiness --version all
```

두 토큰 영수증의 SHA256이 같아야 한다. GPU 실행기는 공개된 준비 manifest와 실제 로컬 pack을 다시 검증하며, 선택된 음성의 input IDs·attention mask를 모델 로드 전과 매 forward 전에 검사한다. 새 환경에서 자료의 결정적 재생과 같은 GPU 학습 가중치의 비트 단위 재현은 별개다. 드라이버·장치·라이브러리가 다르면 같은 결과라고 주장하지 않는다.

## 조건부 GPU probe와 학습

다음은 실제 실행한 v2 명령이다. 새 checkout에서는 같은 고정 계획을 실행할 수 있지만, 이미 실행한 작업 폴더에서는 실행 claim과 기존 출력 때문에 다시 실행할 수 없다. 실패 결과나 claim을 지워 재시도하지 않는다. 새 비교에는 먼저 별도 계획과 실행기를 고정한다.

```powershell
uv run --locked --group retrieval --no-sync python -m scripts.train_embedding_v2 probe --execution-plan data/training/m4-e5-execution-v2.json --ready-manifest data/training/m4-training-manifest-v2.json --output-dir .local/m4-e5-probe-v2
uv run --locked --group retrieval --no-sync python -m scripts.train_embedding_v2 train --execution-plan data/training/m4-e5-execution-v2.json --ready-manifest data/training/m4-training-manifest-v2.json --probe-report .local/m4-e5-probe-v2/report.json --output-dir .local/m4-e5-train-v2
```

원 실행에서는 두 번째 명령의 probe-report에 로컬 원본과 바이트가 같은 공개 사본 `experiments/results/m4-e5-probe-v2.json`을 사용했다. 새 환경에서는 방금 실행한 로컬 보고서를 사용한다. 성공 probe가 없거나 같은 실행 계획·자료·수치 설정이 아니면 학습을 거부한다. Probe 가중치와 optimizer는 버리고 원 base·seed·optimizer에서 새로 시작한다. 본 학습도 실패하면 부분 갱신 수를 보존하고 중단하며 자동 재시작·배율 탐색·CPU/클라우드 대체를 하지 않는다.

`report.json`은 시도·실제 optimizer 진입·완료·검증·관찰된 가중치 변화와 실패 단계를 분리한다. `progress.jsonl`은 중간 실패에도 실제 진행 기록을 남긴다. 손실 감소나 테스트 통과는 검색 품질 개선의 근거가 아니다.

## 품질 비교의 범위

평가기 `scripts.evaluate_training`의 `checkpoint`는 실제 16회 갱신에 연결된 마지막 저장본의 파일 해시·구조를 확인한다. 평가 계획은 이 manifest, 실제 train/probe 보고서, 입력과 소스를 동결한다. `run`은 원 모델과 마지막 저장본을 원래 train 180문서·2,196청크 및 calibration 16질문에서 같은 FP32·tokenizer로 비교한다. `replay`는 저장 순위의 참조·정렬·지표·판정을 재계산하며 새로운 추론이나 시간 측정이 아니다.

재학습한 저장본의 해시가 다르면 공개된 기존 manifest를 덮어쓰지 않는다. 새 보고서·manifest·평가 계획으로 출처를 연결해야 한다. 원래 최종 test는 열지 않으며, calibration 통과도 별도 main-dev 판단과 서비스 검증을 대신하지 않는다. 학습 가중치가 없는 기본 CI는 이 실제 모델 평가를 수행하지 않는다.

원 실행 저장본이 있는 환경의 명령은 다음과 같다. `checkpoint --verify`와 `replay`는 다시 확인할 수 있고 `run`은 같은 계획의 기존 실행 claim이 없어야 한다. v1.1은 공개 보고서 경로 검사만 고친 계획이며 품질 설정은 v1과 같다.

```powershell
uv run --locked --no-sync python -m scripts.evaluate_training checkpoint --execution-plan data/training/m4-e5-execution-v2.json --ready-manifest data/training/m4-training-manifest-v2.json --train-report experiments/results/m4-e5-train-v2.json --probe-report experiments/results/m4-e5-probe-v2.json --output data/models/m4-terminal-v1.json --verify
uv run --locked --group retrieval --no-sync python -m scripts.evaluate_training run --evaluation-plan data/training/m4-calibration-evaluation-v1.1.json --output-dir .local/m4-calibration-v1
uv run --locked --no-sync python -m scripts.evaluate_training replay --evaluation-plan data/training/m4-calibration-evaluation-v1.1.json --report experiments/results/m4-calibration-v1.json
```

## 실패와 복구

- 준비 v1의 음성 부족·잘림 실패는 v2 성공으로 지우지 않는다.
- `.local` 경로 사전 검사 실패는 모델 로드 전 오류다. v1.1의 비유한 gradient norm 실패는 backward 뒤 optimizer 전 오류다.
- 배율1024의 v2 probe는 별도 사전 계획에 따른 한 번의 비교다. 원인 확정이나 최적 배율 탐색 결과가 아니다.
- 평가 명령의 사전 검사 실패와 실제 추론 실패도 구분한다. 소스 변경 시 새 계획으로 묶고 기존 출력과 실패를 보존한다.
- `.local/m4-execution/active.lock`이 있으면 먼저 살아 있는 작업을 확인한다. 다른 작업의 실행을 복구라는 이유로 중복 시작하지 않는다. 완료·실패 claim을 삭제해 같은 계획을 재실행하지 않는다.

유료 API 요청은 없으며 실제 전력·요청당 금액은 측정하지 않았다. 이 연구의 시간과 GPU 메모리는 Java HTTP 응답시간이나 운영 동시 사용자 용량을 뜻하지 않는다.

후속 비교는 완료된 계획이 hash로 묶은 실행·평가 소스를 수정하지 않고 별도 진입점으로 추가한다. 기존 실행기가 검증을 거부하면 이전 소스와 계획을 확인하며, 과거 보고서의 hash를 새 코드에 맞춰 바꾸지 않는다.
