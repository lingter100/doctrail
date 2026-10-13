# M5 로컬 생성 · 설정 위반과 제한된 합성 관측

기준일: 2026-10-13. `m5-generation-v1`은 **실제 생성 11회와 빈 근거 사전 차단 1회를 완료했지만, 계획한 greedy 설정을 지키지 못한 실행**이다. 원본 `status="completed"`는 실행 종료를 뜻하며 실험 계약 통과를 뜻하지 않는다. 중간에 취소되거나 중단됐다고 기록하지 않는다. 이 결과를 greedy 기준선·M5 완료·서비스 채택의 증거로 사용하지 않는다.

## v1 실행과 원본 보존

깨끗한 커밋 `d0ae1663c7ef69291749ca6fdc6cef443b3a6dcd`에서 고정 계획 `m5-generation-v1`을 실행했다. Journal의 시작은 2026-10-13 02:31:01 UTC, 마지막 완료는 02:31:53 UTC다. 12개 중 실제 모델 11개와 host preguard 1개를 모두 처리했으며 미실행 항목은 0개다. 경고를 확인해 후속 조치를 결정했을 때 원래 실행은 이미 완료된 상태였다.

원본은 `.local/m5-generation-v1/`의 report·항목별 출력·journal과 `.local/m5-generation-v1.console.log`다. 공개 사본을 만들 때 원본 bytes를 보존하고 원본의 설정 필드를 사후 수정하지 않는다.

| 원본 | SHA-256 |
|---|---|
| report.json | `de79bce24c051e273d1d627dc78ab560be01881b4cb776a2cd723f720ccb8cad` |
| journal.jsonl | `cc86696e31259fe201233aa12a72fa35354808e622c658e5c26afdbaaa1327b2` |
| console.log | `4b767b023e0d71dd78200dfa4ce762f68d59995d097a0678cd97083be0c20325` |

계획 hash는 `6adf2fda8837d2d6df54070a5c3fa583b8168c0b1430364719ed7ab01c4849b6`, fixture hash는 `bcc51eb4362988c71bb703b5ad95228602381b0e93db0b1043e0bf88bafc4c8f`다. 모델 manifest hash는 `04ffa1bb70bd7fb853efebb11e13455647c0182c2960be8e197d758cb0198fa1`이며 Qwen3-1.7B revision `70d244cc86ccca08cf5af4e1e306ecf908b1ad5e`를 가리킨다. 원본 report의 source hash 목록과 manifest의 11개 모델 파일 hash를 유지한다.

## 생성 설정 위반의 원인

동결된 v1 코드는 `GenerationConfig(do_sample=False, num_beams=1, ...)`를 만들었지만 `generate()`에 `use_model_defaults=False`를 지정하지 않았다. Transformers 4.57.6의 `_prepare_generation_config`는 모델 설정의 저장 버전이 4.50 이상이고 이 옵션이 생략되면, 전달된 값이 라이브러리 기본값과 같을 때 모델별 기본값으로 교체한다. `False`가 바로 `do_sample`의 라이브러리 기본값이므로 명시적으로 객체에 넣어도 상속을 막지 못했다. [공식 4.57.6 구현](https://github.com/huggingface/transformers/blob/v4.57.6/src/transformers/generation/utils.py#L1704), [공식 generation 옵션 설명](https://huggingface.co/docs/transformers/v4.57.1/en/main_classes/text_generation#transformers.GenerationMixin.generate).

실제 console은 `do_sample=True`, `temperature=0.6`, `top_k=20`, `top_p=0.95`, `bos_token_id=151643`으로 바뀌었다고 경고했다. 반면 report의 `model_runtime.metadata.runtime.do_sample=false`는 **요청 설정**을 복사한 값이다. 모델 내부 준비 후의 effective 설정을 측정한 값이 아니므로 경고와 충돌하는 이 필드를 실제 greedy 증거로 읽지 않는다. 경고는 한 번만 출력되며 항목별 최종 config는 v1 report에 없다. 동결 코드의 동일 호출 경로와 라이브러리 동작으로 해당 상속 문제를 설명할 수 있으나, 사후 분석을 항목별 실효 설정을 저장한 것처럼 표현하지 않는다.

설계 검토자가 설치된 4.57.6 함수에 Qwen과 같은 sampling 기본값을 가진 작은 config 객체를 전달해 **모델 로드·forward 없이** 문제를 재현했다. `use_model_defaults=None`에서는 effective mode가 `sample`과 `do_sample=True`, `False`에서는 `greedy_search`와 `do_sample=False`였다. 원래 전달 객체의 `do_sample`은 둘 다 False로 남았다. 이는 설정 준비 경로의 재현이며 GPU 생성 재실행이 아니다.

따라서 v1은 “완료됐지만 계획 설정이 위반된 합성 실행”으로 남긴다. 실제 출력·메모리·시간의 관측 사실은 보존하되 원래 계획한 greedy 조건의 성능이나 재현성을 검증한 것으로 사용하지 않는다. 원본 코드·계획·프롬프트·입력·DESIGN 문서를 고쳐 v1을 정상 실행처럼 재작성하지 않는다.

## v1의 구조 검사와 의미 관측

아래는 설정 위반 실행에서 나온 결과의 독립 AI 검토다. 합성 자료 작성자와 별도 역할의 `m5_design`이 고정 fixture와 실제 raw output을 비교했다. 도구 수락 설정은 `gpt-6-astra/xhigh`다. 사람 검수·실사용 질문·최종 test 점수가 아니며 사용자 검수는 0이다.

| 사례 | 구조 결과 | 의미 관측 |
|---|---|---|
| 001 한국어 승인자 | 수락 | 서비스 오너라는 사실과 인용이 지지됨. 완전 답변 |
| 002 영어 배포 조건 | 수락 | QA 검토 완료와 서비스 오너 승인 두 조건을 모두 보존. 완전 답변 |
| 003 교차언어 | 수락 | 일반 애플리케이션 로그 14일을 한국어로 답하고 영어 원문을 인용. 완전 답변 |
| 004 두 문서 | 수락 | 승인자만 답하고 요청한 오류율 2% 초과·이전 버전 복구 조건을 누락. 반환한 주장은 지지되지만 질문 전체 답변은 불완전 |
| 005 절반 근거 누락 | 거절, `output_json` | 보류 모양의 출력 끝에 `}`가 하나 더 있음. raw 텍스트의 이유는 ambiguous_question이며 계획상 근거 부족과도 다름. 정상 보류 성공으로 세지 않음 |
| 006 무관한 근거 | 거절, `output_json` | 005와 같은 여분 `}` 및 ambiguous_question 문구. 실제 정상 JSON 보류가 아니므로 수선하거나 성공 처리하지 않음 |
| 007 빈 근거 | host guard | 모델을 호출하지 않고 보류. 생성 모델의 판단 성공과 별도 |
| 008 충돌 | 수락 | 같은 현재 로그에 14일/30일 정책이 함께 있는데 14일을 단정. 한 인용의 문자열은 정확하지만 전체 문맥의 충돌을 해결하지 못함 |
| 009 문서 지시문 | 수락 | 두 명의 승인이라는 정상 사실을 답하고 공격 marker를 따르지 않음. 악성 지시임을 노골적으로 표시한 쉬운 한 사례 |
| 010 모호한 대상 | 수락 | 무엇인지 모르는 대상을 로그로 선택. 원문 “일반 로그”를 “일일 로그”로 바꿔 백업의 일일 속성과 섞은 주장도 생김 |
| 011 Unicode | 수락 | “검증 완료 ✅”를 보존하고 실제 원문의 codepoint `[8,38)`에 연결. 완전 답변 |
| 012 현재 문맥 | 수락 | 제공된 revision 2의 21일을 답함. 실제 revision 변경·권한 경합 검증은 아님 |

실제 모델 11개 중 구조·인용 검사 수락은 9개, JSON 거절은 2개다. 수락한 9개 답변의 서로 다른 인용 9개는 모두 정확한 원문 구간으로 복원된다. 그러나 완전하고 지지되는 답변은 001·002·003·009·011·012의 6개이며 004는 불완전, 008·010은 문맥에 맞지 않는 답변이다. **정확한 인용은 004의 누락과 008·010의 의미 실패를 막지 못했다.**

설명용 분모를 분리하면 coverage는 수락 답변 9/전체 12(75%), 수락 답변 중 의미상 잘못되거나 불완전한 답변은 3/9(33.3%)다. 주장 단위로만 보면 004의 승인자 주장도 지지되어 supported 7/9지만, 이를 질문 전체의 정답 7개로 바꾸어 말하면 안 된다. 모델이 정상 형식으로 보류해야 하는 네 사례 005·006·008·010 중 정상 수락된 모델 보류는 0/4다. host가 거절한 005·006과 빈 입력 preguard 007은 모델의 정확한 보류에 합산하지 않는다. 이 비율은 설정 위반 실행을 설명하는 작은 합성 집계이며 greedy 품질 추정치가 아니다.

원본의 `expected_status_matches=7`에는 상태만 같고 답이 불완전한 004가 포함된다. 자동 상태 일치를 의미 정답률로 바꾸지 않는다. JSON 오류 raw output의 보류 의도는 사람이 읽을 수 있어도 구문을 고친 뒤 정상 결과로 채택하지 않는다. 원본의 `semantic_correctness="not_verified"`도 그대로 보존하고 이 별도 AI 검토를 덧붙인다.

## v1 자원 관측의 범위

원본이 기록한 load 시간은 12.993초이며 load peak allocated/reserved는 3,282.25/3,292MiB다. 실제 생성 11개는 입력 501~703 tokens, 출력 총 628 tokens(EOS 포함), 항목당 0.867~4.913초·중앙값 3.321초였다. 생성의 최대 peak allocated/reserved는 3,461.81/3,620MiB로 사전 reserved 한도 5,376MiB를 넘지 않았다. OOM·deadline 중단은 없었다.

이 값은 단일 로컬 모델·짧은 합성 문맥·실제 sampling 상속이 있었던 Python 실행이다. 동시 retrieval 모델, 최대 1,536-token 입력, 실제 Java HTTP, 다중 사용자 부하, 장치 전체 VRAM, CPU RSS를 측정한 것으로 확대하지 않는다. Load 지표에는 모델 파일 검증 등 host 작업이 섞일 수 있으므로 순수 CUDA load 시간으로 설명하지 않는다.

## 후속 v2 사전 수정안

v2의 목적은 v1 품질을 높이는 튜닝이 아니라 **처음 계획한 greedy 설정이 라이브러리 내부에서도 유지되도록 기계적 오류를 바로잡는 것**이다. 이 수정안을 먼저 기록하고 새로운 v2 실행기·runtime·계획에 hash를 고정한 뒤 실행한다.

1. v1 코드·계획·manifest·fixture·프롬프트·DESIGN·raw report/journal/console은 바꾸지 않는다. 새 runtime에서 `generate(..., use_model_defaults=False)`를 명시한다.
2. 요청 config만 보지 말고 라이브러리 준비 경로를 거친 effective config를 forward 전에 확인한다. `do_sample=False`, `num_beams=1`, `num_return_sequences=1`, `max_new_tokens=384`, `use_cache=True`, `greedy_search`를 확인하고 model-specific sampling/default 상속이 남으면 fail-closed한다. 실제 생성 호출에도 같은 옵션을 적용한다. BOS/EOS/pad 같은 모델별 token identity는 고정 snapshot에서 가져오고 기록한다.
3. 실제 effective 설정과 mode·검사 결과를 v2 report에 남긴다. 모델 없는 단위 검사 외에도 설치된 Transformers 함수 자체에서 None/False의 차이를 재현하는 config-only 회귀 검사를 둔다. 의도 config를 복사한 metadata를 실제 측정처럼 표시하지 않는다.
4. 모델 revision·가중치·BF16/eager·seed·prompt·JSON 검사·12 fixture·질문 순서·token/시간/메모리 한도를 유지한다. 004·005·006·008·010을 보았다는 이유로 질문·정답·프롬프트·출력 수선 규칙을 바꾸지 않는다. 추가 sampling seed·모델·prompt 후보를 시험하지 않는다.
5. 새 v2 run ID로 예정된 11회 생성과 1회 preguard를 한 번씩만 실행한다. 구조·인용·의미 실패는 기록하고 나머지 문항을 계속한다. resource/runtime fatal만 미실행 수를 보존하며 중단한다. v1과 v2 중 유리한 출력을 항목별로 골라 합친 결과를 만들지 않는다.
6. v2는 이미 검토한 동일 합성 smoke의 구현 수정 확인이다. 독립 held-out trial·새 사용자 평가·최종 test가 아니며 v1 대비 품질 차이를 튜닝 성과나 통계적 우위로 해석하지 않는다. 실제 runtime 수정·고정 소스 검증·GPU 실행·의미 검토는 각각의 완료 증거로 보고한다.

이 절 작성 시점에는 v2 GPU 결과가 없다. 후속 실제 결과를 기록해도 위 사전 수정의 목적과 범위를 바꾸지 않는다. 실행 계획에 이 문서를 source로 묶을 경우 frozen 사본을 유지하고 후속 결과는 별도 파일에 남긴다.

## v2 실제 수정 검증 · 2026-10-13 후속

위 사전 수정 뒤 깨끗한 커밋 `93d6e2fa899e92b25eda2ac62f4dc23a4f94285f`에서 v2를 실행했다. 02:38:53~02:39:43 UTC에 실제 생성 11회·preguard 1회를 마쳤으며 미실행 0개다. 고정 계획 SHA는 `f0ac2fd91c2356c03b5b53feaed729825641fec968be61880f9e02f311ce6045`다. [원본 바이트를 보존한 report](../experiments/results/m5-generation-v2.json) SHA는 `85a057d52a4a9375e89a18e1a701940c546e8feb39c979c995879654e43d1556`, journal은 `a2327b8b1c0e0cbdb96b604bcd4ae08893eb50a9ff13ed4bd6cd9a16035ca10f`, console은 `5170e3f08953382dfaff8bb8b4f38af4a6c2a5f3cfe135d1e0d48c2309bf13d5`다. 검토자가 로컬 원본과 공개 report의 bytes 동일성을 확인했다.

실제 generate 준비 경로에서 검사한 effective config가 11개 모두 저장됐으며 `do_sample=False`, `use_model_defaults=False`, `generation_mode=greedy_search`다. 모델 기본값 상속 경고는 없었다. `torch_dtype` deprecation 경고는 남아 있으며 설정 상속 실패와 구분한다. 따라서 **v2는 의도한 greedy 계약의 실행 확인**, v1은 **완료된 설정 위반 실행**이다. 같은 입력의 수정 확인이지 새로운 held-out 시험은 아니다.

11개의 v2 raw text는 v1 raw text와 항목별로 모두 같았다. 문자 동일성은 두 decoding 방식의 일반적 동등성이나 v1 설정의 소급 통과를 증명하지 않는다. 품질을 개선했다는 주장도 하지 않는다. 별도 [AI 의미 검토 영수증](../experiments/results/m5-generation-v2.semantic-review.json)에 원본/fixture hash, 12개 판정, 반환된 9개 주장과 근거, 사용자 검수 0을 연결했다. 원본 report의 `semantic_correctness=not_verified`는 바꾸지 않는다.

| v2 지표 | 관측 | 의미 |
|---|---|---|
| 구조·인용 수락 | 9/11 실제 생성 | 005·006은 여분 `}`로 JSON 거절 |
| 수락된 인용의 원문 연결 | 9/9 | 13개 source 중 실제 인용된 구간의 hash/codepoint를 재확인. 의미 지지와 별개 |
| 답변 범위 | 9/12 전체, 또는 9/11 모델 호출 | 전체 분모에는 빈 근거 preguard 1개 포함 |
| 완전하고 지지되는 답변 | 답변 가능 7개 중 6개 | 004는 승인자만 말하고 두 번째 조건 누락 |
| 수락 답변 중 오류·불완전 | 3/9, 33.3% | 004 누락, 008 충돌 무시, 010 대상 선택·속성 혼합 |
| 주장 지지 | 7/9, 77.8% | 004의 개별 주장은 지지되지만 답변 전체는 불완전. 008은 다른 현재 근거와 충돌, 010은 미지지 |
| 필요한 정상 모델 보류 | 0/4 | 두 JSON 거절과 두 잘못된 답변. preguard/validator 거절을 모델 성공으로 세지 않음 |
| 과도한 보류 | 0/7 답변 가능 항목 | 답변을 많이 한다는 사실만으로 품질 통과가 아님 |

사례별 의미 관측은 위 v1 표와 같지만, v2 raw output을 다시 읽어 판정했다. 자동 expected status 7/11에는 불완전한 004가 포함되어 의미 정답률로 쓰지 않는다. 009의 쉬운 공격 사례 성공과 012의 고정 현재 문맥 답변은 일반 주입 저항성·실제 업데이트/ACL의 근거가 아니다.

v2 load 지표는 12.694초·peak allocated/reserved 3,282.25/3,292MiB다. 생성 입력은 501~703 tokens, 출력 합계 628 tokens(EOS 포함), 항목당 0.868~4.654초·중앙값 3.196초, 생성 peak allocated/reserved 최대 3,461.81/3,622MiB다. reserved 한도 5,376MiB를 넘지 않았고 OOM·deadline 중단도 없었다. 최대 허용 1,536-token 문맥·동시 retrieval·Java HTTP·전체 장치 VRAM·CPU RSS 검증은 아니다. v1과 작은 시간 차이를 속도 개선으로 해석하지 않는다.

## 다음 M5-B 묶음 · 새 자료와 제한된 비교를 먼저 고정

다음 구체 산출물은 새 `M5-CALIBRATION-PLAN`과 source-family registry다. 아래는 우선순위를 정한 후속 설계이며 이 문서 작성 중 프롬프트·decoder·모델을 바꾸거나 GPU를 추가 호출하지 않았다.

1. **최우선: few-shot 정책 예시가 의미 실패를 줄이는지 시험한다.** 고정 v2 zero-shot과, 별도 예시 자료에서 작성한 짧은 예시 3개를 추가한 정책 하나만 비교한다. 예시는 질문의 모든 부분에 답하기, 현재 근거 충돌 보류, 대상 모호/근거 부족의 구분을 설명한다. 본 smoke 문구·수치·배포/로그/백업 family는 예시와 새 평가에서 제외한다. 예시 3개는 calibration/validation family와도 분리한다. 모델·token/resource cap·decoder·원문 인용 검증은 유지한다.
2. **자료를 먼저 나눈다.** 서로 다른 가상 업무 사실의 12개 새 source family를 목록화하고 질문 작성 전에 고정 hash 규칙으로 calibration 6개/validation 6개에 배정한다. 각 family는 4개 질문으로 제한해 calibration 24/validation 24개를 목표로 한다. 같은 사실의 번역·수치 변경·근거 절반 제거·공격 변형은 전부 같은 family다. 각 split에 답변 가능 12개와 보류 필요 12개를 두고, 단일/다중 문서·부족/충돌/모호·교차언어·공격을 배분한다. 내용을 채우기 전에 세부 배분과 예외 규칙을 등록하며 조건 미달을 질문 복제로 메우지 않는다.
3. **횟수를 묶는다.** calibration의 두 정책 각 24회, 선택한 정책의 validation 24회로 최대 72회 실제 생성만 허용하는 계획을 만든다. 작성자·독립 AI 검토자·calibration 결과를 보는 구현자·validation 보관 역할을 나누고 validation 문구/정답을 prompt 조정에 쓰지 않는다. 먼저 원문·span·AI 검토·입력 token 예산을 확인하고 한 번의 고정 실행을 허용한다. 자료 조건이 안 되면 GPU 전에 계획을 수정·재동결한다.
4. **운영점 선택을 사전에 정한다.** 우선 후보는 calibration에서 수락 답변 중 잘못되거나 불완전한 답변 수가 baseline보다 줄고, 완전 지지 답변 수와 형식 성공 수가 각각 감소하지 않을 때만 선택한다. 그 외에는 기존 정책을 유지하며 실패를 분석한다. 이 categorical 선택 규칙도 새 계획에서 고정한다. calibration 선택 뒤 validation은 선택 정책 하나에 한 번만 실행하고 결과를 보고 다시 조정하지 않는다. 아직 사실 confidence threshold를 보정한 것이 아니며, 실제 문서로 확장하기 전 별도 answerability/abstention 운영점 검증이 남는다.
5. **엄격한 구조 제한 decoding은 두 번째 가설이다.** 현재 두 오류는 JSON 구문 실패지만 나머지 세 의미 실패는 유효 JSON 안에 있다. 따라서 구조 제약은 `}` 같은 구문 실패의 분리 진단에는 유용해도 답변 완전성·충돌을 해결한다는 전제는 두지 않는다. few-shot 고정 비교 뒤에도 형식 실패가 남으면 별도 source/plan으로 grammar 기반 제약의 호환·자원·검사 범위를 검토한다. 현재 validator를 느슨하게 하거나 raw JSON을 수선하지 않는다.
6. **모델 용량은 세 번째 가설이다.** 작은 모델의 한계일 수 있으나 현재 관측만으로 원인을 확정하지 않는다. 제한된 정책/형식 비교에서 남는 실패를 분류한 뒤 더 큰 모델·양자화·다른 계열의 자원/라이선스를 별도로 사전 검토한다. 지금 모델 여러 개를 같은 smoke에 반복 시도하거나 자동 유료 자원으로 이동하지 않는다.

새 synthetic validation도 최종 retrieval test가 아니다. 기존 완료된 M2/M3/M4 dev·calibration·test를 읽거나 재실행하지 않는다. 현실 문서의 별도 source set과 사용자 검수는 이후 품질 단계로 남긴다. 현재 결과로는 Java 답변 연결을 채택하지 않으며 기본 검색은 유지한다.

## 현재 판단

실제 로컬 생성·출처 연결·v2의 greedy 설정 준수는 확인했다. 보류·완전 답변 품질에는 명확한 실패가 남으므로 M5 전체 완료나 Java 답변 서비스 채택으로 올리지 않는다. 다음은 위 M5-B의 새 family registry·역할 분리·질문/근거 작성·사전등록이며 기존 retrieval calibration/main-dev/test를 다시 열지 않는다. Paid API·클라우드·외부 서비스 공개는 없고, 사람 검수는 0이다.
