# C2 입력 준비 실패

2026-10-14. **기존 4,096-token C2 비교는 입력 준비에 실패했고 품질 생성은0회다.** Calibration8의 성공한 준비 결과, 검증 문항의 원래 거절본과 보완v2, source/policy 고정은 그대로 보존한다. 이 실패를 모델 답변 오답이나 비교 완료로 세지 않는다.

## 실제 순서와 관측

1. Validation12 보완v2를 별도 검토자가12승인한 뒤 `0a58129`에 고정했다. Push38503506042·PR38503510846의 필수3job은 성공했다. 문항 사전검토와 CI 성공은 모델 입력 준비 통과가 아니다.
2. 격리 담당자가 원래 CLI로 공식 오프라인 입력 준비를1회 시도했다. `input_preparation_failed`만 출력했고 input/receipt를 만들지 않았다. 원래 CLI의 내부 예외와 내부 호출 수는 기록되지 않았다.
3. 새 진단 진입점에서 같은 동결 함수·입력에 원래 loader/counter를 그대로 위임하며 metadata만 계측했다. 이 별도 준비 호출1회에서 `ValueError: input_preparation_token_limit`를 직접 확인했다. 처음 CLI의 내부 원인을 사후 확인했다고 주장하지 않는다.

진단은 schema와 두 방식의 catalog/grammar12항목을 통과한 뒤 공식 tokenizer loader1회·counter14회를 측정했다. `c2-val-07`의 C2 입력4,572가 상한4,096을 넘었다. 측정한7문항의 L0는753~3,631, C2는807~4,572다. 나머지5문항은 원래 함수의 즉시 중단 규칙 때문에 미측정이다. 전체12 최대값으로 표현하지 않는다. 준비 호출 총2회와 모델 생성0회를 구분한다.

원래 payload/원문/청크 순서/정답/정책을 바꾸지 않았다. Tokenizer metadata hash는 calibration과 같고, item13·policy41 바인딩과 기존 실패 로그도 변하지 않았다. 부모는 질문/정답/원문이 아닌 안전한 오류 코드·정수 계측값·hash만 확인했다.

## 보존한 증거

- [진단 실행의 원본 metadata](../experiments/results/meetings-c2-validation-input-failure-original-v1.json)
- [후속 설명을 붙인 요약본](../experiments/results/meetings-c2-validation-input-failure-summary-v1.json)
- [실행 직후 console metadata](../experiments/results/meetings-c2-validation-input-failure-console-v1.json)
- [실제 진단 source 바이트](../experiments/diagnostics/meetings-c2-validation-input-failure-v1.py.txt)
- [복사·복구·원래 CLI 오류 바이트 기록](../experiments/results/meetings-c2-validation-input-failure-provenance-v1.json)

반환된 진단 receipt에는 실행 후 요약 필드와 오류 arm 설명이 덧붙여져 있었다. 부모가 실행 직후 console의 원본 길이14,240bytes/SHA256과 달라진 점을 확인했다. 파생 필드를 제거하고 console에 있는 원래 diagnostic 객체를 복구해 같은 직렬화로 만든 바이트가 기록된 원본 SHA256과 **정확히 일치**했다. 복구한 원본과 후속 요약을 별도 보존하며, 요약본을 수정되지 않은 실행 원본이라고 부르지 않는다. 이 복구에 tokenizer/모델을 다시 실행하지 않았다.

## 다음 작업 경계

입력에 맞춰 질문을 교체하거나 청크를 잘라 같은 실험을 통과시키지 않는다. 원래 C2의4,096 조건은 실패로 남긴다. 품질 답변을 한 번도 생성하지 않았다는 사실과 검증 입력의 길이 metadata를 이미 보았다는 사실을 모두 공개한 별도 후속 설계를 등록한다. 공통 입력 예산의 변경은 두 방식에 동일하게 적용하고, 기존 자료/의미 조건을 보존하며 새로운 중립 자원 검증이 필요하다. 구체적인 후속 조건은 별도 설계에 따르고 자동 서비스 채택을 의미하지 않는다.

원래 명령은 아래와 같으며 **실패 기록 재현용 설명**이다. 준비 실패를 지우려고 재실행하거나 원래 출력 경로를 재사용하지 않는다. Validation 내용에 접근하는 재현은 격리 담당자의 범위다.

```powershell
uv run --locked --group retrieval --no-sync python -m scripts.prepare_meeting_blocks_inputs --draft data/evaluation/meetings-c2-validation-v1/draft-v2.json --output .local/c2-validation-inputs-v2 --phase validation
```

유료 사용·추가 다운로드·GPU/서비스 모델 시작·답변 생성·사용자 검수는0이며 phase1/PR14는 계속 미완료/draft다. 목표는 active이고 이 단계의 실패가 프로젝트 중단이나 사용자 승인 대기를 뜻하지 않는다.
