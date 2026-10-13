# M5-B 자료 준비와 재현 경계

기준일: 2026-10-13. 이 단계는 **새 생성 정책 비교를 위한 자료·검사 코드 준비**다. 실제 생성은 0회이며 모델 품질 개선, Java Q&A 연결, 서비스 채택을 뜻하지 않는다. [사전등록](M5-CALIBRATION-PLAN.md)의 최대 72회 비교는 별도 실행기·잠금·결과 검토 절차를 완성하고 동결한 뒤 수행한다. 최종 retrieval test는 계속 잠겨 있고 사용자 검수는 0이다.

## 자료를 먼저 분리한 이유

기존 생성 smoke에서 정확한 인용이 있어도 복합 질문 일부가 빠지거나 충돌·모호성을 무시했다. 이를 같은 질문에서 반복 수정하면 이미 본 질문에만 맞춘 결과가 된다. 새 가상 업무 사실 12계열을 질문 작성 전에 고정하고 SHA 순서로 조정용 6계열, 검증용 6계열에 배정했다. 계열당 4문항이므로 양쪽 각각 24문항이며, 같은 사실의 변형은 한 계열에 남긴다. 세 정책 예시는 별도 3계열에서 작성했다.

각 split은 단일 문서 답변 6개, 두 문서 답변 6개, 보류 12개다. 보류 이유는 근거 부족·해결되지 않은 충돌·대상 모호 각각 4개다. 교차언어와 문서 내 지시문 사례도 각각 4개씩 포함한다. 이 작은 합성 분포는 실제 조직 문서의 분포나 실사용 질문의 난도를 대표하지 않는다. 사용자 검수나 현실 문서의 추가 검증을 대신하지 않는다.

## 준비 중 발견한 결함

- registry 선동결은 `2de1487`, 비교 계획은 `01553d7`이다. Windows 준비 사본의 CRLF를 저장소 규칙인 LF로 정규화한 뒤 Git blob과 같은 hash를 질문에 연결했다. 배정이나 사실을 바꾼 것은 아니다.
- 첫 calibration·예시 초안은 `6be95d2`에 보존했다. 별도 AI 검토에서 공격 문구 네 개의 노골적인 공통 표지, 두 calibration 충돌 항목의 비배타적 규칙, 예시 한 개의 불명확한 배타 조건을 발견했다. 해당 7항목만 수정하고 출처 hash·span·인용과 의미를 다시 검사했다. 예시의 영어 `only` 범위도 한 차례 더 명확히 했다. 모두 모델 출력이 없는 사전 자료 검토다.
- 최초 tokenizer 감사 장치는 실제 import와 단순 `find_spec` 탐색을 함께 막아 실패했다. 이를 모델·토큰 한도 실패로 세지 않는다. 실제 import 이벤트와 가중치 열기만 금지하는 감사로 바꾼 새 프로세스에서 calibration 초안 양쪽 24입력 검사가 통과했고 Torch도 import되지 않았다. 최종 전체 자료 검사는 아래 준비 영수증을 따른다.

고정 자료의 원문 `review_status`는 작성 당시 pending을 유지한다. 완료한 자동 검사·별도 AI 검토는 hash에 연결된 외부 영수증으로 기록한다. AI 작성자와 다른 역할이 검토했지만 조직적으로 독립된 평가기관이나 사람의 판정은 아니다.

## 구현과 재현

새 모듈은 분할·순서·배정·문항 수, 실제 원문 SHA와 Unicode codepoint 구간, 두 문서의 독립적인 필수 사실, 보류 oracle, 자료 중복과 항목별 검토 영수증을 검사한다. 정확한 인용이나 파일 hash만으로 의미 지지를 판정하지 않는다. 문장 유사도는 추가 AI 검토를 위한 경고이며 의미상 독립성의 증명이 아니다.

기존 system과 실제 target payload는 byte 단위로 유지한다. 예시 세 개의 user/assistant 쌍만 앞에 삽입하며, 예시의 모델 입력에서는 출처 식별용 metadata를 생략한다. 저장 자료에는 출처·span이 모두 남는다. 실제 target의 metadata는 그대로다. 모든 예시는 같은 순서로 사용하고 출력 JSON을 수선하지 않는다.

모델 없는 검사와 동결 파일 확인:

```powershell
uv run --locked --no-sync python -m scripts.prepare_generation_calibration --require-reviewed --review data/evaluation/reviews/m5b-calibration-review-v1.json --review data/evaluation/reviews/m5b-validation-review-v1.json --output .local/m5b-structure-check.json
uv run --locked --no-sync python -m scripts.prepare_generation_calibration --verify-freeze data/evaluation/m5b-preparation-freeze-v1.json
```

첫 명령은 tokenizer를 지정하지 않으므로 `prompt_budget_status=not_run`, `generation_ready=false`가 정상이다. `--require-reviewed`는 구조·중복·AI 검토가 미완료면 실패한다. 두 번째 명령은 저장한 준비 파일들의 hash를 재검사하며 토큰을 새로 계산하거나 모델을 호출하지 않는다. CI도 이 두 검사를 수행한다.

이미 받은 고정 snapshot에서 실제 입력 길이를 다시 확인하려면 별도 로컬 출력 경로를 쓴다. 이는 모델 추론 재실행이 아니라 tokenizer-only 검사다.

```powershell
uv run --locked --group retrieval --no-sync python -m scripts.prepare_generation_calibration --snapshot models/generation-m5-qwen3-1.7b --require-reviewed --review data/evaluation/reviews/m5b-calibration-review-v1.json --review data/evaluation/reviews/m5b-validation-review-v1.json --output .local/m5b-tokenizer-check.json
```

고정 manifest의 tokenizer 파일 네 개를 검증하고 그 파일들만 임시 디렉터리에서 읽는다. 추가 `chat_template.jinja` 등의 미검증 로컬 덮어쓰기를 받지 않는다. 실제 runtime과 같은 chat template와 `add_special_tokens=False`, `truncation=False`로 센다. 전체 prompt가 1,536 tokens를 넘으면 실패하며 선택적으로 근거를 자르지 않는다. 외부 다운로드·가중치 로드·GPU를 실행하지 않는다. 활성 추론 중 의존성을 동기화하지 않는다.

Validation의 질문·정답을 부모 통합자나 prompt 작성자에게 출력하지 않는다. 프로그램은 내용을 읽어 검사하되 ID·hash·count·token 수만 보고한다. 별도 검토자는 정책 예시를 고정한 뒤 검증 자료를 읽으며 이후 prompt 튜닝 역할을 맡지 않는다. 이는 같은 공개 저장소 안의 절차적 격리이며 물리적 접근 통제를 보장하지 않는다.

## 현재 완료 증거와 다음 단계

최종 자료는 24/24/3문항·38/38/5원문이다. 별도 AI의 항목별 검토 27+24개가 실제 파일 hash와 연결되며 현재 blocker는 0이다. 수정한 calibration과 예시를 `f7e9692`에서 먼저 고정한 뒤 검토자가 validation을 읽었다. Validation 초안 `bdeffac`는 수정 요청 없이 통과했다. 계열 간 정규화한 정확 중복과 0.85 문자열 유사도 경고는 각각 0개이며, 공유된 간단한 질문 형식·저술 스타일과 현실 문서 범위의 한계는 남는다.

실제 고정 tokenizer 검사에서는 baseline·few-shot 각각 48개, 총 96개 prompt가 통과했다. 최대 입력은 **753/1,039 tokens**이고 한도는 1,536이다. 실제 Torch import와 모델 파일 열기, 이전 평가 자료 접근을 막은 새 프로세스에서 실행했고 Torch는 import되지 않았다. 준비 report SHA는 `95cdd2f70139f0bb08f331909aedc97a67e1debc17fa790c9ff42836f04dc5ad`다. [동결 manifest](../data/evaluation/m5b-preparation-freeze-v1.json)는 자료·리뷰·report·계획·구현·검사·기존 prompt/runtime·model manifest·의존성 파일 **18개**를 묶는다. 파일 목록 자체는 사람이 읽을 수 있고, 검사기는 지정된 목록의 hash를 확인한다. 범용 검사기가 필수 목록을 자동으로 완성해 주는 것은 아니다.

로컬 Python 711개, Java 82개, Playwright 22개, 타입 검사·production build·Ruff가 통과했다. 새 준비 검사 25개에는 분할·원문 drift, 유효하지 않은 보류 oracle, 두 사실이 같은 문서만 인용하는 경우, 중복, prompt 순서·길이, 가짜 검수 상태와 손상된 검토·동결 바인딩의 거절을 포함한다. 별도 코드 검토도 같은 25개를 확인했고 준비 범위의 blocker는 없었다. 기존 Python deprecation warning1개는 남는다. CI·Git 통합은 로컬 검증과 별도로 확인한다.

최종 자료·검토·token 검사·CI 상태는 [STATUS](STATUS.md)와 [준비 영수증](../experiments/results/m5b-preparation-v1.json)에 연결한다. 저장한 입력 해시는 원문·예시·표현 변경을 탐지하는 데 사용한다. 단위 검사 통과를 모델의 답변 정확성으로 바꾸어 말하지 않는다.

다음은 최대 48회 calibration 실행을 위한 신규 실행기, 엄격한 형식/인용 판정 분리, 익명화한 의미 검토와 사전 선택 규칙의 구현이다. 선택을 고정한 뒤에만 선택 정책의 validation 24회를 한 번 수행한다. 모델 출력으로 자료 정답을 고치거나 validation에 두 정책을 추가 비교하지 않는다. 그 후에도 실제 문서·권한·수정·삭제·Java 연결 및 현실 질문 품질 검증이 남는다. 유료 API·GPU 임대·클라우드·서비스 외부 배포는 하지 않았다.
