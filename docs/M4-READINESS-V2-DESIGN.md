# M4 · 실제 실패에 대한 준비 계약 v2

기준일: 2026-10-12. **v1의 실패를 보존하고, 부족한 음성 네 후보의 검토와 실제 잘린 모델 입력의 의미 검토만 추가한다.** 질문·양성·기존 음성 라벨·학습 설정을 바꾸는 계획이 아니다. [새 실행 계약](../data/training/m4-readiness-plan-v2.json)의 SHA-256은 `aa6464441d7c02b14977ab79656b3c48d57a1a4a0af5a29f9186a520d7a5405c`다. [v1 설계](M4-READINESS-DESIGN.md)와 모든 v1 산출물은 그대로 남긴다.

## 1. 변경을 요구한 실제 증거

[v1 tokenizer 영수증](../data/training/m4-tokenizer-receipt-v1.json)은 고정 E5 tokenizer를 CPU에서 실제 실행한 결과다. 모델 가중치를 올리거나 GPU를 사용하지 않았다. [v1 준비 manifest](../data/training/m4-training-manifest-v1.json)의 SHA-256은 `3b303325b0785f79e4410ef335822ecef19997966f32cd333ea5feb934c798b0`이다.

| v1 검사 | 실제 결과 |
|---|---|
| 독립 양성 의미 검토 | 80개 accept, 사용자 검수 0개 |
| 질문·선택된 양성 근거의 token 보존 | 80개 모두 통과 |
| 음성 후보 검토 | negative 244개, ambiguous 8개, relevant 4개 |
| 질문당 음성 2개 | `m4-fit-048`이 0개여서 실패 |
| 고정 음성의 전체 token 보존 | 12개 질문-청크 쌍 실패, 서로 다른 청크는 8개 |
| 상태 | `data_ready=false`, probe 미실행, 학습 미실행 |

잘림이 확인된 질문은 `005`, `015`, `021`, `025`, `026`, `027`, `030`, `049`, `050`, `051`, `053`, `055`다. 모두 `m4-fit-` 접두사의 기존 질문이다. 최대 길이는 여전히 512이며 긴 후보를 짧은 후보로 교체하지 않는다.

v2는 v1 manifest가 가리키는 입력과 manifest 자체의 **34개 실제 파일 hash**, 실행에 사용한 **8개 소스의 LF 정규화 hash**를 고정한다. 새 자료를 만들기 전 모두 현재 파일과 일치함을 확인했다. 기존 v1의 `data_ready=false`가 재현돼야 하며 이를 소급 통과로 바꾸지 않는다.

## 2. 부족한 한 질문에만 후보 네 개 추가

`m4-fit-048`의 원래 BM25 후보 목록에서 fit·unreviewed·격리 사유 없음 조건을 유지한다. 기존 rank·chunk ID 순으로 적격 후보를 정렬하고 처음 4개 다음의 4개만 고정한다. 이는 새 검색이나 모델 점수에 따른 선택이 아니다. 새 본문을 읽기 전에 메타데이터로 목록을 고정했다.

| 원래 BM25 rank | 추가 검토 청크 |
|---|---|
| 6 | `k8s-en-714196198a9cf46c:7` |
| 7 | `k8s-en-e857760d31af8e6d:0` |
| 8 | `k8s-en-702c8273896bed82:1` |
| 9 | `k8s-en-54c2092d43a54b79:9` |

`m4_supp_author`가 질문·참고 답안·전체 양성 문맥과 네 후보의 전체 본문을 모두 독립 검토한다. `negative`·`relevant`·`ambiguous`·`unknown`의 의미와 원문/질문/pack 바인딩은 v1과 같다. 검토 영수증은 새 파일에 쓰며 기존 네 후보의 라벨을 고치지 않는다.

기존 4개와 새 4개의 전체 문맥 검토 결과를 합쳐 **원래 순위에서 처음 두 negative**를 선택한다. 토큰 길이를 보기 전에 선택을 확정한다. 두 개가 여전히 부족하면 전체 준비 상태가 false이며 이번 버전에서 아홉 번째 적격 후보 이후로 확대하지 않는다. 나머지 63개 질문의 음성 두 개는 v1 manifest의 순서와 참조까지 그대로 유지한다.

## 3. 실제 모델 입력을 별도 검토하기

잘리지 않은 고정 음성은 기존 전체 문맥의 negative 영수증을 그대로 사용한다. 잘린 고정 음성은 **전체 문맥 negative와 실제 잘린 입력 negative를 모두** 충족해야 한다. `m4_gate_design`이 질문별로 검토하며 같은 청크를 공유하는 여러 질문도 각자 영수증을 남긴다. 추가한 048의 선택된 음성이 잘리면 같은 규칙이 자동으로 적용된다.

독립성은 원래 fit 질문 작성자 `train_author`와의 분리를 뜻한다. `m4_gate_design`은 일부 후보의 이전 전체 문맥 검토도 수행했다. 이번 검토를 제3의 검토자나 사용자 검수로 표현하지 않는다. 두 검토 역할의 설정은 부모가 확인한 `gpt-6-astra / xhigh`이며 개발 보조 모델의 기록이다.

로컬 검토 pack에는 질문·양성 전체 문맥·후보 전체 본문·기존 negative 영수증과 다음 실제 tokenizer 증거가 함께 들어간다.

- 잘림 전후 token ID와 offset, special-token mask, 잘린 입력의 attention mask.
- 실제 retained token ID를 `skip_special_tokens=True`, `clean_up_tokenization_spaces=False`로 decode한 표시.
- retained offset의 끝을 기준으로 원문에서 직접 자른 문자열과 정확한 구간. 이는 원문 일부이며 decode 결과와 별도로 표시한다.
- 모델 입력의 token ID/attention-mask hash와 위 표시·offset을 포함한 전체 view hash.

Decode는 tokenizer 정규화를 거친 해석이며 원문을 byte 단위로 복원한 문장이 아니다. Offset에 대응하는 원문 구간도 그 안의 모든 문자가 실제 token으로 표현됐다는 증거로 부르지 않는다. 검토자는 잘린 끝의 문장·조건·부정·예외·주체를 확인하고, 버려진 본문의 조건을 실제 입력에 존재하는 것처럼 읽지 않는다.

`negative`는 실제 남은 입력이 질문의 구체적 사실을 지지하지 않는 이유와 잘림이 그 판단에 미친 영향을 설명할 때만 준다. 대체 답이 될 가능성, 중요한 조건·부정의 손실, 해석을 바꾸는 모순이 남으면 해당하는 `relevant`·`ambiguous`·`unknown`을 기록하고 준비 게이트를 막는다. 실패 때문에 뒤 순위 후보를 선택하거나 source를 수동으로 자르지 않는다.

실제 입력 영수증은 질문·compiled 질문·모든 양성 문맥·후보 행·본문·원래 전체 문맥 검토·view·retained token ID·모델 입력·pack·최종 token 영수증·새 계획 hash를 함께 묶는다. 원문과 raw token ID·decode·offset 배열은 로컬에만 두고, 공개 결과에는 참조·수량·hash·검토 이유를 보존한다.

## 4. 해시 연결과 검증의 실제 범위

산출물 순서는 **계획 commit → 048 pack/검토 → 음성 선택 확정 → 실제 CPU token payload → 로컬 실제 입력 pack → 공개 token 영수증 → 실제 입력 의미 검토 → 준비 manifest**다. Token payload에는 미래의 pack hash를 넣지 않는다. 로컬 실제 입력 pack이 payload hash를 참조하고, 최종 공개 token 영수증이 pack hash를 참조한다. 의미 검토는 pack과 최종 token 영수증을 모두 참조한다. 이 순서로 순환 hash를 피한다.

| 검증 경로 | 확인할 수 있는 범위 |
|---|---|
| 로컬 실제 tokenizer 실행 및 `tokenize --verify` | 고정 tokenizer로 ID·offset·decode·원문 표시·로컬 pack을 다시 계산하고 저장 hash/바이트와 비교 |
| 모델 없는 새 CI의 구조 replay | 원문 참조·질문·양성·고정 후보 선택을 다시 만들고, 저장된 공개 token 증거의 바인딩·검토 대상 일치·최종 manifest 바이트를 대조 |
| 이후 실제 probe/학습 | 로컬 실제 입력 pack의 바이트/hash가 있어야 하며, forward 전에 재생성한 unpadded token ID·attention mask가 동결 모델 입력 hash와 일치해야 함 |

**모델 없는 CI는 실제 raw token view를 새로 만들거나 읽었다고 주장하지 않는다.** 저장된 hash끼리 같다는 사실만으로 보이지 않는 원시 token 내용을 증명할 수는 없다. 새 CI는 저장된 실행 증거와 영수증 연결의 재현이며, 별도의 실제 tokenizer 검증과 구분한다. 이 때문에 기존 잠금 파일에 tokenizer 의존성을 추가하지 않는다. 후속 probe/학습에서 로컬 pack이 없으면 고정 tokenizer로 다시 만들고 동결 결과와 대조하기 전까지 중단한다.

## 5. 통과해도 유지되는 제한

질문은 fit 64개·calibration 16개로 유지한다. 80개 양성 의미·token 게이트와 원래 수량·언어·주제·중복·계열 조건을 모두 유지한다. 음성은 질문당 두 개이고 in-batch negatives는 계속 없다. v1의 `selected_negative_inputs_untruncated`가 참이 됐다고 기록하지 않는다. v2는 **그대로 보존된 입력 또는 별도 검토된 실제 잘린 입력**이라는 새 게이트로 판단하고, 잘린 입력 수는 통과 후에도 공개한다.

하나라도 음성 부족·실제 입력 비음성/모호성·바인딩 실패가 있으면 전체 `data_ready=false`다. 질문을 삭제하거나 더 작은 분모로 진행하지 않는다. 원래 E5 revision·max length·접두사·pooling·학습 seed·epoch·step·optimizer·precision·자원 상한과 평가 정책을 바꾸지 않는다. Dev/test 질문을 열거나 검색 점수를 얻어 후보를 고르지 않는다.

자료 준비가 통과한 뒤에만 기존 계약의 자원 probe를 시작할 수 있으며, probe와 본 학습 상태는 별도다. 이 계획의 작성이나 구조 replay는 학습·검색 향상·Java 운영 채택 결과가 아니다. 사용자 검수는 pending이며 유료 자원과 공개 서비스 배포는 수행하지 않는다.
