# M4 · 보충 자료와 학습 준비 게이트

기준일: 2026-10-12. **이 계약은 기존 fit 64개·calibration 14개를 보존하면서 부족한 보정 질문 2개, 명시적 음성 검토, 실제 E5 tokenizer 검사를 연결한다.** 계획을 저장한 시점의 데이터 준비·자원 probe·학습 결과가 아니다. 질문과 참고 답안은 AI 작성이며 사용자 검수는 계속 0개다.

실행 계약은 [m4-readiness-plan-v1.json](../data/training/m4-readiness-plan-v1.json)이다. SHA-256은 `8ef8dbe2a5e16f167c55e060ea5aa9207f00d91de6d03fa70712a2f910483b66`이다. 기존 [M4-DESIGN](M4-DESIGN.md), [m4-plan-v1.json](../data/training/m4-plan-v1.json), [selection-v1.json](../data/training/generation/selection-v1.json)과 pilot 산출물을 덮어쓰지 않는다. 기존 학습 설정·train 내부 분할·M2 청크·M3 모델 revision은 그대로 상속한다.

## 1. 입력을 먼저 고정하기

새 계획은 원래 계획·inventory-v3·두 선택 목록·작성 지침·원래 두 초안·생성 영수증·pilot 네 산출물·원래 세 의미 검토 파일·코퍼스 manifest·모델 manifest·`uv.lock`의 실제 파일 SHA-256을 포함한다. 기존 compiler·review validator·corpus loader·ingest·retrieval 소스는 CRLF만 LF로 정규화한 SHA-256으로 고정한다. 질문·후보 행은 기존 검토기의 compact sorted JSON hash, pack과 양성 문맥은 기존 `fingerprint`를 사용한다. 파일 바이트 해시와 JSON 행 해시를 혼용하지 않는다.

새 초안·검토 영수증·합성 compiler 산출물·두 음성 pack·tokenizer 영수증·새 실행 코드의 해시는 실행 보고서에 추가한다. 아직 없는 산출물에 예상 해시를 넣거나 이 계획의 해시를 스스로 포함해 순환 바인딩을 만들지 않는다. 계획과 선택 목록을 고정한 뒤 본문을 작성·검토한다.

기존 corpus loader의 전체 코퍼스 무결성 검사는 유지하고 그 직후 원래 train만 남긴다. 이 작업의 author pack·음성 pack·tokenizer 검사에는 dev/test/smoke 질문·정답 파일을 읽는 경로가 없다. 기존 일반 CI의 동결 평가 자료 replay와 새로운 질문 열람을 구분한다.

## 2. 보정 질문 2개를 위한 새 선택 버전

[selection-v2.json](../data/training/generation/selection-v2.json)은 기존 선택의 모든 ID와 순서를 보존하고 calibration 한 문서만 뒤에 추가한다. SHA-256은 `e7446e20b1fbbf2f684dd44c28daa651491032474e55818cc7c1a1e389e8a828`이다. 선택은 inventory 메타데이터만 사용한다.

1. 원래 calibration에 속하고 기존 calibration 선택 계열에 속하지 않는 문서를 남긴다. 길이는 2,000~20,000자, 주제는 concepts·tasks·reference다.
2. 계열 안에서는 적격 문서 중 영어를 먼저, 이후 문서 ID 오름차순으로 대표 하나를 고른다.
3. 대표 주제 concepts → tasks → reference, `sha256("doctrail-m4-calibration-supplement-v1:" + family_id)`, 계열 ID 순으로 정렬한다.
4. 첫 계열 하나만 선택한다. 선택 목록에는 모든 적격 계열의 순위와 해시를 남긴다. 이 주제 순서는 개념 설명 자료를 보충하기 위한 선택이며 검색 향상 예측이 아니다.

결과는 `k8s-family-85e09e3d503ba9b4`의 `k8s-ko-05261080c1ab2828`이다. 메타데이터상 concepts·한국어·9,393자이며 새 author pack에는 이 문서만 들어간다. 원래 pack이나 14개 보정 질문을 재작성하지 않는다.

작성자는 `m4_supp_author`, 별도 의미 검토자는 `m4_gate_design`이다. 부모 실행자가 두 역할의 `gpt-6-astra / xhigh` 요청을 도구가 수락했음을 확인했다. 이것은 개발 보조 모델 설정이며 서비스 모델이나 부모 채팅 모델의 변경이 아니다. 초안 ID는 `m4-cal-015`, `m4-cal-016`이다. 기존 지침의 단일 사실·실용 질문·정확한 인용·독립 의도 조건을 모두 따른다.

두 질문을 만들 수 없다면 부족한 이유를 남기고 `data_ready=false`로 유지한다. 뒤 계열을 자동으로 열거나 번역·말바꾸기로 수량을 채우지 않는다. 최종 목표는 원래 fit 64개와 보정 16개, 합계 80개다. 보정의 다섯 번째 계열을 추가해도 원래 최소 4계열·계열당 최대 4질문 규칙을 낮추지 않는다.

## 3. 256개 후보를 검토하고 128개 음성만 선택하기

원래 pilot의 fit 질문마다 `status=unreviewed`, 격리 사유 없음인 BM25 후보를 기존 rank, chunk ID 순으로 정렬하고 앞 4개를 고정한다. 64질문 × 4개 = 256개가 **검토 대상 목표**다. 실제 음성 개수가 256개라는 뜻이 아니다. 기존 양성·동계열·겹침·중복 격리 후보를 복구하지 않는다.

`m4-fit-001`~`032`는 `m4_gate_design`, `033`~`064`는 `m4_supp_author`가 검토한다. 두 검토자 모두 원래 fit 질문 작성자 `train_author`와 다른 역할이다. 검토자는 질문, 참고 답안, 정확한 근거, 알려진 모든 양성 청크의 전체 문맥과 후보의 전체 청크를 읽는다. 전체 본문은 로컬 pack에만 보존한다.

| 판정 | 의미와 후속 처리 |
|---|---|
| `negative` | 요청한 구체적 사실을 지지하지 않는 이유를 설명할 수 있음. 학습 음성 선택 후보 |
| `relevant` | 요청한 사실 또는 유효한 대체 답을 지지함. Loss에서 제외하고 발견 사실 보존; 정답 목록에 자동 편입하지 않음 |
| `ambiguous` | 조건·번역·버전 관계·가능한 대체 답을 확정할 수 없음. Loss에서 제외 |
| `unknown` | 검토 증거가 부족하거나 미완료. Loss에서 제외 |

같은 주제라는 사실이나 기존 양성 목록에 없다는 이유는 `negative`의 근거가 아니다. 256개 각각을 정확히 한 번 기록하며, 두 음성을 확보한 뒤에도 뒤 두 후보의 검토를 생략하지 않는다.

영수증은 원래 draft question hash, compiled question hash, 모든 양성 compact reference의 문맥 hash, 원래 후보 행 hash, 후보 본문 hash, 해당 review pack hash와 새 계획 hash를 모두 묶는다. 검토자·판정·구체적 이유·`human_review=pending`도 필수다. 행·본문·역할·pack 변경은 기존 검토 영수증을 재사용할 수 없게 한다. 구조 검증은 의미 판정의 진실을 자동으로 증명하지 않는다.

학습 음성은 `negative`로 판정된 후보 중 원래 순위의 앞 두 개다. 서로 다른 chunk ID를 요구하지만 별도의 서로 다른 문서 수 조건은 추가하지 않는다. 같은 문서의 다른 청크 비율은 진단으로 보고할 수 있다. 두 음성이 부족한 질문이 하나라도 있으면 전체 자료가 미준비 상태다. 검토 범위를 다섯 번째 이후 후보로 늘리려면 새 계획과 pack 버전을 먼저 만든다. 다른 질문의 문서를 in-batch 음성으로 사용하지 않는다.

## 4. 실제 E5 tokenizer로 확인하고 단일 양성 고르기

모델 manifest의 고정 E5 revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`과 로컬 tokenizer 파일 해시를 대조한다. 실제 fast tokenizer를 사용하되 가중치 forward나 GPU는 필요하지 않다. `query: `·`passage: `, special token 포함 `max_length=512`, truncation을 유지한다. 글자 수나 decode한 문자열의 부분 일치만으로 보존을 추정하지 않는다.

- **질문:** 접두사를 붙인 전체 질문의 잘림 전후 token ID가 완전히 같아야 한다. Fit과 calibration 80개 모두 검사한다.
- **양성:** 원래 알려진 양성 청크를 문서 ID·숫자 ordinal·chunk ID 순으로 확인한다. 정확한 문서 quote 구간을 청크 안의 위치와 passage 접두사 길이로 옮기고, 그 구간과 겹치는 잘림 전 모든 비특수 token의 ID·offset이 잘림 뒤에도 남는지 검사한다. 인용이 한 token도 만들지 않거나 인용의 마지막 token이 일부 잘리면 실패다. 이를 통과한 가장 이른 청크 하나만 선택한다. 중첩 양성 개수만큼 질문을 복제하지 않는다.
- **음성:** 의미 검토 순위로 앞 두 개를 먼저 고정한 뒤, 각 접두사 포함 **전체 청크**의 잘림 전후 token ID가 같아야 한다. 잘림이 조건·부정 표현을 없애면 원래 전체 문맥에 대한 판정을 실제 모델 입력에 그대로 적용하기 어렵기 때문이다. 실패는 `negative_truncation`으로 남기며 뒤 후보로 자동 교체하지 않는다.

음성 전체 보존 조건은 보수적인 첫 준비 계약이다. 실제로 막히면 원래 후보와 실패를 보존하고 다음 버전에서 실제 잘린 모델 입력을 별도로 독립 검토하는 방법을 설계할 수 있다. 현재 계약 안에서 조건을 낮추거나 길이·청크·질문·인용을 수정하지 않는다.

Token 영수증에는 실제 tokenizer class와 라이브러리 버전·파일 해시·설정, 질문 길이, 모든 양성 후보의 인용 보존 결과, 선택된 청크 ID·본문 hash, 고정 음성 ID·길이, 제외 행과 이유, 사용한 입력 및 코드 해시가 들어간다. 데이터 제외 사유와 전체 80개 분모를 함께 보존한다. 하나라도 양성/질문 보존에 실패하거나 fit 음성 두 개를 사용할 수 없으면 전체 `data_ready`가 false다. 실패한 질문만 빼고 더 작은 자료를 준비 완료로 보고하지 않는다.

## 5. 데이터·probe·학습 상태를 분리하기

| 상태 | 통과 의미 |
|---|---|
| `data_ready` | 동결 입력·독립 질문·원래 수량/언어/주제/중복 조건·양성 검토·256개 음성 영수증·질문당 두 음성·실제 token 보존·결정적 replay가 모두 통과 |
| `resource_probe_result` | 별도 실행의 `not_run`·`passed`·`failed` 결과. 데이터 준비 결과 자체에 probe 성공을 요구하지 않음 |
| `training_ready` | `data_ready=true`이고 기존 계획의 실제 자원 probe가 통과함 |
| `training_executed` | 제한된 본 학습이 실제 수행됐는지에 대한 독립 기록 |

따라서 `data_ready=true`이면 충돌하는 모델 작업이 없는지 확인한 뒤 probe를 시작할 수 있다. Probe 시작에 이미 성공한 probe를 요구하는 순환 조건을 만들지 않는다. Probe도 실제 optimizer update지만 본 학습과 구분하며 본 실행 전 base checkpoint·optimizer·seed를 다시 시작한다.

현재의 준비 도구는 probe나 학습을 실행하지 않는다. 이후 실제 probe/학습은 원래 seed·2 epoch·최대 16 optimizer step·AdamW·microbatch/누적·FP16·checkpointing·5,376MiB allocated 상한·실패 시 중단 계약을 그대로 따른다. OOM 후 자동 재시도·CPU/클라우드 전환·batch/길이 조정·LoRA 교체·hyperparameter 탐색을 추가하지 않는다.

Calibration 비교·한 번의 고정 main dev 평가·잠긴 test 개방 조건·Java 운영 채택 검증도 기존 설계를 따른다. 이 준비 계약은 검색 개선, Java 서비스 성능 또는 운영 채택의 결과가 아니다. 유료 API/GPU/클라우드·공개 서비스 배포는 수행하지 않는다.
