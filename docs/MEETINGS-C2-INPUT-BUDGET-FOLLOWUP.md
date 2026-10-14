# C2 입력 준비 실패 이후의 제한된 예산 후속 설계

2026-10-14. **설계만 완료. 새 구현·tokenizer 실행·native 생성·서비스 채택은 이 문서 작성에서 모두 0이다.** 설계 역할은 `c2_budget_followup`이며 이후 독립 출력 scorer에서 제외한다. 실제 개발 모델/effort 증거는 부모의 역할 생성 영수증으로 남긴다. 서비스 추론 모델과 개발 모델은 별개다.

결정은 **기존 C2 4,096-token 준비 실패를 닫아 보존하고, 공통 입력 상한만 5,120으로 바꾼 별도 후속 프로토콜을 한 번 등록하는 것**이다. Native context는 6,144를 그대로 쓴다. 문항·oracle·전체 context·prompt·단위 분할·출력384·90초는 바꾸지 않는다. 기존 문항을 계속 쓰는 것은 아래의 명시적인 프로토콜 이탈과 길이 노출 한계를 가진 후속이며, 원래 C2 계획의 성공이나 완전히 미노출된 신규 검증으로 소급 계산하지 않는다.

## 1. 관측과 접근 범위

설계자가 직접 읽은 것은 `AGENTS.md`, [원래 비교 계획](MEETINGS-C2-COMPARISON-PLAN.md), [검토 계약](MEETINGS-C2-REVIEW-CONTRACT.md), [준비 기록](MEETINGS-C2-PREPARATION.md), [닫힌 자원 결과](MEETINGS-C2-RESOURCES.md)와 공통 입력/tokenizer/어댑터/실행/audit 코드다. Validation 디렉터리·manifest·본문·질문·oracle·semantic review, 과거 C0/C1/M5-B 품질 pool은 열지 않았다. 아래 최신 실패 수치는 부모가 전달한 메타데이터이며 설계자가 원본을 독립 재확인한 값이 아니다.

- Calibration8은 먼저 동결됐고 공식 tokenizer16입력은 모두 통과했다. 최대 L0 3,140/C2 3,730이다.
- Validation12 v2는 별도 문항 사전 검토에서12수락이고, 이전2거절과 새 파일을 포함한 item freeze는 `0a58129`로 tokenizer보다 먼저 고정됐다고 전달받았다.
- 첫 CLI의 외부 오류는 `input_preparation_failed`였다. 이것만으로 내부 원인을 단정하지 않는다. 뒤의 직접 계측에서 일곱 번째 항목 `c2-val-07`의 C2 4,572 > 4,096이 관측됐다.
- 이 계측은7/12항목,14개 arm 길이까지만 확인했다. L0 753~3,631, C2 807~4,572이며 나머지5항목은 미측정이다. 4,572를 전체 최대라고 부르지 않는다.
- 새 품질 생성0, 인간 검수0이다. 기존 C2-P0 자원 native2만 이미 완료됐고 재실행하지 않는다.

첫 CLI와 뒤의 계측은 별도 사건으로 기록한다. 각각의 시각·command/source/draft/item-freeze hash·완료 수·safe error·native0를 가진 새 실패 영수증이 필요하다. 원래 출력/로그가 없는 경우 새 기록은 당시 영수증이 아니라 사후 작성임을 표시한다. 오류 텍스트·문항 본문을 운영 로그로 내보내지 않는다.

## 2. 같은 문항을 유지하는 이유와 허용 범위

원래 비교 계획에는 입력상한 위반을 준비 실패로 남기고 내용을 잘라 통과시키지 않는 규칙, 실패 뒤 같은 자료로 정책을 고쳐 재시도하지 않는 규칙이 있다. 따라서 상한 변경을 원래 계획에 내재된 허용사항이나 단순 버그 수정으로 해석할 수 없다. 원래 source41와 processing18, 문항/source freeze, calibration input/token receipt, 실패한 validation 준비 증거는 모두 그대로 둔다. 원래 프로토콜은 `preflight_failed_input_budget`, quality dispatch0으로 보존한다.

그 위에 다음 조건을 가진 **새 자원 계약의 후속**을 등록한다. 권고 식별자는 `meeting-answer-blocks-c2-input-budget-v1`이다. 새 plan에는 `supersedes_for_execution_only`, 원래 실패 영수증 SHA, `protocol_deviation: equal_input_cap_4096_to_5120_after_length_metadata`, 노출 역할 목록을 명시한다. 기존 계획의 무수정 재시도로 명명하지 않는다.

1. 지금까지 품질 응답이0이고, 부모/후속 설계자는 validation의 의미 내용을 보지 않았다. 노출된 것은 ID·길이·상한 실패 메타데이터다.
2. 두 arm의 상한을 함께 바꾸며, 입력 길이에 따라 문항·원문·chunk·순서·prompt·근거 단위·oracle·품질 기준을 바꾸지 않는다. 현재8/12 전부가 분모에 남는다.
3. 후속의 유일한 새 변인은 공통 입력 자원 상한이다. 기존 원문 선택이 잘 됐는지 사후 재검토하거나, 더 작은 context로 치환하는 기회로 쓰지 않는다.
4. 같은 문항을 재사용했다는 사실과 validation 길이가 후속 자원 설계에 영향을 줬다는 사실을 결과·포트폴리오에 공개한다. `fresh validation`, `untouched holdout`, 원래 C2의 사전등록 성공으로 쓰지 않는다.

**이번 제한된 제품 개발 후속을 위해 새 문항 작성은 요구하지 않는다.** 위 조건에서 같은 항목은 처음 생성되는 출력의 엄격한 의미 검증과 운영 진행 여부를 판단하는 데 사용할 수 있다. 다만 원래 4,096 조건의 가설 확인, 길이 정보까지 전혀 보지 않은 확증 결과 또는 일반화 성능을 주장하려면 별도로 미노출 출처/문항과 사전등록이 필요하다. 그 주장을 지금 목표로 삼아 또 다른 자료 작성 주기를 열지 않는다. 이미 validation 내용을 본 사람에게 재작성만 맡긴 것을 독립성 복구라고 부르지도 않는다.

이 결정은 원래 계획의 금지를 지워 없애는 해석이 아니라, 이탈 사실을 보존한 명시적 후속 설계다. 자동 채택이나 새로운 인간 승인 요구를 만들지 않는다. 유료 서비스와 공개 배포 경계는 그대로다.

## 3. 먼저 고정할 단일 예산

| 항목 | L0 후속 | C2 후속 |
|---|---:|---:|
| 공식/실제 native 입력 상한 | 5,120 tokens | 5,120 tokens |
| native context | 6,144 | 6,144 |
| 출력 상한 | 384 | 384 |
| 요청 전체 준비·생성·후처리 | 90초 미만 | 90초 미만 |
| 종료 확인 / 요청~정리 안전 경계 | 5초 / 120초 | 5초 / 120초 |
| 생성·retry·warmup·동시성 | 1 / 0 / 0 / 1 | 동일 |
| 모델/GGUF/runtime/tokenizer/설정 | 기존 고정 identity | 동일 |
| GPU layers / batch / ubatch / fit | 24 / 512 / 128 / off | 동일 |
| greedy/seed/nonthinking/cache | 기존 값 유지 | 동일 |

5,120은 4,572에 여유를 덧붙여 산출한 값이 아니다. 이미 구성된 6,144 context 안에서 **출력384와 예약 여유640을 먼저 남기는 단일 운용 상한**이다: `6144 - 384 - 640 = 5120`. 640은 검증된 모델 요구량이나 KV 메모리 여유가 아니라 이번 후속의 보수적인 토큰 예약이다. 공식 count에는 채팅 template·비생각 preamble이 이미 포함된다. Native 전달 token 배열도 독립적으로 5,120 이하인지 확인하며 숨겨진 추가 토큰을 예약 여유로 묵인하지 않는다.

이 문서/상한을 commit한 **뒤에** 미측정5개를 포함한 전체 길이를 확인한다. `max + margin`, 최대값을1,024 단위로 올림, 5,120→5,632→8,192 같은 단계적 상향은 등록하지 않는다. 하나라도5,120을 넘거나 기존 구조/bytes 제한에 실패하면 이 후속도 생성0에서 종료한다. 문항을 빼거나 다른 문항을 작성하여 이 실행을 살리지 않는다. 이후 제품 경로는 별도 결정사항이며 이 문서는 또 다른 cap 확대를 자동 허용하지 않는다.

## 4. 전 항목 메타데이터 조사와 공식 준비

**전체12항목/24 arm 길이 조사가 필요하다.** 현재7항목의 최대만으로 자원 계획이나 실행 가능성을 확정하지 않는다. 격리 custodian만 frozen v2 draft를 읽는다. 새 조사 도구는 기존 공식 tokenizer와 frozen catalog/prompt를 그대로 사용하고, 상한 초과를 발견해도 가능한 나머지 항목을 계속 계수한다. 각 실패는 안전한 범주와 측정 가능 여부로 남기며 `unknown`을0이나 통과로 바꾸지 않는다. 정적 구조 검사가 실패한 항목의 prompt를 임의 수리하지 않는다.

조사 영수증은 다음을 분리한다.

- 원래4,096 판정과 후속5,120 판정, 전체/측정/실패/미측정 수.
- 항목ID·arm·공식token수·prompt/grammar hash·단위/청크 수, tokenizer asset/source hash.
- 원래 draft와 item/source freeze hash, 원본 파일 byte 수, canonical 원래 payload hash와 변환 후 동일성 boolean.
- 원문 context의 개수·순서·좌표·문서/revision·문자열·제목·회의일·nullable/생략 필드의 보존 검사 결과. 원문/metadata 값을 부모에게 보여주지 않는다.
- 각 입력/출력 JSON의 byte 수, native 요청 직렬화 byte 수가 기존 상한 안인지 여부, native/generation/download0.

부모에게는 두 상한별 통과 수, min/max, 측정 완료 수, 원문 보존 boolean, hash와 추상 오류 범주만 보낸다. 항목별 길이표도 custodian 산출물로 봉인할 수 있다. 이미 노출된 일곱 번째 ID/길이는 삭제하지 않지만 추가 ID별 길이를 부모에게 줄 필요는 없다. Oracle/semantic receipt는 조사 도구에 필요하지 않으며 읽지 않는다.

모든24개가 정적 검사와5,120을 만족해야 **새 경로**에 공식 prepared input/token receipt를 만든다. Calibration도 기존8개 payload와16개 count가 그대로인지 대조하고 새 프로토콜에 연결한다. 이전 input.json을 덮어쓰지 않는다. 새 receipt의 추가 필드는 payload 밖에 둔다. 정확한 원래 bytes hash와 canonical payload equality를 함께 기록해 JSON 포맷 변경을 원문 변경으로 혼동하지 않게 한다.

새 cap으로 단순히 실패를 감추지 않도록 원래4,096 초과 수를 항상 결과에 남긴다. 길이 조사와 입력 준비는 모델 가중치 열기/추론/native 시작/다운로드가 모두0인 별도 단계다.

## 5. 자원 위험과 새 중립 확인의 범위

대상 하드웨어는 부모가 전달한 RTX4050 Laptop6GB/RAM32GB다. 이 설계에서 장치 상태나 현재 여유 메모리는 측정하지 않았다. 기존 자원 보고서의 RSS 최대 표본은 각각6,243.65/6,273.39MiB인 native **CPU 프로세스 메모리**이며 VRAM 여유가 아니다. 이전 입력3,881의 성공은5,120 입력의 성공을 증명하지 않는다.

Native context6,144와24layers를 유지하므로 context 확대에 따른 새로운 KV/cache 용량 설정을 도입하지 않는다. 그러나 실제 peak, prefill 임시 버퍼, Windows 공유GPU메모리, CPU offload, 다른 프로세스와의 경쟁은 입력 길이에 따라 영향을 받을 수 있다. 모델 구조/캐시 dtype/정적·동적 할당을 확인하지 않고 VRAM 사용량이나 tokens/second를 계산해 보장하지 않는다. 8,192 context, 자동 fit, layer 변경, KV 양자화, CPU fallback, batch 변경은 이번 후속에 없다.

새 neutral resource plan은 **네이티브 호출 최대4회**로 고정한다: 새 normal DTO에 L0→C2 두 번, 새 stress DTO에 C2→L0 두 번이다. 두 arm의 새 입력 guard와 정상 EOS/상한 출력 경로를 모두 실제 확인하려면 이2×2가 가장 작은 대칭 확인이다. 기존2회와 fixture를 재사용하지 않고 품질 문항도 쓰지 않는다. 각 DTO 안에서 두 arm은 질문·context·순서·metadata가 완전히 같다. 이 순서는 품질 비교 순서와 별개로 사전 고정한다.

새 neutral fixture는 평가 계열과 무관한 기계적 자료로 만든다. 모델 없는 deterministic 구성 단계에서 stress의 큰 쪽 arm 공식입력을4,992~5,120, 작은 쪽도4,096 초과로 맞추고 두 쪽 모두5,120 이하로 고정한다. whole chunk/블록 제한을 지키며 생성 전에 fixture bytes·두 prompt/grammar hash와 count를 봉인한다. 이 조건을 찾지 못하면 생성하지 않는다. Neutral 자료의 기계적 길이 구성은 frozen 평가 입력을 자르는 행위와 분리하며, 완료 뒤 native 결과에 따라 fixture를 다시 고르지 않는다.

- Normal2: 각 arm의 실제 정상 문법·mapper 경로, 단일 생성, EOS,384이하,90초 미만을 요구한다. 정상 fixture의 공식 길이는1,024이하로 제한한다. 구조·원문 위치와 toy 사실 일치를 확인하되 제품 답변 품질 점수로 계산하지 않는다.
- Stress2: 같은 큰 DTO, 각 arm의 실제 prompt/native 준비를 거친다. 출력 부하만 사전등록한 별도 기계적 grammar로384tokens까지 요구한다. 정확히384/length 종료와90초 미만은 **자원 조건만** 만족시킨다. 이 특수 grammar override는 resource 전용 경로로 격리하고 품질 runner에서는 불가능하게 한다.
- 공통: weights/runtime/tokenizer·nonthinking/greedy/cache0·native input5,120이하·토큰 간단 합5,504이하·raw 응답·dispatch 전 영수증·실제 호출 수·정리 완료를 검증한다. 공식/native count 불일치는 기록하고 미리 봉인한 일치 요구를 만족하지 않으면 즉시 중단한다. 완료된 호출을 다시 수행하지 않는다.
- 메모리:0.25초 표본 native RSS와 시스템 available RAM을 남긴다. 이미 사용 가능한 NVIDIA 계측이 있으면 device used/total VRAM도 같은 범위에서 기록하고, GPU 프로세스별 수치가 없으면 없다고 적는다. 새 도구 다운로드나 드라이버 변경은 하지 않는다. 별도 메모리 계측 실패를 VRAM 여유 입증으로 바꾸지 않는다.
- OOM, native error/timeout,90초 초과, source/config mismatch, 정리 실패는 즉시 실패·남은 호출 미실행이다. 새 neutral plan 전체 경과는2400초 이하로 고정하고 소유 process만 종료한다. 다른 모델 job이 active면 새 실행을 시작하지 않는다.
- 마지막 정상 종료 뒤 metadata-only health/model-identity 재시작을 한 번 확인하고 정리한다. 재시작 생성은0이다. 실제 timeout이 없으면 timeout 복구를 입증했다고 하지 않는다. timeout/취소/과도 메모리/바쁜 worker의 강제 경로는 별도 모델 없는 회귀와 이후 Java 운영 검증으로 남긴다.

새 자원4 + 후속 calibration16 + 선택된 validation12 = **새 native 상한32**, 닫힌 기존 자원2까지 이 계보 누적 상한34다. 원래 C2 전체상한30이 늘어났다는 protocol deviation을 숨기지 않는다. 추가 warmup·retry·자기검토·재작성·scoring용 서비스 생성은0이다. 개발 AI의 사전/사후 검토와 로컬 서비스 native 호출 수는 별개로 기록한다.

## 6. 구현할 최소 경계

기존 파일의4,096 상수를 바꾸는 수정은 금지한다. 새 명시적5,120 구현은 다음 모든 단계에서 같은 contract를 집행해야 한다.

1. tokenizer-only survey/prepare, source와 payload 보존 검사.
2. L0/C2 요청별 runtime의 준비 전후 입력 guard, native backend `_complete`의 token guard와 effective metadata. 기존 `meeting_gguf._complete`도4,096을 검사하므로 바깥 wrapper만 고쳐서는 실행되지 않는다.
3. 비교 runner의 prepare·dispatch payload·native row·완료 영수증과 전체 stop 조건.
4. audit의 plan/source 검증·raw output replay·token guard·calibration gate 재생. 기존 audit은 기존 runner/4,096에 묶여 있어 새 결과를 그대로 통과시킬 수 없다.

새 모듈/entrypoint로 추가하고 frozen catalog·prompt·grammar·mapper·review math를 import하여 재사용한다. 필요한 예산 경로만 명시적으로 새 구현에 연결한다. 전역 상수 monkeypatch, module import 바꿔치기, 기존 class를 잠시 패치한 후 되돌리기, CLI만 다른데 런타임이 같다고 주장하는 방식은 쓰지 않는다. 기존 source41/processing18이 새 plan에서도 모두 원래 hash인지 확인한다. 새 소스 동결에는 새 파일·테스트·이 설계·새 자원/실행 계약을 별도 바인딩한다.

상한을 올려도 artifact snapshot16MiB, native HTTP request512KiB, response2MiB를 유지한다. 전체 파일은 bound+1로 단일 snapshot 읽고 hash/parse가 같은 bytes를 사용하게 한다. 큰 파일·큰 grammar/request·원문 DTO 제한을 token budget으로 대체하지 않는다. 원본을 생략·절단·줄바꿈 정규화·요약하거나 응답 뒤 인용을 늘려서 byte/token 검사를 통과시키지 않는다.

모델 없는 핵심 검사는4,096에서 기존 동작 유지,4,097~5,120 새 두 arm 통과,5,121 양쪽 native dispatch0, false/non-int token 거절, cap 미만 prompt/grammar/mapper 완전 동등, DTO 생략필드/Unicode/전체 context byte 보존, raw response 재생, 파일/HTTP byte 경계, source drift, 같은 출력경로 재사용 거절, partial count 영수증, 검증 gate 전 본문 접근 차단이다. 실제 데이터 기대정답을 새 테스트 fixture로 옮기지 않는다. 부모/구현자는 generic synthetic 테스트만 쓴다.

## 7. 한 번의 실행과 제품 완성으로 이어지는 조건

순서는 실패 영수증 보존 → 이 상한/이탈 설계 commit → 새 코드·합성 회귀·source freeze → custodian의 전체 길이 조사/공식 준비 → 새 중립 plan commit과4회 → 두 split이 함께 바인딩된 새 실행 plan commit → calibration16회 → 독립 익명 판정 잠금/선택 → 통과할 때만 custodian validation12회다. 입력 조사가 실패하면 새 자원4회도 실행하지 않는다. 어느 단계의 실패도 앞선 산출물 삭제나 native 재시작으로 실행 재개하지 않는다.

품질 기준은 그대로 유지한다. Calibration은 C2 완전 적합8/8, L0실패→C2성공≥1, L0성공→C2실패0,16응답과 독립 판정 전부를 요구한다. 둘 다8/8이면 구조 개선 미관측이다. Validation은 후보12/12, 오류/근거 없는 추가사실/부적절 보류0 및 각 요청의 새 자원 계약을 요구한다. 선택 기준이 실패하면 더 큰 cap이나 prompt 수정으로 같은 항목을 다시 생성하지 않는다. Scorer는 둘이 서로 다르고 설계·구현·출처/문항 작성·사전검토 역할 전체를 제외한다. 이 역할도 제외한다.

통과한 경우 결과 명칭은 **동일 동결 문항을 사용한 길이 노출 후 자원 변경 비교/검증**이다. Python 측정은 Java 서비스 성능으로 부르지 않는다. 다음 작업은 또 다른 평가 자료 만들기가 아니라 기존 phase1 기능의 실제 Java/React 운영 검증과 후보를 명시적으로 선택하는 통합이다. 세션·ACL·리비전 교체/삭제·문서/회의 통합 검색·정확한 인용 좌표·편집/재시도 시 사용자 입력 보존·90초/120초 경계·busy/cancel/실패 응답·결정 이력/담당 작업 편집을 확인한 뒤 채택 여부를 기록한다. BM25/base 기본값이나 과거 실패 정책을 자동 변경하지 않는다.

후속이 통과해도 목적표집8/12와AI 작성/판정·인간0·공개문서 학습 가능성·길이 정보에 의한 계약 변경 한계를 남긴다. 통과 전에는 phase1/PR14가 미완료/draft다. 유료0, 공개 서비스 배포0, 새 과거-pool 접근0을 유지한다.
