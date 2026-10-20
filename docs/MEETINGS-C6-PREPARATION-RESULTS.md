# C6 입력 준비 결과와 종료 이유

2026-10-20. C6는 **입력 크기 조건에서 종료**됐다. 모델 답변을 생성하기 전에 검증용 8문항 중 2개가 사전등록된 입력 상한을 넘었다. 답변 정확도가 낮았다는 결과와는 다르며, reader 변경이 실제 지연을 개선했는지도 이번 실행으로 알 수 없다.

## 실제 측정

| 구분 | 공식 준비 | 측정 문항 | 입력 토큰 범위 | 5,120 초과 | CLI 시간 | 결과 |
| --- | --- | --- | --- | --- | --- | --- |
| calibration | 1회 | 6 | 1,273~2,192 | 0 | 71.720초 | 통과 |
| 격리 validation | 1회 | 8 | 1,784~5,266 | 2 | 47.741초 | 실패·종료 |

두 실행 모두 캐시 토크나이저 로드1회, 다운로드0, 실제 생성0이다. CLI 시간에는 자료·Git 검증과 토크나이저 준비가 포함되며 모델 응답 시간이 아니다. Validation 요청 JSON의 최대 크기는25,077bytes로524,288bytes 제한을 넘지 않았다. 초과한 조건은 입력 토큰이다. 검증 문항별 길이나 내용을 근거로 상한·문항을 조정하지 않는다.

## 보존한 오류와 수정

Calibration의 첫 직접 script 실행은 `ModuleNotFoundError: scripts`로0.707초 만에 종료됐다. 이때 main/prepare·출력 예약·토크나이저에는 도달하지 않았다. 실행 코드나 자료를 바꾸지 않고 저장소 루트에서 Python의 모듈 실행 방식을 사용했다. CLI 시작은2회, 실패 기록1개, 실제 공식 준비는1회다. Validation은 module CLI를 처음부터 사용했다. 공식 준비 시작 이후 재시도는 양쪽0이다.

실제 사용한 진입 방식은 다음과 같다. 아래는 실행 이력 설명이며 **닫힌 C6에 다시 실행하지 않는다**.

```text
.venv/Scripts/python.exe -X utf8 -m scripts.prepare_meeting_c6_inputs --phase <split> ...
```

인자는 각 영수증의 accepted draft-v2/oracle-draft-v2/source-freeze/item-freeze 경로·SHA와 같다. 준비 코드 SHA4d2f13bf는 바뀌지 않았다. `python script.py`로 실행할 때의 모듈 탐색 경로와 `python -m scripts...`의 차이이며, 입력 크기 실패를 숨기는 재측정은 하지 않았다.

## 실행하지 않은 범위

실행 plan은 양쪽 준비 통과를 요구한다. Calibration의 통과만으로 모델을 호출하지 않았다. Native 요청, 익명 답변 pack, 최종 의미 판정, 서비스 채택은 모두0이다. Validation 입력 파일은 생성되지 않았다. 이미 닫힌 C0~C5나 C6를 재실행하지 않는다.

근거가 충분한 문항을 만드는 검토와 모델이 수용할 수 있는 길이의 입력을 만드는 검증은 별개다. 이번에는 앞 단계가 수용됐지만 뒤 단계에서 실패했다. 다음 작업은 출처 채택·분할 단계의 크기 규칙을 먼저 정하는 설계 검토다. 고정 wrapper와 원문 전체 청크의 비용을 함께 보되, 토큰/글자 비율을 언어 공통 보장으로 가정하지 않는다. 새 자료를 만들기 전에 규칙과 한계를 등록한다.

## 재현 자료와 한계

- [측정·종료 집계](../experiments/results/meetings-c6-preparation-results-v1.json): 공식 실행 HEAD e8e5297, 원본/수용본 불변, 초기 오류와 실제 준비의 구분.
- [Validation 실패 영수증 exact 사본](../experiments/results/meetings-c6-validation-preparation-failure-receipt-v1.json): 원본 SHA6a3fecee, 수정 없음.
- [Calibration 입력](../data/evaluation/meetings-c6-calibration-inputs-v1/input.json)과 [영수증](../data/evaluation/meetings-c6-calibration-inputs-v1/receipt.json): 원본과 바이트가 동일하다.
- [수용본 CI와 실제 Git 증명](../experiments/results/meetings-c6-item-ci-v1.json): 검증된 코드·자료와 실행 준비 실패를 분리한다.

공개 원문6개와 AI 합성 원문6개, AI 작성/독립 AI 검토 문항14개다. 사용자 검수0이며 최종200~300문항 benchmark가 아니다. Phase1 자연어 답변과 전체 서비스 운영 수용은 아직 완료되지 않았다.
