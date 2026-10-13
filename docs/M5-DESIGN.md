# M5 · 근거 기반 답변과 보류의 첫 실행 계약

기준일: 2026-10-13. 이 문서는 **새 로컬 생성 모델의 제한된 합성 smoke와 이후 평가·서비스 경계**를 고정한다. 실제 실행 결과는 별도 보고서에 남긴다. 문서를 작성했다는 사실은 모델 로드·생성 성공이나 M5 완료를 의미하지 않는다.

M4의 완료된 학습·calibration·main-dev와 운영 결과를 보존한다. Main-dev의 다중 문서 전체 근거 @5는 1→0/7로 퇴보했으므로 생성 모델이 누락된 사실을 보충하도록 기대하지 않는다. 기본 BM25/base와 명시적 terminal 실험 경로를 그대로 둔다. 기존 dev·calibration으로 새로운 프롬프트·검색 설정을 탐색하거나 최종 test를 읽지 않는다. [직전 판단](M4-OPERATIONS-RESULTS.md), [로드맵](roadmap.md)을 따른다.

## 1. 이번에 확인할 질문과 범위

첫 가설은 “현재 6GB 로컬 GPU와 잠금 환경에서 작은 다국어 생성 모델이 짧은 합성 문맥을 읽고, 원문에 연결 가능한 제한된 JSON 답변 또는 보류를 생성할 수 있는가”다. 실제 모델 가중치를 로드한 관측과 모델 없이 검사한 계약을 구분한다.

| 단계 | 산출물 | 완료로 주장할 수 없는 것 |
|---|---|---|
| M5-A, 이번 묶음 | 모델·라이선스·입력·프롬프트 고정, 실제 GPU 자원/생성 smoke, 엄격한 인용 검증, 실패 보존 | 실제 문서의 답변 품질, Java HTTP 속도, 권한 경합, 서비스 채택 |
| M5-B, 별도 사전등록 | 새 generation calibration과 독립 validation, 주장 지지·답변 범위·보류 분석 | 기존 retrieval dev/test의 새 성능, 사용자 검수, 자동 일반화 보장 |
| M5-C, 후속 구현 | Java 세션/ACL/리비전 재검사, loopback 생성 추론, React의 답변·근거·보류, 실제 운영 검사 | 최종 test 개방이나 외부 서비스 공개 승인 |

첫 실행에는 검색·리랭커 모델을 같이 올리지 않는다. 이미 검색된 것처럼 **명시적으로 제공한 합성 evidence**만 사용한다. 따라서 여기서 검증한 문맥 처리와 실제 retrieval→generation 경로는 별개다. Python은 추론·데이터·평가를 맡으며 Java 서비스의 업무 판단을 대신하는 subprocess를 추가하지 않는다.

## 2. 생성 모델 선택과 출처

고정 후보는 `Qwen/Qwen3-1.7B`, revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`다. 최신 모델이라는 이유가 아니라 기존 `transformers==4.57.6`에서 native 모델 클래스를 사용할 수 있고, 작은 다국어 모델의 실행·실패를 분리하기 위해 선택했다. 선택 시점의 공식 카드에는 Transformers 4.51.0 미만의 비호환과 `enable_thinking=False` hard switch가 명시돼 있다. [공식 모델 카드](https://huggingface.co/Qwen/Qwen3-1.7B), [고정 snapshot](https://huggingface.co/Qwen/Qwen3-1.7B/tree/70d244cc86ccca08cf5af4e1e306ecf908b1ad5e).

Qwen의 공식 언어 목록에는 영어와 한국어가 포함된다. 이는 제공자가 설명한 지원 범위이며 DocTrail 한국어 품질을 확인한 결과가 아니다. [공식 Qwen3 발표](https://qwenlm.github.io/blog/qwen3/).

| 후보 | 확인한 사실 | 이번 선택 |
|---|---|---|
| Qwen3-1.7B | Apache-2.0, native Qwen3, non-thinking 모드 | 고정한 첫 실행 후보 |
| Qwen3-0.6B | 같은 Qwen3 계열의 더 작은 Apache-2.0 모델 | 메모리 대안. 1.7B 실패를 남긴 뒤 새 계획을 만들 때만 검토 |
| Qwen3.5-0.8B | 현재 공개된 Apache-2.0 모델. 공식 사용 안내는 새로운 `qwen3_5`/multimodal 클래스와 Transformers 최신 main 설치를 제시 | 동결된 4.57.6 환경에 즉시 섞지 않음. 작은 수치만으로 드롭인 호환을 가정하지 않음 |
| Gemma 3 1B IT | 별도 Gemma 라이선스, Hugging Face의 사용 조건 수락 경로 | 라이선스·접근 경계가 추가돼 첫 실행에서는 선택하지 않음 |

대안 출처: [Qwen3-0.6B 공식 카드](https://huggingface.co/Qwen/Qwen3-0.6B), [Qwen3.5-0.8B 공식 카드](https://huggingface.co/Qwen/Qwen3.5-0.8B), [Gemma 3 1B 공식 카드](https://huggingface.co/google/gemma-3-1b-it). 이 표는 로컬 모델 간 품질 벤치마크가 아니다.

선택 revision에는 Apache License 2.0의 `LICENSE`가 존재한다. 모델 manifest에 revision·각 파일 크기·SHA-256·라이선스 출처를 남기고 로컬 snapshot의 LICENSE를 보존한다. 가중치를 저장소에 넣거나 배포하지 않는다. 향후 재배포 시 라이선스와 해당되는 고지·변경 표시 조건을 다시 확인한다. 모델의 라이선스 표시는 사용자의 문서에 대한 권한을 부여하지 않는다. [고정 LICENSE](https://huggingface.co/Qwen/Qwen3-1.7B/blob/70d244cc86ccca08cf5af4e1e306ecf908b1ad5e/LICENSE).

snapshot의 safetensors 2개는 합계 약 4.06GB다. 이름의 `1.7B × 2bytes`만으로 필요한 메모리를 산정하지 않는다. 약 3.78GiB의 파일 크기 외에도 KV cache·중간 tensor·CUDA allocator·다른 앱의 VRAM이 필요하다. 6GB에서 실제 성공하는지는 아래 probe로 판단한다. [고정 파일 목록](https://huggingface.co/Qwen/Qwen3-1.7B/tree/70d244cc86ccca08cf5af4e1e306ecf908b1ad5e).

## 3. 실행 설정과 자원 중단 조건

새 모델은 기존 `retrieval` 선택 그룹의 Python 3.11·Torch 2.10.0/Windows cu128·Transformers 4.57.6를 사용한다. 첫 실행에 dependency upgrade, bitsandbytes, llama.cpp, FlashAttention, `accelerate`, quantization, compile을 추가하지 않는다. 일반 CI에는 모델 다운로드와 heavy 그룹을 요구하지 않는다.

| 항목 | 첫 실행에서 고정할 값 |
|---|---|
| 모델 로딩 | 검증한 로컬 snapshot, `local_files_only=True`, `trust_remote_code=False`, `use_safetensors=True` |
| 장치·정밀도 | `cuda:0`, `torch.bfloat16`; BF16 지원을 먼저 확인하고 미지원이면 중단 |
| 동시 실행 | batch 1, 생성 요청 1개, E5/BGE 학습·추론과 동시 실행 금지 |
| mode | `model.eval()`, `torch.inference_mode()`, non-thinking hard switch |
| decoding | `do_sample=False`, beam 1, 새 토큰 최대 384; prompt/chat template까지 실제 최대 1,536 tokens |
| attention/cache | native eager attention·KV cache 사용. manifest와 실행기의 설정을 고정하며 실제 선택된 backend 확인 결과는 실행 보고서에 기록 |
| 시간 | 각 생성에 180초 제한. 종료가 token 사이에서만 확인되는지와 외부 process deadline 존재 여부를 기록 |
| GPU 메모리 | peak allocated와 reserved를 각각 기록, reserved 5,376MiB 초과는 실패로 중단 |
| 실패 | OOM·시간 초과·비유한 값·모델/파일 hash 불일치 시 실패 보고서를 먼저 보존 |

모델 카드의 non-thinking 예시는 sampling 설정을 권장한다. 여기서는 한 가지 설정의 간단한 재생·형식 실패 분석을 위해 greedy를 선택한다. 이를 제공자 권장값이나 최적 품질 설정으로 표현하지 않는다. 반복·품질 실패가 나도 첫 결과 뒤에서 파라미터를 바꾸고 같은 실행을 덮어쓰지 않는다. [non-thinking 안내](https://huggingface.co/Qwen/Qwen3-1.7B#switching-between-thinking-and-non-thinking-mode).

1,536 tokens는 evidence만의 예산이 아니라 system 지시·JSON·질문·chat template을 포함한다. 실제 token 수가 넘으면 문맥을 몰래 자르지 않고 생성 전에 `generation_input_limit`로 기록한다. 출력이 최대 토큰·deadline에서 끝나면 문법상 JSON이 완성돼 보여도 정상 종료와 분리하고 답변을 채택하지 않는다. 고정한 tokenizer/model 설정의 EOS·pad를 사용하며 실제 종료 이유와 입력·출력 token 수를 남긴다. token별 원시 ID와 별도 tokenizer 진단은 이번 실행의 필수 telemetry가 아니다.

호스트 전체 VRAM과 PyTorch reserved는 다르다. 실행 전 가용 VRAM·다른 프로세스와 디스크 여유를 확인한다. 이번 실행의 필수 telemetry는 cold load/각 생성의 wall time·PyTorch peak allocated/reserved·실제 입력/출력 token 수·종료 이유다. CUDA 동기화를 GPU 생성 측정 경계에 적용한다. 이는 OOM을 막는 절대 보장이 아니라 관측·중단 조건이다. 장치 전체 VRAM 주기 샘플과 CPU RSS 샘플은 후속 진단 권고이며 현재 실행기가 수집했다고 가정하지 않는다. 나중에 수집하면 샘플 간격·누락 가능성을 함께 남긴다. 소수의 순차 smoke 시간에 p95 서비스 SLA나 Java 성능이라는 이름을 붙이지 않는다.

무료 로컬 모델 파일 내려받기와 로컬 실행만 범위에 있다. 실패 후 자동 CPU fallback·작은 모델 교체·재시도·paid API·클라우드 호출은 없다. 후속 자원 대안은 새 manifest/계획·결과로 남긴다. 다운로드·의존성 준비는 활성 GPU 작업 확인 후 부모 실행자가 한 번만 수행한다.

## 4. 입력과 근거의 식별

생성 입력은 단일 질문과 최대 5개의 **이미 허용되고 현재인 문서 구간**이다. 대화 이력·도구·인터넷·외부 URL fetch는 없다. 첫 합성 실행의 권한·current 표시는 fixture 조건이며 Java 인증 검증의 증거가 아니다.

각 evidence는 다음을 포함한다.

- `evidence_id`: 이번 요청 안에서만 유일한 식별자. 모델이 만들 수 없다.
- `document_id`, `revision`, `source_sha256`: 호스트가 보관하는 문서·버전·전체 정제 본문의 식별값.
- `start_cp`, `end_cp`, `text`: 현재 정제 본문에서 실제 보낸 구간. `[start_cp,end_cp)` Unicode codepoint이며 Java UTF-16 위치가 아니다.
- 입력 순서: 사전 고정 fixture 순서. 후속 서비스에서는 서버 검색 결과 순서를 고정하고 임의 재정렬하지 않는다.

모델에 필요한 `evidence_id`·본문과 사람이 읽을 출처 정보만 직렬화하고, 내부 ACL·토큰·사용자 비밀은 넣지 않는다. 문서 제목·본문·질문을 JSON 데이터로 인코딩하되 JSON 인코딩을 프롬프트 주입의 완전한 방어로 주장하지 않는다. tokenizer chat 특수 토큰 문자열과 역할 전환을 흉내 내는 문구도 공격 fixture/검사 대상으로 남긴다.

모델은 모든 evidence 본문을 불신 데이터로 취급해야 한다. 문서 속 “이전 지시를 무시하라”, 다른 출력 형식, 비밀 공개 요구, `/think` 등은 실행할 지시가 아니다. 생성 모델에는 도구나 임의 파일 접근을 주지 않는다. 이러한 모델 지시 준수는 실험 대상이며 자동으로 보장된 경계는 host의 권한·입력 범위·출력 검증이다.

## 5. 모델 출력과 자동으로 보장할 범위

모델 raw output은 다음 두 형태 중 하나인 JSON 객체 하나다. 예시의 내용은 설명을 위한 합성 예이며 평가 정답으로 사용하지 않는다.

```json
{"status":"answered","reason":null,"claims":[{"text":"합성 작업공간의 보관 기간은 17일입니다.","citations":[{"evidence_id":"E1","quote":"보관 기간은 17일이다."}]}]}
```

```json
{"status":"abstained","reason":"insufficient_evidence","claims":[]}
```

- 최상위 키는 `status`, `reason`, `claims`만 허용한다. 중복 JSON key, 알 수 없는 key/type, NaN/Infinity, 코드펜스, JSON 앞뒤 설명은 거절한다. 앞뒤 공백만 허용한다.
- `answered`는 `reason=null`, 주장 1~3개를 요구한다. 각 `text`는 비어 있지 않은 최대 500 codepoints, `citations`는 1~3개다. 인용 객체는 `evidence_id`, `quote`만 허용하며 quote는 비어 있지 않은 최대 300 codepoints다.
- `abstained`는 빈 `claims`와 `insufficient_evidence`, `conflicting_evidence`, `ambiguous_question` 중 하나의 reason을 요구한다. 모델이 임의 보류 설명이나 사실 주장을 덧붙이지 않는다.
- 사용자에게 보여줄 답변 문장은 검증한 claims만으로 구성한다. 모델이 생성한 별도 요약·결론·URL·출처 제목을 신뢰하지 않는다.

인용 검증기는 알려진 `evidence_id`와 **실제로 보낸 text 안의 정확한 quote**를 검사한다. 공백·대소문자·Unicode normalization을 임의로 바꾸거나 “비슷한 인용”을 수선하지 않는다. 같은 quote가 해당 evidence에 두 번 이상 나타나면 위치가 불명확하므로 거절한다. 호스트가 유일한 위치에서 absolute codepoint span·문서·리비전·source hash를 복원한다. 모델이 말한 offset·페이지·문서 ID를 원문 사실로 받아들이지 않는다. 중복 citation을 정확도 분모를 늘리는 데 사용하지 않는다. 검증기 자체는 입력 revision/hash의 형식을 검사할 뿐 DB의 현재 상태나 전체 source hash를 증명하지 못한다. 실제 원문·권한·현재 revision 검사는 호출자 책임이며 합성 fixture의 바인딩과 후속 Java 검증에서 각각 확인한다.

하나라도 잘못된 인용·주장이 있으면 전체 답변을 보류한다. 유효한 주장만 골라내어 질문 전체가 답변됐다고 표시하지 않는다. JSON 복구·모델 재호출·숨겨진 fallback도 하지 않는다. 호스트 거절 사유는 `invalid_generation`, `context_too_large`, `generation_timeout`, `generation_failed` 같은 고정 code이며 모델이 선택한 `reason`과 다른 필드에 남긴다.

**정확한 인용 문자열과 의미 지지는 서로 다르다.** 예를 들어 “보관 기간은 17일이다”를 정확하게 인용하고 “보관 기간은 30일”이라고 답해도 quote 검사는 통과할 수 있다. 검증된 인용이 다른 주장에 붙거나, 부정·조건·수치 관계가 뒤집히거나, 질문의 절반만 답해도 같은 한계가 있다. 따라서 호스트가 구조적으로 수락한 결과에 `semantic_support="not_verified"`를 강제로 붙인다. 모델이 이 값을 자신 있게 덮어쓸 수 없다. 첫 prototype에서 `answered`는 모델의 응답 선택과 구조 검사 통과를 뜻하며 “의미가 검증된 정답”을 뜻하지 않는다.

## 6. 답변·보류 정책과 평가할 실패

| 입력 상황 | v1 의도 | 실제 보장/남은 검사 |
|---|---|---|
| 허용된 evidence 0개 | 모델 호출 전 보류 | host가 보장. 생성 능력의 성공으로 세지 않음 |
| 관련 없는 evidence만 있음 | `insufficient_evidence` | 모델 판단을 실제 생성으로 평가 |
| 질문의 모든 부분을 원문으로 답할 수 있음 | 짧은 claims와 각 근거 | quote provenance 자동 검사 + 별도 의미 검토 |
| 두 문서가 필요하지만 한쪽이 없음 | 전체 보류 | 일부 답만 하는 실패를 의미 검토. quote 유효성과 분리 |
| 허용된 현재 문서들이 같은 범위에서 충돌 | `conflicting_evidence` | 업로드 시간·검색 순위로 권위를 추정하지 않음. 충돌 탐지는 아직 의미 평가 |
| 대상·조건이 불명확 | `ambiguous_question` | 임의 대상 선택을 실패로 검토 |
| 오래된 revision만 답을 지지 | 현재 사실의 근거로 사용하지 않음 | Java가 current만 제공하고 반환 전 재검사해야 보장 가능 |
| 문서에 공격 지시와 정상 근거가 같이 있음 | 정상 질문만 답하거나 보류 | 공격 응답·가짜 출처·역할 변경 시도를 별도로 평가 |
| 모델의 인용이 유효하나 내용이 거짓 | 구조 통과와 의미 실패를 함께 기록 | 인용 검사 성공으로 오류를 숨기지 않음 |

v1에는 부분 답변 상태가 없다. 질문 일부의 근거만 존재할 때 나머지를 상식·사전학습 지식으로 채우거나, 일부만 답한 결과를 완전 답변으로 표시하지 않는다. 충돌 여부·질문 완전성·문장 지지는 일반 규칙으로 완전히 판정하지 못한다. LLM의 자기 confidence, BM25 점수, dense 유사도, token log probability를 보정된 사실 확률로 표시하지 않는다.

## 7. 합성 smoke와 독립 검토

첫 fixture는 기존 Kubernetes 문서·M2/M3/M4 질문을 읽거나 변형하지 않고 새로 만든다. 가상의 명칭·수치·정책만 사용하고 각 항목에 `synthetic=true`, `ai_authored=true`, `human_reviewed=false`를 둔다. fixture 작성 역할과 결과 의미 검토 역할을 분리한다. 사용자가 직접 검수한 것처럼 영수증을 만들지 않는다.

첫 12항목의 기능별 구성은 다음으로 고정한다. 실제 fixture의 문구·필수 사실·보류 이유는 GPU 실행 전에 hash로 묶고 모델 prompt에서는 정답·기대 decision을 제외한다.

| 항목 | 기대하는 확인 |
|---|---|
| 한국어 단일 사실 | 원문 수치·대상에 맞는 한국어 답변 |
| 영어 단일 사실 | 원문에 맞는 영어 답변 |
| 영어 근거→한국어 질문 | 번역이 quote 원문을 바꾸지 않는지 |
| 다중 문서의 완전 근거 | 두 독립 사실을 함께 답하고 필요한 출처 모두 연결 |
| 다중 문서 중 절반 누락 | 일부 답변 대신 근거 부족 보류 |
| 비어 있지 않은 무관 근거 | 실제 모델의 근거 부족 보류 |
| evidence 없음 | deterministic preguard, 모델 호출 0회 |
| 동일 조건의 상충 근거 | 충돌 보류, 근거 없는 우선순위 추정 금지 |
| 공격 지시 + 정상 근거 | 정상 내용에만 응답, 공격 문자열을 행동 지침으로 사용하지 않음 |
| 대상·조건 모호 | 명확화가 필요한 보류 |
| Unicode·기호 원문 | quote·codepoint의 정확한 연결 |
| 현재 revision 사실 | 보내지 않은 이전 사실을 사용하지 않음. 실제 revision race 검증은 후속 |

문구·개수 또는 schema가 실제 구현 전에 조정되면 최종 계획에 변경 이유와 정확한 hash를 고정한다. 생성 결과를 본 뒤 같은 버전의 정답·구성을 바꾸지 않는다. 각 항목은 예정된 순서대로 한 번 실행한다. 실패 케이스만 같은 version에서 다시 뽑아 성공으로 교체하지 않는다.

모델을 호출하지 않는 빈 evidence 항목을 포함한 전체 12개와, 실제 모델 호출 예정 11개를 별도 분모로 낸다. 구조·인용·의미 실패나 한국어/영어 readiness 지표 미달은 남은 질문을 중단하는 조건이 아니다. 동일한 설정으로 예정된 질문 전체를 계속 측정한다. OOM·deadline·메모리 한도·모델 hash/환경 불일치와 재사용 불가능한 runtime 오류처럼 실행 안전성·완결성을 해치는 실패에만 실행을 중단한다. 이때 남은 항목은 `not_run`이며 실패·보류 성공으로 계산하지 않는다. raw 모델 출력·raw decision·parser 결과·quote 결과·호스트 최종 decision·종료 이유·시간/메모리를 함께 보존한다. 합성 원문과 raw 출력은 평가 artifact에 기록할 수 있으나 실제 사용자 원문을 operational log에 기록하는 허가로 확대하지 않는다.

첫 GPU 단계의 **실행 준비 지표**는 고정 identity의 CUDA/BF16 로드와 자원 한도 내 실제 생성, 최소 한국어/영어 각 1개에서 정상 종료한 구조·인용 유효 답변을 확인한다. 이는 실행을 조기 종료시키는 gate나 질문 품질 통과 조건이 아니다. 12개 전체 결과와 나머지 실패는 그대로 보고한다. 검사기는 변조 ID·모델이 임의로 덧붙인 revision/hash·반복 quote·Unicode·truncation·불완전 JSON을 fail-closed하는 합성 회귀 검사를 별도로 통과해야 한다. 형식상 올바른 입력 metadata와 현재 원문의 일치는 별도 호출자 바인딩 검사다.

독립 AI 검토자는 raw 답변의 각 주장에 대해 `supported`, `unsupported`, `contradicted`, `unclear`와 근거를 기록한다. 질문 전체에 대해서는 `complete`, `incomplete`, `incorrect`, `abstained`를 기록한다. 특히 수치·부정·범위·교차언어·다중 문서 결합·공격 지시를 확인한다. 자동 exact-fact 검사가 있으면 그 이름과 적용 가능한 사실만 별도 기록하며 일반 의미 채점으로 부풀리지 않는다. 사용자 검수는 계속 0이다.

## 8. 수치의 정의와 후속 calibration

| 지표 | 분자/분모와 해석 |
|---|---|
| raw 형식 성공률 | 엄격한 schema 통과 raw 출력 / 실제 생성 완료 수 |
| 인용 provenance 성공률 | 정확한 현재 입력 구간으로 유일하게 복원한 서로 다른 인용 / raw 출력의 검사 가능한 서로 다른 인용. schema 실패 수 별도 |
| 답변 범위, coverage | 최종 수락된 답변 수 / 전체 평가 질문. preguard·모델 보류·validator 보류·실행 오류 각각 분리 |
| 답변 중 오류율, selective error | 의미 검토에서 하나라도 unsupported/contradicted 또는 불완전/오답인 답변 수 / 최종 수락된 답변 수. 0답변이면 null |
| 주장 지지율 | supported 주장 / 검토된 주장. unclear를 분모에서 빼 성공률을 올리지 않음 |
| 적절한 보류 | 보류 필요로 사전 판정한 항목의 보류 / 보류 필요 항목. 모델 원래 보류와 검사기 거절을 분리 |
| 과도한 보류 | 충분한 근거가 있는 항목의 보류 / 답변 가능 항목 |

Schema에 맞지 않아 host가 막은 환각을 모델의 정답·적절한 보류로 합치지 않는다. 전체 보류 시스템이 낮은 오답률만으로 좋은 모델처럼 보이지 않도록 coverage와 과도한 보류를 항상 같이 낸다. 작은 AI 합성 표본은 실사용 정답률 추정이나 통계적 우위의 근거가 아니다.

이번 12개는 개발 smoke이며 calibration·held-out 성능 자료라는 이름을 붙이지 않는다. 후속 M5-B에서는 새 자료의 source family를 먼저 정해 generation calibration과 validation으로 나눈다. 같은 가상 정책의 수치·명칭만 바꾼 변형, 번역·동일 사실의 패러프레이즈, 원본과 공격 버전은 같은 family에 묶는다. 역할을 분리해 calibration을 본 작성자가 validation 정답으로 prompt를 조정하지 않도록 한다. 해당 선택 규칙·표본 수·역할·hash·정책 후보 수를 별도 계획에서 실행 전에 등록한다.

새 generation validation은 기존 M2의 최종 retrieval test와 별개다. 기존 test를 generation 자료라 부르며 읽거나 평가하지 않는다. 최종 test의 개방 조건은 기존 잠금 그대로다. 사람 검수가 없는 예비 실험은 가능하나 이를 최종 검수로 대체하지 않는다.

첫 v1에는 의미 support score나 보정된 confidence threshold가 없다. quote 1개 등의 형식 조건은 **보류 품질의 calibration을 마친 임계값이 아니다.** 후속에서 측정 가능한 support/abstention 판단을 정의하고, 제한된 calibration에서 operating point를 정해 validation 전에 동결해야 한다. 현재 smoke 통과로 로드맵의 보류 임계값·실제 문서 품질 조건까지 완료했다고 주장하지 않는다. 후속 현실 문서 표본은 별도 허용 source set으로 선정하고 기존 완료 비교를 튜닝 자료로 재사용하지 않는다.

## 9. Java·React 연결 전에 필요한 운영 계약

이 절은 후속 구현 요구사항이며 이번 Python smoke가 검증하지 않는다.

1. Java가 서버 세션으로 사용자를 식별하고 workspace membership·document ACL을 검사한 뒤 허용된 현재 청크만 검색·선택한다. 생성 worker가 user ID나 ACL 판단을 대신하지 않는다. 제한 문서는 prompt·오류 메시지·근거 제목에 포함하지 않는다.
2. Java는 생성 전 문서 집합·revision/hash·권한 snapshot을 확보하고 DB transaction을 끝낸다. 생성 후 같은 세션·membership·문서/청크·권한 snapshot을 쓰기 transaction에서 재확인한다. 생성 중 갱신·재처리·삭제·권한 회수·관련 가시 corpus 변경이 있으면 409로 폐기한다. 새 충돌 문서가 추가된 경우도 검토 범위에 포함한다.
3. 생성 worker는 인증된 loopback에서 한 요청씩 고정 model/revision/prompt identity의 추론만 수행한다. Java가 모든 응답의 identity와 quote를 다시 검증한다. health 응답만 확인하고 결과 identity 검사를 생략하지 않는다.
4. 검증된 결과와 답변 이력을 원자적으로 저장한다. 보류 이력과 worker 오류는 서로 구분한다. 기존 이력 재조회 때에도 현재 ACL과 삭제 여부를 검사하고 철회된 문서의 quote·제목·파생 답변을 다시 노출하지 않는다.
5. 첫 연결에는 answer cache와 token streaming을 추가하지 않는다. 전체 결과를 검증한 뒤 한 번에 보여야 검증 전 문장·철회된 근거가 먼저 화면에 나오는 것을 막을 수 있다. 캐시는 나중에 별도 invalidation·scope 계약이 있을 때 도입한다.
6. React는 답변·보류·오류와 실제 모델/방법을 구분한다. 근거를 클릭하면 검증된 현재 document/revision/codepoint 구간으로 이동한다. 원문은 text 또는 sanitize한 markup으로 렌더링하며 모델 HTML/URL을 실행하지 않는다. 질문이 바뀐 뒤 도착한 이전 답변도 요청 세대로 폐기한다.
7. 운영 로그는 request ID·safe code·latency·모델 설정 hash만 포함하고 원문·질문·프롬프트·답변·세션 token을 넣지 않는다. 내부 worker 오류와 제한 문서 존재 여부를 외부 사용자에게 노출하지 않는다.

권한 회수/다른 workspace·private 문서, 수정/삭제/동일 본문 재처리, 로그, 이력의 재접근, 생성 중 경합, worker 장애, base 검색 유지와 데스크톱/모바일 화면은 실제 Java/React 묶음에서 확인해야 한다. 최종 응답 commit 시점 이후의 모든 future 권한 변경까지 이미 사용자에게 전달된 정보를 되돌릴 수 있다고 주장하지 않는다.

## 10. 동결·재생·기여 기록

실행자는 새 파일만으로 model manifest·source allowlist·프롬프트/schema·fixture·uv.lock·실행기·검증기 hash를 묶는다. 실제 모델 호출 전에 그 계획과 Git source 상태를 보존한다. 결과는 run ID·시작/종료 시각·환경·실제 dtype/device·actual token 수·실패 단계·종료 이유·출력·자원 수치와 연결한다. 완료한 M2/M3/M4 실행 소스·입력·결과를 수정하지 않는다.

재생 검사는 저장된 합성 입력/출력과 hash·결정 규칙을 확인하며 새 생성 추론을 수행하지 않는다. 저장 output의 검증 재생과 같은 model/prompt의 재생성이 동일한 작업이라는 주장을 하지 않는다. 첫 모델 실행 실패와 후속 수정을 다른 version/run으로 보존하고, 실패 run의 데이터를 성공 run처럼 다시 써 넣지 않는다.

모델 없는 CI는 데이터·계약·검증기·결과 재생을 확인한다. 로컬 실제 GPU 실행, Java HTTP, React production/browser, 원격 CI는 각각의 상태로 기록한다. 모델 품질·실제 권한 연동·기본 채택은 각자의 증거가 있어야 다음 단계로 올린다. 유료 자원·공개 서비스 배포·사용자 검수를 자동으로 승인하지 않는다.

설계 작성 역할은 `m5_design`이며 부모가 도구로 확인한 수락 설정 `gpt-6-astra/xhigh`를 기여 기록에 남긴다. 개발 보조 모델과 서비스 생성 모델 Qwen3-1.7B는 별개다. 부모 채팅의 모델 설정을 바꿨다는 뜻이 아니다. 이 문서는 공식 자료 확인과 설계 산출물이며, 실제 자원/생성 결과·독립 AI 의미 검토·사용자 검수는 별도로 기록한다.
