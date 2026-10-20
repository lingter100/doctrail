# C5 평가 질문 작성과 검토

2026-10-20. source commit aa7836c와 양쪽 필수 CI 성공 뒤, 고정한 원문12개에서 질문14개와 정답 근거 초안을 작성했다. 실제 모델 실행은 아직 없다.

## 해결하려는 문제

인용 문자열이 원문과 같아도 답변에서 필요한 사실이 빠지거나 조건·시점을 잘못 해석할 수 있다. 따라서 질문마다 필요한 사실과 충분한 근거 대안을 먼저 기록하고, 작성자와 다른 검토자가 전체 원문을 보고 확인한다. 답변 가능한 질문과 일부 필수정보가 없어 보류해야 하는 질문을 함께 사용한다.

## 현재 작성 결과

| 구분 | Calibration | 격리 validation |
| --- | ---: | ---: |
| 질문 | 6 | 8 |
| 한국어 / 영어 응답 | 3 / 3 | 4 / 4 |
| 답변 가능 / 보류 기대 | 4 / 2 | 4 / 4 |
| 필요한 사실 | 29 | 31 |
| 모든 충분한 대안에 복수 문서가 필요한 질문 | 2 | 3 |
| 원문 문서 / 고유 전체 청크 | 6 / 15 | 6 / 14 |

형식·근거 좌표·전체 청크·구성 검사는 양쪽 모두 통과했다. 별도 독립 검토에서 calibration6/validation8 모두 수정0·반려0으로 수용됐다. 필요한 사실60개와 충분한 근거 대안57개를 확인했다. 보류 질문은 관련 family 전체에서 필수정보가 없는지 확인하며 답이 있는 청크를 제외해 만들지 않는다. 원문이나 context를 토큰 수에 맞춰 줄이지 않는다.

작성자는 기존 실제 Astra xhigh c5_calibration_author와 c5_validation_author다. 중단 뒤에도 기존 문맥을 유지한 역할로 재개했고, 새로운 실제 Git/code/source 증명을 마친 후 작성했다. 별도 c5_calibration_prereviewer와 c5_validation_prereviewer가 각각 item 검토만 수행한다. 부모는 질문·정답 의미를 열지 않고 hash와 구조 검사 metadata를 확인했다. 최종 답변 판정자2명은 이 작성/검토 역할과 별개다.

## 완료 상태를 구분하는 기준

AI가 작성한 질문14개, 구조 검사를 통과한 질문14개, 독립 의미 검토가 수용한 질문, 사용자 검수한 질문은 서로 다른 상태다. 현재 독립 AI 검토 수용은14개이고 사용자 검수는0이다. 각 item freeze는 정확히6파일을 결합한다. source freeze14/15와 toolchain76, 원래 validation 반려17파일은 그대로 보존한다.

검토가 반려하면 원래 초안과 이유를 남기고 피드백 범위 안의 새 버전을 다시 검토한다. 수용한 item freeze를 커밋한 뒤에만 split별 공식 offline 계수1회를 실행한다. 이후 calibration 원래6/6 및 무결성 조건을 통과해야 validation 모델 실행8개가 열린다. 새 tokenizer/native/답변 품질 판정은 아직0이다.

작은 AI 작성 진단 표본이므로 전체 서비스 정확도로 일반화하지 않는다. 한국어 UI, 권한·수정·삭제와 실제 Java/React 운영은 별도 검증 범위다. [작성 영수증](../experiments/results/meetings-c5-item-authorship-v1.json), [원문 준비](MEETINGS-C5-SOURCES.md), [고정 계획](MEETINGS-C5-PLAN.md), [최신 상태](STATUS.md)에 근거를 남긴다.

검토 결과와 원본 보존 hash는 [독립 검토 영수증](../experiments/results/meetings-c5-item-review-v1.json)에 기록한다. 검토자가 실행한 보조 표시 스크립트 오류3건은 별도 보존했으며 최종 pure 검사는 통과했다. 커밋 후 fullmaterial proof와 공식 계수는 다음 단계다.
