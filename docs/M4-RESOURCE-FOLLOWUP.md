# M4 자원 probe의 수치 실패 후속 설계

## 확인한 실패와 남은 불확실성

기존 v1.1 probe는 네 번의 forward와 backward를 마쳤지만 optimizer 호출 전에 실패했다. 저장된 가중 microbatch loss는 순서대로 `1.37548828125`, `0.42852783203125`, `0.8563232421875`, `0.17413330078125`이며 모두 유한하다. 실제 optimizer 진입·완료·검증 및 관찰된 가중치 변경은 모두 0회다. 이 결과는 학습 완료나 자원 조건 통과가 아니다.

보존된 [보고서](../experiments/results/m4-e5-probe-v1.1.json)와 [진행 기록](../experiments/results/m4-e5-probe-v1.1.progress.jsonl)은 로컬 원본과 byte-for-byte 일치한다. 보고서의 오류는 `RuntimeError` 및 `runtime_failed_stop_no_automatic_retry`로만 기록되어 있다. 부모 작업이 실제 실행 도구 session `45501`의 종료 코드 1과 traceback에서 관찰한 구체 오류는 다음과 같다.

> The total norm of order 2.0 for gradients from `parameters` is non-finite, so it cannot be clipped.

위 문구는 별도 stderr 파일이나 보고서 필드로 저장된 증거가 아니다. 부모가 관찰한 traceback이며, 설계 담당자가 재실행하여 확인한 사실로 표현하지 않는다. 부모가 확인한 발생 위치는 `scaler.unscale_` 다음의 `clip_grad_norm_(error_if_nonfinite=True)`다.

보고된 최고 GPU 할당량은 `1523.45849609375 MiB`, 예약량은 `1982 MiB`다. OOM으로 보고된 실패는 없지만 optimizer가 실행되지 않아 AdamW moment 상태까지 포함한 메모리 가능성은 확인되지 않았다. 이 작은 수치를 전체 학습이 메모리에 들어간다는 근거로 사용하지 않는다.

## 사전 등록한 한 번의 비교

[기계 판독 계획](../data/training/m4-resource-followup-v1.json)의 SHA256은 `7d3d5b8c1e66b7831a84c3f461a110ad1fee1023c69837da3ab17e925c474ad6`이다. 변경할 수치 설정은 GradScaler의 초기 loss scale 한 항목으로, `65536.0`에서 `1024.0`으로 낮춘다. 기존 초기값은 실행 계획 및 고정 런타임 생성자의 기본값에서 확인한 값이며, 실패 보고서에 실제 scale 측정값이 기록되어 있었던 것은 아니다.

가설은 높은 초기 loss scale이 FP16 역전파의 비유한 값에 관여했을 가능성이다. 유한한 forward loss와 비유한 gradient norm만으로 그 원인을 확정할 수는 없다. 최초 문제가 생긴 tensor나 연산도 식별하지 못했으며 모델·목적함수·역전파 구현 결함을 배제하지 않는다. `1024`는 이번 진단에서 미리 고정한 단일 값이고 최적값이라는 주장은 없다.

같은 E5 base revision, FP16 autocast, FP32 가중치·optimizer 상태, seed `20261012`, gradient checkpointing, eager attention, TF32 비활성, deterministic 설정을 사용한다. 성장 배수 `2.0`, 감소 배수 `0.5`, 성장 간격 `2000`도 유지한다. 학습률 `1e-5`, weight decay `0.01`, temperature `0.01`, clipping norm `1.0`, 길이 `512`, 명시적 음성 2개 및 in-batch 음성 금지도 그대로다.

Probe는 기존의 다음 8질문을 같은 순서로 사용한다: `005`, `015`, `021`, `025`, `026`, `027`, `030`, `049` (모두 `m4-fit-` 접두부). 질문 2개씩 네 microbatch를 누적해 실제 optimizer update 1회를 확인한다. 각 입력 tensor는 기존과 같은 `[8, 512]`이어야 한다. 새 base·optimizer·scaler에서 시작하고 기존 실패 상태를 이어받지 않는다. 질문·양성·음성·토큰 검토는 새로 선별하지 않으며 fit 64와 calibration 16을 보존한다. Dev/test 질문은 읽지 않는다.

## 실행 전 동결 및 구현 계약

원래 `scripts/train_embedding.py`, `src/doctrail/training.py`, 모든 준비 코드와 실패 실행 계획·결과를 보존한다. 추가 진입점은 `scripts/train_embedding_v2.py`이며 기존 수학·선택·optimizer·schedule을 유지하고 명시적 scaler 생성 인자, 계획 검증, 안전한 단계별 진단 기록만 추가한다. 원래 런타임을 monkeypatch하지 않는다.

부모가 만드는 `data/training/m4-e5-execution-v2.json`은 `execution_id=m4-e5-execution-v2`, 이 후속 계획의 경로·SHA, `numerical_override={"grad_scaler_init_scale":1024.0}`, 새 실행 파일을 포함한 실제 runtime source hash를 묶어 모델 실행 전에 동결한다. 기존 실패 근거 → 후속 계획 → 새 코드·실행 계획 → 새 probe 보고서 순서로 연결하며 미래 출력 해시를 이전 계획에 넣지 않는다. 원본 실패의 로컬 파일 존재는 새 CI의 필요조건이 아니다. 공개된 동일 바이트 보고서·진행 기록을 검증한다.

기존 readiness v2를 재생하고, 실제 검토 pack과 선택 음성의 unpadded input IDs·attention mask를 모델 로드 전과 각 forward 전에 검증한다. 새 출력 디렉터리 `.local/m4-e5-probe-v2`를 사용하며 기존 결과를 덮어쓰지 않는다.

새 보고서는 설정한 초기 scale과 실제 초기 scale, unscale·clipping 전 scale, 도달한 경우 optimizer 전후 scale, 마지막 완료 단계와 실패 단계, 실제 optimizer 진입·완료·검증 횟수와 가중치 변경을 분리해 남긴다. 비유한 norm은 실제 관찰한 경우에만 안전한 원인 코드로 기록한다. 모든 `RuntimeError`를 overflow로 분류하지 않는다. 입력 원문은 로그에 쓰지 않으며 진단을 위한 추가 forward/backward나 재시도도 하지 않는다.

## 통과, 중단, 이후 진행

통과하려면 같은 입력의 네 loss와 backward, unscale, 유한 gradient norm 및 clipping, 실제 AdamW update 1회와 유한 가중치 변경, optimizer 상태 증가가 모두 확인되어야 한다. 그 전체 update를 포함한 최고 할당량은 기존 상한 `5376 MiB` 이하여야 한다. Scale에 따른 update skip, OOM, 입력 불일치, 소스·base 무결성 실패는 모두 실패다.

실패하면 해당 시점까지 실제 수행된 단계와 부분 업데이트를 기록하고 본학습 전에 멈춘다. 자동 재시도, scale sweep, precision·batch·길이·목적함수 변경, CPU·클라우드 대체는 없다. 이후 비교가 필요하면 새 실패 근거를 분석하여 별도 버전 계획을 먼저 작성한다.

이 정확한 실행 계획의 probe가 통과한 경우에만 새 base·optimizer·scaler와 같은 seed로 초기화해 `.local/m4-e5-train-v2`에서 원래 2 epoch·최대 16 step recipe를 진행할 수 있다. 본학습도 초기 scale `1024`를 쓰며 probe 가중치나 optimizer 상태는 가져오지 않는다. 본학습 실패도 실제 부분 실행을 보존하고 멈춘다.

현재 상태는 자료 준비 통과, 기존 자원 probe 실패, 후속 probe 미실행, 학습 미실행이다. 후속 probe 성공은 scale 민감성 가설에 부합하는 한 번의 관찰일 뿐 원인 확정·모든 batch의 자원 가능성·검색 품질 향상·Java 성능 검증을 뜻하지 않는다. 사용자 검수는 계속 대기 상태다.
