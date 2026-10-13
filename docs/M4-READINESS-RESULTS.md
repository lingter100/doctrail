# M4 학습 준비 검증과 발견한 실패

이 문서는 실제 자료 검수·CPU tokenizer·GPU 학습의 단계별 결과다. 아래 v1/v2 자료 준비와 실제 학습·검색 품질은 별개로 읽는다. 질문과 의미 판정은 AI 작성·검토이며 사용자 검수는 0개다.

## v1 실제 결과

사전 선택을 보존한 보충 문서 1개에서 calibration 질문 2개를 추가했다. 원래 fit64·calibration14개는 바꾸지 않았고 새 `m4-pilot-v2`에 80개를 컴파일했다. 독립 AI가 보충 두 질문을 수락했다. 자료는 fit16계열·calibration5계열, 한국어60·영어20질문이다.

| 검사 | 실제 관측 |
|---|---|
| 양성 의미 검토 | 전체80개 accept, 사용자 검수0 |
| 원래 순위의 음성 후보 검토 | 256개: negative244 / relevant4 / ambiguous8 |
| 음성 두 개 확보 | 63/64질문. `m4-fit-048`은 0개 |
| 고정 E5 tokenizer | 80/80질문의 전체 입력 및 선택된 양성 인용 토큰 보존 |
| 선택한 음성의 전체 입력 보존 | 12질문에서 잘림 발생 |
| 최종 v1 상태 | `data_ready=false`, `probe_allowed=false`, probe·학습 미실행 |

계약·구현을 `aeed064`·`0660faa`에서 먼저 고정했고 실제 토큰 영수증과 실패 manifest를 `4e70f38`에 보존했다. 실제 CPU tokenizer 실행과 저장된 영수증의 결정적 재생은 다른 검사다. 재생만으로 tokenizer를 다시 실행했다고 주장하지 않는다.

원본은 [v1 토큰 영수증](../data/training/m4-tokenizer-receipt-v1.json)과 [v1 준비 보고서](../data/training/m4-training-manifest-v1.json)다. 전체 원문은 공개 저장소에 추가하지 않고 고정 공개 코퍼스에서 재생한다.

## 실패가 알려 준 것

`m4-fit-048`은 다른 namespace의 Service를 DNS로 찾는 질문이다. 첫 네 후보 중 두 개는 실제 대체 정답을 제공했고 나머지 두 개도 namespace 조건이 불완전한 관련 예시였다. 원래 정답 목록에 없다는 이유로 이를 음성으로 사용했다면 정답 문서와 질문을 멀어지도록 학습시킬 수 있었다. 전체 검수에서도 대체 정답 4개를 발견했다. 이 발견을 기존 평가 정답에 자동 추가하거나 기존 지표에 소급 반영하지 않았다.

입력 잘림은 또 다른 문제다. 전체 문서가 질문을 지지하지 않아도, 모델에 보이는 앞부분에서 조건이나 부정 표현이 사라졌는지는 확인해야 한다. v1에서는 전체 음성 입력이 조금이라도 잘리면 준비를 차단했다. 실제로 막힌 질문은 `005,015,021,025,026,027,030,049,050,051,053,055`다. 이 검사가 실패했다고 이미 잘못된 학습이 수행된 것은 아니다.

후속 v2는 원래 후보와 실패를 보존하면서 부족한 질문의 다음 네 후보만 검토하고, 이미 선택한 음성의 실제 잘린 모델 입력을 별도로 검토하도록 설계한다. 길이가 짧거나 학습하기 쉬운 뒤 후보로 교체하지 않는다. v2의 준비 통과·자원 probe·본 학습 상태는 실제 산출물이 생긴 후 별도로 기록한다.

## 재현과 해석

```powershell
uv run --locked --no-sync python -m scripts.replay_training_readiness --download-tokenizer-only
```

새 환경에서는 먼저 `uv sync --frozen --python 3.11`과 `uv run python -m scripts.prepare_corpus replay`로 잠금 환경·원문 캐시를 준비한다. 위 명령은 공개 고정 tokenizer/config JSON 네 개만 내려받아 hash를 검사한다. 모델 가중치나 GPU 라이브러리를 받지 않으며 원문 pack과 저장된 검수·토큰 영수증을 재생한다. 실제 tokenizer 재실행은 별도 `retrieval` 환경과 `prepare_training_ready tokenize --verify`가 필요하다.

면접에서는 “검색된 비정답 문서를 그대로 음성으로 학습하지 않고, 대체 정답과 입력 잘림을 실제로 발견해 학습을 막았다”고 설명할 수 있다. 자동 검사 통과를 사람 검수나 학습 효과로 표현해서는 안 된다. 사용자가 확인할 부분은 질문의 실용성, 대체 정답 판단, 잘린 문맥에서 조건이 바뀌는지다.


## v2에서 실제로 보완한 범위

새 계획 `5e6400c`를 고정한 뒤 fit048의 다음 후보 네 개를 검토했다. 원래 rank6·7·8은 negative, rank9는 ambiguous였다. 음성 선택은 기존 순서의 rank6·7이며 나머지63개 질문의 두 음성은 그대로다. 기존 v1의 relevant·ambiguous 판정을 바꾸지 않았다.

소스 `51726f2`를 고정한 뒤 선택 음성128쌍/서로 다른93청크를 실제 CPU tokenizer로 처리했다. 기존12개 질문-청크 쌍(서로 다른8청크)이 잘렸고 추가 선택한048의 두 음성은 잘리지 않았다. 별도 `tokenize --verify`에서 token 영수증과 비공개 실제 입력 pack의 바이트 일치를 확인했다. 원문·token ID·offset·decode 전체는 로컬에 보존하고 공개 파일에는 참조·수량·hash를 기록한다.

실제 잘린 입력12쌍은 별도 AI 검토에서 모두 negative였다. 각 질문별로 잘림이 판정에 미친 영향을 기록했다. v2 compile과 v1·v2 전체 replay를 통과해 `data_ready=true`, `probe_allowed=true`가 됐다. v1 실패는 그대로이며 사용자 검수는0이다. 모델 없는 CI는 저장된 증거 연결을 재생하는 범위이며 실제 tokenizer 재실행과 구분한다.


## 실제 GPU 실행 전 경로 오류

첫 probe 명령은 자료 폴더 `.local`을 허용하지 않는 경로 검사 결함으로 사전 검사에서 실패했다. `.local/` 하위 경로만 허용하면서 폴더 자체를 빠뜨린 것이다. [실패 기록](../experiments/results/m4-e5-preflight-v1-failed.json)에 남겼으며 모델 로드·GPU probe·optimizer 갱신·실행 claim 생성은 모두 없었다. 실제 GPU 메모리 실패로 해석하지 않는다. 같은 데이터·학습 설정을 유지하고 경로 검사와 실행 소스 hash만 새 계획에 반영한다.


## 첫 실제 GPU probe의 수치 실패

[v1.1 GPU report](../experiments/results/m4-e5-probe-v1.1.json)와 [진행 journal](../experiments/results/m4-e5-probe-v1.1.progress.jsonl)은 실제 실행 원본과 바이트가 같다. 네 microbatch의 유한 loss와 backward 완료 후 optimizer 전에 실패했다. 부모가 도구의 traceback에서 `clip_grad_norm_`의 비유한 gradient norm 오류를 확인했다. 원래 report에는 generic runtime failure만 저장돼 있으므로 이 상세 원인을 report 필드인 것처럼 표현하지 않는다.

실제 optimizer 호출·완료·검증·관찰 가중치 변화는 모두0이다. GPU peak allocated는1,523.46MiB, reserved는1,982MiB이며 OOM은 아니었다. AdamW moments 생성 전의 최고치이므로 이 수치를 전체 학습 메모리로 소개할 수 없다. 총 실행시간11.41초는 이 실패한 probe 실행 범위이며 서비스 요청 지연이나 학습 완료 시간과 다르다.

FP16에서 초기 GradScaler 배율65536이 영향을 줬다는 가설을 세웠지만, 유한 forward와 비유한 gradient만으로 원인을 확정하지 않았다. 같은 데이터·모델·batch·seed·목적함수에서 배율1024 한 가지를 별도 계획으로 비교한다. 원래 실패와 runner는 보존한다. 후속 probe가 통과해야 본16-step 학습을 할 수 있다.

## 고정 배율 후속 probe와 실제 학습

계획 `790e931`, 실행기·실행 계획 `04876bd`를 먼저 커밋한 뒤 한 번의 후속 probe를 실행했다. [v2 probe](../experiments/results/m4-e5-probe-v2.json)는 같은 네 weighted loss를 기록했고, 초기/현재 scale1024, clipping 전 norm56.11948, 실제 AdamW 갱신1회를 확인했다. 최고 할당2612.10MiB·예약3148MiB, 실행17.66초다. 기존 실패를 재작성하지 않았고 이 성공만으로 처음 비유한 값이 생긴 연산을 확정하지 않는다.

원래 base·새 optimizer·같은 seed로 시작한 [본 학습](../experiments/results/m4-e5-train-v2.json)은 fit64질문을 두 epoch 처리해16회 갱신 모두 실제 진입·완료·가중치 변화까지 확인했다. 마지막 checkpoint 하나만 저장했다. 최고 할당2789.22MiB·예약3414MiB, 전체 실행43.71초였고 optimizer 구간 바깥의 모델 준비·저장·무결성 확인도 포함한다. Epoch별 기록된 평균 loss는0.96707→0.19231이지만 검색 향상의 증거로 쓰지 않는다.

가중치 SHA256은 `cfbb2be999370a594f36ceffefaaf9696b865e8f4a46df77841853b5a3a907c7`이다. 실제 파일은 로컬에만 있고 공개 [terminal manifest](../data/models/m4-terminal-v1.json)가 파일 크기·hash와 train/probe 출처를 연결한다. 공개 report·journal은 로컬 원본과 바이트가 같다. 서비스에 학습 저장본을 적용하지 않았다. 실행법·복구는 [M4-RUNBOOK](M4-RUNBOOK.md)에 있다.

Calibration 첫 명령은 공개 train/probe report의 경로를 평가기가 허용하지 않아 모델 로드 전에 거부됐다. [사전 검사 실패](../experiments/results/m4-calibration-preflight-v1-failed.json)를 보존하고 해당 보고서 경로만 허용하는 수정과 새 평가 계획을 동결한다. 이 오류는 품질 평가 실패나 낮은 모델 점수가 아니다.

## 실제 내부 calibration 비교

경로 검사만 고친 v1.1 계획·소스 `aa8b568`을 동결한 뒤 원 모델과 마지막 저장본을 실제 CUDA FP32로 한 번씩 평가했다. train 전체180문서·2196청크에서 내부 검증16질문만 사용했다. [보고서](../experiments/results/m4-calibration-v1.json)의 모든 순위·근거 참조·집계·판정 replay도 통과했다.

| 지표 | 원 모델 | 학습 마지막 저장본 |
|---|---:|---:|
| 주석된 전체 근거 @50 | 13/16 (81.25%) | 15/16 (93.75%) |
| 주석된 전체 근거 @5 | 8/16 (50.00%) | 11/16 (68.75%) |
| 근거 청크 MRR@10 | 0.30156 | 0.60129 |
| 상위10청크 안 문서 hit@5 | 10/16 | 15/16 |
| Query encode+dense rank p50/p95 | 12.419/15.861ms | 13.513/18.907ms |

Primary 회복은001·005이며 @50 추가 퇴보는0이다. @5는6개 회복·3개 퇴보(010·014·015)가 함께 있어 순증3개다.016은 두 모델 모두 top50에서 주석 근거를 놓쳤다. 시간은 passage embedding을 미리 만든 뒤 질문 encoding과 dense rank만 측정한 단일 로컬 순회이며 Java HTTP·서비스 SLO·속도 개선 주장이 아니다. 초기 모델 로드·문서 prefill은 별도 report에 남긴다.

사전 조건인 @50 순증1개 이상·@5 총수 비감소를 통과해 별도 main-dev 비교의 후보가 됐다. 서비스 기본 모델 교체나 최종 품질 검증 완료를 뜻하지 않는다. AI 작성16질문·5개 calibration 문서 계열의 작은 표본이고 사용자 검수는0이다. [사례별 분석](M4-CALIBRATION-ANALYSIS.md)에 불리한 결과도 남기며 이 calibration 점수로 새 epoch·seed·음성을 탐색하지 않는다.

주석의 한계도 확인했다.001은 고정 영어 근거가 회복됐지만 원 모델의1위 한국어 번역 청크도 질문에 답한다.002 역시 주석 표 행 밖의 대체 설명이 있다. 고정 지표는 변경하지 않고 정성적으로 구분한다. 위 수치는 **주석된 근거 회수**의 개선이며 그만큼 새 질문에 답할 수 있게 됐다는 뜻이 아니다.
