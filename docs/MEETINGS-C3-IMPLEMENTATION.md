# C3 요구사항 계획 후보의 구현과 검증 범위

이 구현은 [사전 설계](MEETINGS-C3-PLAN.md)의 실험 후보이며 서비스 기본 경로를 바꾸지 않는다. 같은 무료 로컬 모델이 먼저 질문의 요구사항과 근거를 계획하고, 모든 요구가 지원된 경우에만 두 번째 호출에서 자연어로 답한다. 일부 필수 정보가 없거나 불확실하면 전체 질문을 보류한다.

## 구현

- `meeting_answer_requirements.py`: 요구사항 1~6개, 순차 ID, 항목별 유효 근거 최대4개, 두 단계 prompt/grammar, 누락·중복 없는 답변 슬롯과 서버의 정확한 원문 인용 연결.
- `meeting_requirements_runtime.py`: 실제 생성된 계획에 따른 두 번째 입력 길이 검사, 두 단계에 공유되는90초, 단계당5,120입력/384출력, 최대2회, 안전한 오류 및 요청별 실행 기록. 기존 pinned GGUF 전송과 신원·설정·nonthinking 검사를 재사용한다.
- 명시적인 한국어/영어 인자를 오프라인 평가에서 지원한다. 기본 요청 언어 추정과 언어 guard는 문자 종류 기반이며 완전한 언어 판별기가 아니다.
- `completion_attempts`는 wrapper 진입 횟수다. 실제 native HTTP dispatch 횟수는 후속 실행기가 별도 영수증으로 기록해야 한다. 요구 계획 원문은 운영 telemetry에 넣지 않는다.

요구사항을 모델이 빠뜨리거나 근거를 잘못 판정할 위험은 남는다. 올바른 JSON, 정확한 인용 좌표, 슬롯 완전성이 답변의 의미 정확성을 보증하지 않는다. 실제 모델 품질 검증·Java/React 연결·서비스 채택은 아직 하지 않았다.

## 확인한 문제와 수정

독립 코드 검토가 연속 요청의 실행 기록 오염을 발견했다. 요청 초기화 전에 모델 정보를 복사하면 이전 요청의 grammar hash와 template 검증 상태가 다음 빈 요청에도 남을 수 있었다. 초기화 이후 정보를 기록하도록 순서를 고쳤다. 두 번의 모의 HTTP 생성 뒤 빈 요청을 보내 추가 호출0과 grammar 없음/template 미검증을 확인하는 회귀검사를 추가했다.

전체 Python 첫 실행은 기존 C0 합성 실행기 검사에서 `PermissionError`로 실패했다. 첫 정상 결과 뒤 중단된 원본 보고서를 보존했고, 사후 검사에서 계획·소스·모든 입력 hash는 같았다. 보고서의 `sources_unchanged=false`는 완료 경로에 도달하지 못한 초기 상태이며 실제 파일 변경의 증거가 아니다. 기록에는 상세 시스템 호출이 없어 파일 접근 오류의 정확한 발생 위치와 원인은 확정하지 않는다. 기존 동결 실행기와 검사를 변경하지 않았고 해당 파일의40개 합성 검사는 별도 재확인에서 통과했다.

최종 수량·명령·소스 바인딩은 `experiments/results/meetings-c3-implementation-v1/verification.json`과 [STATUS](STATUS.md)에 기록한다. 첫 실패를 이후 성공으로 덮어쓰지 않는다. 기존 C2 소스72·비교41·처리18 바인딩은 모두 보존했다. 합성 검사는 실제 모델 추론이나 사용자 검수가 아니다.

## 입력 준비와 독립 판정 도구

새 `prepare_meeting_requirements_inputs.py`는 원문에서 전체 문서/청크를 다시 구성하고 원본 Python 처리 영수증과 Java 처리 대조 영수증을 연결한다. 완료 표시만 읽지 않고 원문·코드·문서·좌표의 hash와 수량을 확인한다. Source freeze는 `manifest`, `inventory`, `processing_receipt`, `prereview`, `java_parity`의 5역할과 manifest에 선언된 raw 파일만 포함한다. 각 source의 `adoption_author_role` 및 합성 원문의 `synthetic_provenance.author_role`이 사전검토의 작성자 목록과 일치해야 한다. 이는 기록의 일관성 검사이며 AI 검토를 사람 검수로 바꾸지 않는다.

자료 경로는 해당 C3 split의 새 디렉터리로 제한한다. 다른 split·이전 실험·등록되지 않은 추가 파일은 본문을 열기 전에 거절한다. 원래 요청의 필드 생략/null/Unicode/전체 청크를 유지하고 공식 tokenizer는 다운로드 없이 첫 단계만 센다. 모든 6/8개를 조사해 실패와 미측정도 분모에 남기며, 두 번째 입력은 `dynamic_unmeasured`로 기록한다. 새 출력 디렉터리는 한 번만 사용할 수 있다.

독립 코드 검토는 `code_freeze` 인자만 위 경로 검사에서 빠진 결함을 새 합성 파일로 재현했다. 계약을 거절하더라도 먼저 반대 split 파일을 읽으면 격리가 깨진다. 따라서 전체 코드 목록의 경로도 `data/evaluation/meetings-c3-toolchain-source-freeze-v1.json`으로 고정하고 어떤 snapshot이나 출력 생성보다 먼저 검사한다. 이 경로를 등록한 것이 실제 전체 freeze 생성이나 자료 작성 허용을 뜻하지 않는다.

새 `meeting_requirements_review.py`는 C3 구성과 기존과 동일한 답변 점수 계산, 판정자의 실제 노출, 답변 잠금 뒤 계획 진단을 검증한다. 근거 없이 충분히 지지된다고 쓰거나 요구사항과 필수 사실의 연결을 양쪽에 다르게 적으면 거절한다. 계획 진단은 답변 점수를 다시 고르는 절차가 아니다. 최종 답변 잠금·계획 공개 순서는 다음 audit 도구에서 연결한다.

두 도구와 대응 검사의 합성 검증은 [STATUS](STATUS.md)에 기록한다. 실제 tokenizer/모델·새 원문/문항 검증은 아직 하지 않았다. 준비 코드가 참조하는 전체 toolchain은 뒤의 실행/audit 파일까지 있어야 성립하므로, 지금 이 부분 구현만으로 자료 작성이나 추론을 시작할 수 없다.

## 재현과 다음 단계

```powershell
uv run --locked --no-sync ruff check src tests scripts
uv run --locked --no-sync pytest -q tests/test_meeting_answer_requirements.py tests/test_meeting_requirements_runtime.py
uv run --locked --no-sync pytest -q tests/test_meeting_requirements_review.py tests/test_prepare_meeting_requirements_inputs.py
uv run --locked --no-sync pytest -q
```

모델·질문을 실행하는 명령은 아직 제공하지 않는다. 다음은 새 단일 후보의 중립 자원 검사·품질 실행·판정 잠금 도구를 구현하고 전체 toolchain을 고정하는 것이다. 그 후 등록한 새 자료 계열의 원문 채택과 별도 검토, 질문 작성·검토·고정, 공식 입력 길이 검사 순서로 진행한다. 격리 검증 본문은 부모/설계자/구현자가 열지 않는다. 이전 C0/C1/C2 평가를 재실행하지 않는다.
