# M3 로컬 검색 모델 비교 실행

기존 BM25 서비스는 그대로 실행할 수 있다. 아래 추가 환경은 오프라인 검색 비교용이며 모델이 웹 서비스에 연결되었다는 뜻이 아니다. 실행 결과는 STATUS와 experiments의 보고서로 확인한다. 사용자 검수·최종 test·학습·생성 답변과 구분한다.

## 환경과 모델 준비

저장소 루트에서 실행한다. Python 3.11·uv 잠금 파일을 사용한다. Windows의 선택 버전은 PyTorch 2.10.0+cu128, Transformers 4.57.6이며 모델 실행은 별도 `retrieval` 의존성 그룹에 있다. 기본 CI는 이 그룹이나 가중치를 다운로드하지 않는다.

```powershell
uv sync --frozen --group retrieval
uv run --group retrieval python -m scripts.prepare_models --model all --output-dir models
```

두 모델의 가중치는 합계 약 2.74GB이고 tokenizer·설정 파일이 추가된다. PyTorch의 Windows CUDA 패키지 자체도 약 2.7GiB라 최초 설치는 네트워크 속도에 따라 오래 걸릴 수 있다. 가중치와 로컬 캐시는 Git에서 제외한다. 정해진 공식 리비전의 각 파일 크기·SHA-256을 검증하며 모델 파일과 함께 내려온 Python이나 pickle을 실행하지 않는다. 이미 검증된 파일은 재사용한다. 다운로드 중단 시 `.partial`을 정리하고 해당 파일을 다시 받을 수 있다.

모델 출처·라이선스·해시는 [manifest](../data/models/m3-models.json)에 있다. E5는 MIT, BGE reranker는 Apache-2.0이다. 서로 다른 모델을 한 라이선스로 묶지 않는다. 유료 모델 API 호출이나 GPU 임대는 없다.

## 비교 실행

먼저 [데이터 재현](../data/README.md)으로 공개 원문·정제 파일을 준비한다. 모델 두 개의 해시가 맞고 고정 dev 입력이 재현되어야 시작한다. 고정 실행기는 CUDA 장치를 요구하며 사용할 수 없으면 실패한다. CPU나 BM25로 조용히 대체하지 않는다.

```powershell
uv run --group retrieval python -m scripts.evaluate_retrieval --manifest data/manifests/kubernetes-v1.json --questions data/evaluation/m2-dev-v1.1.jsonl --output experiments/results/my-m3-run.json
```

실행 중에는 코드를 바꾸거나 같은 가상환경의 의존성을 다시 동기화하지 않는다. E5를 먼저 실행하고 GPU에서 해제한 뒤 리랭커를 로드한다. 고정 비교 조건은 [M3-DESIGN](M3-DESIGN.md)과 보고서의 `config`다. 기존 BM25와 top10 순위·점수·지표가 달라지면 중단한다. 모든 실험은 dev만 사용하며 `--split test`는 거부한다.

출력 이름을 새로 정해야 한다. 보고서 또는 같은 이름의 `.stages.jsonl`이 있으면 덮어쓰기를 거부한다. Journal은 단계, 질문 ID, 후보 ID·점수, 자원과 잘림 진단을 남기며 원문 질문·비밀번호·예외 메시지를 운영 로그처럼 흘리지 않는다. 성공 보고서에는 공개 dev 질문과 결과가 포함된다.

실패하면 journal의 마지막 `run_failed`와 직전 단계를 확인한다. 실패한 보고서를 완성 결과로 소개하지 않는다. 같은 입력을 다시 실행할 때도 새 출력 이름을 쓰며, 부분 실행 순위를 성공 실행으로 합치지 않는다. OOM·장치 변경·입력 변경이 필요하면 이유와 새 설정을 동결한 별도 실험으로 남긴다.

## 수치 읽는 법

- `methods`: 기존 M2와 같은 전체 원문 근거 회수 지표. 모델의 512토큰 입력에서 해당 span을 실제 보았는지는 별도 미측정이다.
- `candidate_recall`: 상위50 후보 안의 필수 근거 존재. 실제 상위5에 모든 근거를 배치할 수 있다는 oracle 점수나 답변 정확도가 아니다.
- `paired_comparisons`: 같은 양성 질문에서 개선·퇴보한 ID와 지표 차이. 사람 검수와 통계적 일반화 증거가 아니다.
- `timing.stage_components`: GPU 동기화로 잰 실제 단계 시간. `method_serial_component_sums`는 따로 측정한 단계의 합계이며 실제 HTTP 왕복 시간이 아니다.
- `resources_by_stage`: 50ms 간격 CPU RSS 샘플 peak와 PyTorch GPU allocator peak. 장치 전체 VRAM·전력이나 OS의 정밀 최대값과 구분한다.
- `tokenization_by_stage`와 입력별 진단: 문서·질문·리랭커 쌍의 토큰 길이와 잘림 여부. 합성 warmup은 별도 집계다.

단일 dev 순회, 통제하지 않은 캐시·전원·백그라운드 부하라는 한계가 있다. 반복 분산·인터넷 지연·동시 사용자 부하·전력 비용은 이 명령으로 측정하지 않는다.

## 코드 검사

```powershell
uv run --group retrieval ruff check src tests scripts
uv run --group retrieval pytest -q
```

모델 그룹이 없는 일반 CI에서는 NumPy cosine·Torch tensor pooling 검사 2개가 skip될 수 있다. 나머지 합성 테스트는 입력 계약·RRF·평가·오류 처리를 검사하며 모델 의미 품질을 증명하지 않는다. 실제 GPU 실행과 CI 결과를 별도로 기록한다. 사용한 Transformers가 `torch_dtype` 인자의 deprecation 경고를 출력할 수 있으며 현재 고정 버전에서 실제 로딩 가능 여부는 실행으로 확인한다.
