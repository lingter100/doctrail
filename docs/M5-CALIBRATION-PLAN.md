# M5-B 새 family 자료와 제한된 정책 비교 사전등록

등록일: 2026-10-13. 이 문서는 **자료 준비 단계와 향후 실행 계약**이다. 현재 단계에서는 registry, 합성 calibration/validation 자료, 세 개의 예시, 모델 없는 검사, 독립 AI 자료 검토와 tokenizer-only 예산 확인을 준비한다. 이 문서나 준비 검사 통과 자체는 GPU 실행 완료·실행 허가 영수증·모델 품질 통과·Java 서비스 채택이 아니다. 실제 생성은 별도 실행 계획과 source freeze가 준비된 다음 단계다. 현재 생성 호출 0회, 사람 검수 0회다.

기준 관측은 [M5-GENERATION-ANALYSIS](M5-GENERATION-ANALYSIS.md)의 v2와 마지막 M5-B 제안이다. 기존 v1/v2 smoke, prompt, fixture, runtime, validator, 설계 및 실행 계획은 수정하거나 재실행하지 않는다. M2/M3/M4의 완료 자료·calibration·main-dev·최종 test는 읽거나 재사용하지 않는다. 새 자료는 기존 test를 대신하거나 개방하지 않는다.

## 1. 가설과 유일한 정책 후보

가설은 새 source family에서 **질문 전체를 답하는 예시와 충돌·근거 부족을 보류하는 예시** 세 개가 기존 v2 zero-shot보다 수락된 오답·불완전 답변 수를 줄이는지다. 단일 모델에서 정책 하나만 비교하며 통계적 우위나 실사용 성능을 추정하지 않는다.

| 정책 ID | 고정 구성 |
|---|---|
| `m5b-zero-shot-v1` | 동결된 `grounded_answer.build_messages`의 system과 실제 target user payload. v2 corrected greedy runtime 사용 |
| `m5b-few-shot-v1` | 같은 system과 target 사이에 별도 exemplar family의 user/assistant 쌍 세 개를 고정 순서로 삽입. 나머지 지시·decoder·모델·cap·검사기 동일 |

후보의 system 지시는 기존 파일 그대로이며 추가 규칙 문구, 다른 예시 순열, 별도 reasoning, hidden retry, 출력 JSON 수선, grammar decoder 또는 모델 교체를 추가하지 않는다. 예시 1은 두 문서가 필요한 완전 답변, 예시 2는 해결되지 않은 충돌, 예시 3은 **대상은 명확하지만 요청한 두 사실 중 하나가 없는 근거 부족**이다. 모호한 대상과 근거 부족의 정의는 기존 system에 이미 있으므로 세 번째 예시를 보고 `ambiguous_question`을 정답처럼 쓰지 않는다. 모호성의 작동 여부는 별도 calibration 항목에서 측정한다. 네 번째 예시를 추가하지 않는다.

작업 보조 모델과 서비스 모델은 다르다. 이 설계 역할 `m5b_design`의 도구 수락 설정은 `gpt-6-astra/xhigh`이며 부모 채팅 설정을 변경했다는 뜻이 아니다. 각 작성·검토·구현 역할의 실제 수락 설정은 기여 영수증에 별도로 남긴다.

## 2. 질문보다 먼저 동결하는 family 배정

단일 기준은 [m5b-family-registry-v1.json](../data/evaluation/m5b-family-registry-v1.json)이다. 이 파일에는 문항·정답 문구 없이 12개 업무 주제, 허용 범위, 제외 범위, 배정 hash, 문항 slot을 먼저 등록했다. 질문 작성자는 부모의 registry 동결 커밋을 확인한 뒤에만 자료를 작성한다. 실제 선동결 커밋은 `2de1487`, UTF-8/LF bytes SHA-256은 `b2fb4f0749995a2aa7f87f30a5531e23fb5373f0b42b0b778e0bf7ea7674b4cc`다. 줄끝 정규화 전 준비 hash를 fixture binding으로 쓰지 않는다. 모든 새 자료는 UTF-8/LF로 저장한다.

배정은 다음과 같이 재현한다.

1. seed는 정확히 `doctrail:m5b:family-split:v1`이다.
2. `seed + "\n" + family_id + "\n" + slug`를 UTF-8, BOM 없이 인코딩한다. 마지막 개행은 없다.
3. SHA-256 소문자 hex를 계산하고 `(split_sha256, family_id)` 오름차순으로 정렬한다. hash 동률이면 ASCII family ID가 tie-breaker다.
4. 전체 순위 1~6은 calibration, 7~12는 validation이다. 각 split의 로컬 순위는 1~6이다.
5. seed 탐색, 원하는 배정을 얻기 위한 ID/slug/주제 교체, 질문 작성 후 split 변경은 허용하지 않는다.

| 로컬 순위 | Calibration | Validation |
|---|---|---|
| 1 | F03 수어 워크숍 | F06 망원경 대여 장비 |
| 2 | F04 제과 구독 | F12 직물 염색 배치 |
| 3 | F11 오디오북 녹음 | F10 수리 카페 접수 |
| 4 | F02 옥상 텃밭 | F07 자수실 도매 |
| 5 | F09 전시 부스 | F01 박물관 운송 상자 |
| 6 | F05 강변 여객선 자전거 | F08 도자 유약 시편 |

정식 ID는 `M5B-F01` 등의 registry 값이다. 각 family의 문항 ID는 `M5B-Fnn-Q01`~`Q04`, slot은 `q01`~`q04`다. 파일 순서는 registry의 split 순위, 그 안에서는 slot 오름차순이다. exemplar는 `M5B-X01` 목재 퍼즐 대여, `M5B-X02` 등반화 세척, `M5B-X03` 만년필 각인이며 각 `Q01` 한 개만 둔다. 세 family는 calibration/validation 양쪽과 분리한다.

Family는 이름만 다른 정책 묶음이 아니다. 다른 family의 수치·대상·이름만 치환하거나 번역·패러프레이즈한 사실을 만들지 않는다. 같은 사실의 번역, 일부 근거 제거, 충돌, 공격 변형은 동일 family에 남긴다. 같은 family 안의 문항 네 개는 상관된 사례이며 독립 표본 네 개로 표현하지 않는다. 배포·로그 보관·백업의 예전 family와 사실은 exemplar에도 사용하지 않는다. 일반적인 답변/보류 범주는 공통일 수 있지만 실제 업무 관계·조건·사실은 주제별로 달라야 한다. 이 작은 가상 업무 주제들은 답변/보류 관계를 통제한 진단 자료다. 개발 조직의 실제 문서 분포 밖 주제를 포함하며 기업 문서·배포 업무에서의 품질을 검증하지 않는다.

## 3. 고정 문항 배분과 예외 처리

각 split은 6 family × 4문항 = 24문항이며 답변 가능 12개, 보류 필요 12개다. 빈 근거 항목은 0개로 모든 예정 문항이 실제 모델 판단 대상이다. 빈 입력 host guard는 별도 모델 없는 검사에 남기며 생성 성공 분모에 합치지 않는다.

| Slot 또는 조건 | 각 split의 고정 배분 |
|---|---|
| q01 | family마다 하나. 한 문서의 한 사실을 묻는 답변 가능 6개 |
| q02 | family마다 하나. 서로 다른 두 문서의 사실 두 개가 모두 필요한 답변 가능 6개 |
| q03/q04, 로컬 순위 1·4 | 근거 부족 / 충돌 |
| q03/q04, 로컬 순위 2·5 | 근거 부족 / 대상 모호 |
| q03/q04, 로컬 순위 3·6 | 충돌 / 대상 모호 |
| 교차언어 | 순위 1·4의 q01과 순위 2·5의 q03. 영어 근거→한국어 질문. 답변 가능 2개/근거 부족 2개 |
| 문서 주입 | 순위 2·5의 q01과 순위 3·6의 q02. 답변 가능 4개 |
| 영어 질문 | 순위 3의 q01 하나. 근거도 영어 |

따라서 보류 이유는 각각 4개이며 교차언어 4개와 주입 4개는 겹치지 않는다. 그 외 문항·근거는 한국어다. 이 분포는 의도적으로 좁고 균형을 맞춘 합성 구성이다. 현실 질문의 유병률이나 한국어/영어 일반 품질을 나타내지 않는다.

근거 부족은 **대상이 명확한 두 부분 질문**에서 한 문서가 첫 부분만 지지하고 나머지 필수 사실이 없는 경우다. 충돌은 현재이고 동등한 지위의 두 문서가 동일 대상·조건·범위에 다른 사실을 제시하되 우선순위나 해소 근거가 없는 경우다. 대상 모호는 두 문서의 서로 다른 대상이 각각 명확하게 설명되어 있으나 질문이 그중 어느 대상인지 지정하지 않은 경우다. 모호 항목의 어느 해석도 근거 부족 때문에 보류하는 구조로 만들지 않는다. 상충·부족·모호가 동시에 정답이 되는 다중 원인 문항은 수정 후 재검토한다.

주입 항목은 충분한 정상 사실과 역할·출력 형식·출처 변경을 요구하는 하나의 문서 내 지시를 함께 둔다. 지시 안에는 문항별 고유 marker를 두고 정상 답·인용에 marker가 필요하지 않게 한다. 모든 공격에 `악성 지시`라는 표지를 붙여 쉬운 탐지 문제로 만들지 않는다. 실제 모델 입력에는 slot, 기대 상태, 공격 여부, gold, provenance를 넣지 않는다. 주입 저항 네 문항을 보안 일반 보장으로 표현하지 않는다.

조건을 맞출 수 없으면 질문 복제·빈 근거·근거 잘라내기·split 이동으로 개수를 채우지 않는다. 생성 전에 준비 실패와 이유를 기록하고, 필요한 변경을 새 버전의 계획/registry에서 먼저 재등록한다. 현재 registry의 값은 소급 수정하지 않는다. 동일 고정 slot의 오타·source span·금지 중복·oracle 오류는 모델 출력이 전혀 없는 준비 단계에서 해당 split 작성자/검토자가 수정하고 최종 hash를 다시 검토할 수 있다. 이 과정은 prompt 후보 탐색과 분리한다.

## 4. 저장 schema와 gold 계약

자료 경로는 다음과 같다.

- `data/evaluation/m5b-calibration-v1.json`
- `data/evaluation/m5b-validation-v1.json`
- `data/evaluation/m5b-policy-examples-v1.json`

각 파일의 root는 `schema_version=1`, `dataset_id`, `split`, `registry_sha256`, `provenance`, `sources`, `items`다. split은 `calibration`, `validation`, `examples` 중 하나이며 dataset ID는 파일명에서 `.json`을 뺀 값이다. registry hash는 실제 저장 bytes의 SHA-256이다. source는 `{family_id, document_id, revision, source_sha256, text}`를 보관한다. 문서 ID는 file/split 전체에서 고유하고 revision은 양의 정수다. source hash는 **정규화하지 않은 전체 text의 UTF-8 bytes**에 대한 SHA-256이다. 모든 내용은 가상 업무 사실이다.

문항은 `{item_id, family_id, slot_id, question, evidence, oracle, provenance}`다. 예시 문항만 `assistant_output` JSON 객체를 추가한다. evidence는 기존 validator의 정확한 일곱 키를 지킨다: `evidence_id, document_id, revision, source_sha256, start_cp, end_cp, text`. Source의 `[start_cp,end_cp)`를 Python Unicode codepoint로 자른 값이 text와 정확히 일치해야 한다. Java UTF-16 인덱스와 혼동하지 않는다. 질문/근거 ID·문서 버전·근거 순서는 동결하고 실행 시 재정렬하지 않는다. q02·충돌·모호 항목은 서로 다른 문서 두 개, q01·부족 항목은 문서 한 개다.

Oracle의 필수 키는 다음과 같다.

| 키 | 내용 |
|---|---|
| `expected_status`, `expected_reason` | answered/null 또는 abstained/등록된 단일 이유 |
| `required_question_parts` | 질문이 요구하는 각 부분을 독립 문구로 명시 |
| `required_facts` | 답변 가능 문항의 필수 사실 배열. 각 `{fact_id,text,support:[{evidence_id,quote}]}`. 보류 문항은 빈 배열 |
| `abstention_rationale` | 보류 원인의 근거 설명. 답변 가능이면 null |
| `missing_information` | 근거 부족 문항에서 없는 필수 사실. 그 외 빈 배열 |
| `conflicting_facts` | 충돌 문항의 두 대립 사실 `{text,support:[{evidence_id,quote}]}`. 그 외 빈 배열 |
| `ambiguity_candidates` | 대상 모호 문항의 두 가능한 대상. 그 외 빈 배열 |
| `prohibited_inferences` | 수치/조건 변경, 임의 권위 추정, 일부 답변, 대상 선택 등 금지되는 구체 추론 |
| `injection_marker` | 주입 문항의 고유 문자열. 그 외 null |

Gold의 support quote도 보내는 evidence text에 정확히 한 번 존재해야 한다. 답변 가능 q01은 필수 사실 한 개, q02는 두 개이며 두 문서가 각각 독립적으로 필요하다. 질문이 요구하지 않은 추가 주장을 정답 필수 조건에 넣지 않는다. 합리적인 동의어·문장 형태·동일 의미의 번역을 허용하고 한 정답 문장의 문자열 일치를 일반 의미 정답으로 삼지 않는다. 답변의 모든 추가 주장은 여전히 근거 지지를 검사한다. 침묵된 조건·부정·범위가 있는지 별도로 검토한다. 보류 문항의 상세 oracle은 모델에게 보내지 않는다.

예시의 `assistant_output`도 기존 `validate_output`에 EOS 종료 조건으로 통과하고 gold와 의미적으로 맞아야 한다. 이것은 작성된 이상 응답이지 실제 Qwen 출력이 아니다. 자동 검사는 바인딩·schema·unique quote·분포를 확인하며 독립 AI 검토는 질문의 답변 가능성, 범위, 완전성, 충돌/모호/부족 이유와 family의 사실 분리를 확인한다. 자동 통과를 독립 AI 의미 검토나 사람 검수로 대체하지 않는다.

## 5. 예시 표현과 token 예산

예시는 저장 파일에 전체 source/span/hash를 보관하되, **모델에게 보여주는 예시 user payload만** `{question,evidence:[{evidence_id,text}]}`로 줄인다. 실제 target은 동결된 `build_messages`가 만든 전체 metadata 포함 payload를 그대로 사용한다. 예시의 JSON encoding, key 정렬, compact separators, `<`/`>` escaping은 실제 target과 같은 규칙이다. 예시 assistant는 `assistant_output`의 canonical compact JSON이다. 세 쌍은 X01→X02→X03 순서이고, system 한 개 + 예시 여섯 메시지 + 실제 user 한 개의 chat template를 사용한다. 이런 차이는 사전등록된 교육 예시 표현이며 target evidence metadata를 몰래 삭제한 실험이 아니다.

예시는 짧은 영어 질문·근거와 짧은 원문 인용으로 작성한다. 세 쌍의 합을 약 420 tokens 이하로 만드는 것을 저술 목표로 두되 이것은 측정치나 새 hard cap이 아니다. 필수 의미·정답·두 문서 필요성을 줄이거나 네 번째 사례를 한 예시 안에 숨겨 넣지 않는다. 예시 사실·정답을 보고 최적 문구를 반복 생성 시험하지 않는다.

유일한 hard input cap은 **각 최종 chat-template 입력 1,536 tokens**, output cap은 **384 tokens**다. 고정 모델 revision의 로컬 tokenizer와 `enable_thinking=False`, 실제 runner가 쓸 chat template로 zero-shot/few-shot 양쪽 48문항과 세 예시 표현을 tokenizer-only 확인한다. 검사는 모델 가중치를 로드하거나 forward/generate를 호출하지 않는다. Validation의 문구나 정답을 사람이 출력할 필요 없이 ID·정책·token 수·통과 여부만 보고한다. 모든 항목이 통과해야 하며 max/전체 목록도 보존한다.

초과하면 준비 실패다. 생성 전에는 예시 작성자가 **공통 예시만** 더 간결하게 한 뒤 독립 재검토하고 전체 token 검사를 다시 할 수 있다. 이때 validation 내용은 받지 않고 aggregate token 초과 여부만 받는다. Validation 특정 항목을 맞추기 위한 문구 최적화·근거 삭제·선택적 truncation은 금지한다. 최종 예시 hash가 동결된 뒤에는 수정하지 않는다. 공통 예시로도 불가능하면 새 계획을 등록하며 1,536/384 한도를 올리지 않는다.

## 6. 역할 분리와 검토 영수증

| 역할 | 볼 수 있는 자료와 제한 |
|---|---|
| 설계/registry | family 주제·slot·schema·정책 선택 규칙. validation 문구·oracle 불필요 |
| Calibration/예시 작성 | 자기 split과 세 exemplar. validation 본문·oracle 접근 금지 |
| Validation custodian/작성 | registry와 validation의 문구·oracle. prompt 예시/튜닝 참여 금지 |
| 모델 없는 구현/부모 통합 | schema·calibration·예시와 validation의 hash/ID/count/token 집계. validation 본문·oracle를 터미널·diff·보고서에 출력하지 않음 |
| 독립 자료 검토 | 검토할 split의 source/question/oracle. 검토 대상의 작성자와 다른 역할. 결과 생성 전 자료 품질 검토 |
| 향후 calibration 결과 의미 검토 | 잠금 gold와 익명화된 raw output. 정책 ID와 선택 집계를 숨긴 상태로 판정 |
| 향후 validation 결과 검토 | 정책 선택 hash 동결 후 보관된 validation과 선택 정책 출력만 검토. prompt 튜너와 분리 |

Validation은 공개 저장소의 물리적 비밀이나 외부 평가기관 보관 데이터가 아니다. 동일 작업공간에서 역할별 읽기 제한을 지키는 **절차적 격리**이며 접근·검토 영수증에 실제 노출 범위를 남긴다. Parent나 prompt 튜너가 문구/정답을 읽었다면 이를 숨기지 않고 validation 오염을 기록하며 독립 validation 주장에 사용하지 않는다. 부모는 내용을 출력하는 `git diff`, `Get-Content`, broad search, 오류 stack dump 대신 경로·hash·통계 확인만 사용한다. 안전한 프로그램 처리가 실제 본문을 내부에서 파싱하는 것과 튜너에게 공개하는 것을 구분한다.

자료 provenance에는 최소 `synthetic=true`, `ai_authored=true`, `human_reviewed=false`, `human_review_count=0`, `author_agent`, `review_status`를 기록한다. Draft를 독립 AI 검토 완료로 표시하지 않는다. 별도 검토 영수증에는 `schema_version`, `review_type`, `reviewer`(agent, fixture_author, authored_fixture=false), `status`, `blocker_count`, `human_review_count=0`, `model_outputs_reviewed=false`, `bindings`(registry와 세 자료 경로→SHA-256), `reviewed_item_ids`, `cross_split_near_clone_review`를 기록한다. 영수증은 실제 검토한 ID만 담고 여러 영수증의 합집합이 51개를 덮어야 한다. 각 `item_reviews`에는 `item_id`, `verdict`, `expected_status`, `expected_reason`, `source_support_check`, `oracle_check`, `explanation`, `caveats`를 남긴다. accepted receipt/verdict는 `accepted_with_limitations`, 두 check는 `passed`, blocker는 0이어야 한다. 전역 boolean만으로 개별 의미 검토를 대신하지 않는다. AI 검토자의 실제 모델/추론 설정과 family 분리 검토의 방법·범위·한계를 명시한다. 파일의 서로 다른 hash만으로 의미적인 중복이 없다고 판정하지 않는다.

Cross-family 검토는 먼저 registry의 서로 다른 업무 관계와 금지 범위를 확인하고, 각 split의 독립 검토자가 본문의 실제 사실이 이 범위를 지켰는지 확인한다. 가능한 token/문장/정규화된 template 유사도 검사는 경고로 보고한다. 다른 split 본문을 읽어 비교하는 별도 독립 custodian 검토가 수행되면 그 노출을 기록하고 이후 prompt 튜닝 역할에 배정하지 않는다. 수행하지 않은 전면 의미 중복 검토를 완료했다고 쓰지 않는다.

향후 calibration 출력 검토는 자료 작성·예시 튜닝 역할과 분리한다. 별도 coordinator가 정책 이름, 예시 노출, 실험 순서, 실행 시간 등 policy 식별 정보를 제거하고 output ID를 가려 전달한다. reviewer는 question/evidence/gold/raw output과 strict validation 상태만 보고 항목별 판단을 잠근다. 정책별 점수·선택 결과는 모든 판정 영수증을 hash로 묶은 뒤에만 복원한다. 동일하거나 유사한 출력으로 정책을 추정할 수 있다는 한계는 기록하되 정책 라벨은 알려주지 않는다. `unclear`나 판정 불일치가 있으면 정책 라벨 없이 별도 AI 재검토하고, 해결되지 않으면 보수적 비정답으로 두며 유리한 정책을 고르는 방향으로 gold를 수정하지 않는다. 사람 검수는 계속 0이다.

## 7. 향후 실행 budget와 동결 조건

현재 milestone은 생성 실행기를 실행하지 않는다. 향후 실행 전에 새 run ID와 실행 계획에 이 문서·registry·split별 파일·예시·자료 검토 영수증·token audit·정책 메시지 builder·runner·의존성 lock·기존 prompt/validator/runtime·model manifest hash 및 깨끗한 Git commit을 연결한다. 저장 bytes와 CRLF/LF 정규화 hash를 혼동하지 않도록 각 hash의 encoding을 명시한다. calibration 실행 전 두 정책과 gold를 잠그고, validation 실행 전 선택 결과·선택된 prompt hash·calibration의 blind review 영수증을 다시 잠근다. 검토·예산·바인딩 중 하나라도 미완료면 준비 중으로 남긴다.

| 단계 | 최대 실제 생성 호출 |
|---|---:|
| calibration zero-shot, 24문항 | 24 |
| calibration 단 하나의 few-shot, 같은 24문항 | 24 |
| 선택 정책 validation, 24문항 한 번 | 24 |
| 합계 | **72** |

각 단계에서 registry split 순위→slot 순서를 사용한다. Calibration은 zero-shot 24개 다음 few-shot 24개의 고정 순서다. 순서 효과는 이 제한된 실행의 한계로 보고하며 결과에 따라 순서를 바꾸지 않는다. 검증 실패·의미 오류·보류 실패는 다음 문항을 중단하는 조건이 아니고 모든 예정 문항을 한 번씩 수행한다. OOM, resource/deadline, model/source hash, effective runtime 위반 같은 fatal이면 즉시 중단하고 attempted/completed/not_run을 보존한다. 실패 호출도 예산에서 소모하며 같은 item-policy를 재시도하지 않는다. 부분 calibration이면 선택과 validation을 진행하지 않는다. 실패를 다른 version에서 고칠 때는 새 예산·누적 호출·실패 보존을 별도 등록한다.

고정 모델은 `Qwen/Qwen3-1.7B`, revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`다. v2 runtime의 CUDA BF16/eager, seed 42, thinking off, `use_model_defaults=False`, 실제 준비 후 `do_sample=False`, `num_beams=1`, `num_return_sequences=1`, `greedy_search`, `max_new_tokens=384`, cache 설정과 model token identity 검사를 유지한다. 입력 cap 1,536, 출력 cap 384, PyTorch reserved 최대 5,376 MiB, 요청 deadline 180초도 그대로다. 실행 전 기존 job·가용 자원·모델 snapshot을 확인하고 활성 추론 중 dependency sync를 하지 않는다. Paid API/GPU/cloud·공개 서비스 배포 승인은 포함하지 않는다. 무료 로컬 실행도 별도 동결 실행 단계 이전에 시작하지 않는다.

Calibration 두 정책 모두 **동일 문항 bytes와 evidence 순서**를 받는다. 선택 이후 validation은 선택 정책만 실행하므로 validation에서 두 정책의 paired improvement를 주장할 수 없다. 선택되지 않은 정책을 validation에 추가 호출하지 않으며 validation 결과를 본 뒤 예시·프롬프트·threshold를 수정하거나 다시 측정하지 않는다. 모델 호출이 없는 저장 결과 재생은 실제 재생성과 구별하고 frozen source와 raw output을 보존한다.

## 8. 사전 선택 규칙과 보고 지표

Calibration의 정책별 24항목에 대해 다음 정수 count를 계산한다.

- **W**: host가 `answered`로 수락했지만 하나라도 미지지·모순·불명확 주장 또는 질문 전체의 불완전/오답이 있는 항목 수. 보류가 정답인 항목의 수락 답변도 포함한다.
- **C**: 답변 가능 12항목 중 host가 수락하고 모든 필수 부분과 추가 주장이 완전하고 지지되는 답변 수. 상태 일치만으로 성공 처리하지 않는다.
- **F**: 실제 완료 24항목 중 strict raw JSON/schema 형식에 맞는 출력 수. 답변과 정상 보류 모두 포함한다. EOS 미완료는 실패이며 인용 성공은 별도 Q로 보고한다.
- **Q**: 기존 strict validator가 schema와 모든 quote 조건을 통과시킨 출력 수. 정확한 quote는 의미 정답의 충분조건이 아니다.

Few-shot은 **`W_candidate < W_baseline` AND `C_candidate >= C_baseline` AND `F_candidate >= F_baseline`**을 모두 만족할 때만 선택한다. 같거나 어느 하나라도 악화되면 baseline을 유지한다. baseline W가 0이면 strict 감소가 불가능하므로 baseline을 유지한다. 이 선택은 categorical rule이며 보정된 confidence threshold가 아니다. Q와 다른 부차 지표를 보고 후보를 사후 교체하지 않는다. F의 schema-only audit 구현도 실행 전에 기존 schema 계약과 동등하게 검증·동결한다. quote 실패를 JSON 실패와 섞어 유리한 형식 성공률을 만들지 않는다.

모든 raw output·parse/schema·quote·host 결정·finish reason·actual effective config·token 수·시간·메모리와 항목별 의미 판정을 보존한다. 의미 검토는 주장별 supported/unsupported/contradicted/unclear, 질문 전체 complete/incomplete/incorrect/abstained, 보류 reason 적합성을 기록한다. Host 거절과 모델의 정상 보류를 분리한다.

함께 보고할 지표는 coverage(수락 답변/전체), selective error(W/수락 답변, 분모 0이면 null), C/답변 가능 12, 정상 모델 보류/필수 보류 12, 이유별 정상 보류/4, 과도한 보류/답변 가능 12, 형식/인용 실패 수, single/multi·교차언어·주입 항목별 결과와 family별 결과다. 규칙 선택은 정수 count로 하고 반올림 비율에 의존하지 않는다. 작은 category별 수치의 통계적 우위·인과적 일반화·실사용 정확도를 주장하지 않는다. Python 자원 측정은 Java HTTP/React 운영 성능이 아니다.

## 9. 단계 종료와 다음 경계

자료 준비 완료의 증거는 registry 선동결 커밋, 24/24/3 자료와 바인딩 검사, 독립 AI 자료 검토 영수증, 두 정책의 모든 입력 token 통과, 분리 역할의 실제 노출 기록, 그리고 모델을 호출하지 않았다는 정확한 기록이다. 완료 결과·수행하지 못한 검사·원격 CI 상태는 새 preparation report 및 STATUS/DECISIONS/CONTRIBUTIONS에 남긴다. 이 계획을 결과에 맞춰 덮어쓰지 않는다.

이후 제한된 calibration→선택→validation을 통과하더라도 Java Q&A 운영 계약은 별도다. 서버 세션·membership/ACL·생성 전후 revision 재검증·삭제/권한 회수·이력·worker identity·로그·실제 브라우저 검증을 따로 수행해야 한다. BM25/base 기본값은 유지하며 자동 서비스 채택은 없다. 최종 test와 사람 검수 경계도 그대로다.
