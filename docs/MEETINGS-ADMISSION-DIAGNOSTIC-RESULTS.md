# 입력 수용 조건 진단 결과

2026-10-20. 커밋 `b1a965b6188ea2efe10278d7795230780842bb8c`에서 공식 진단을 한 번 완료했다. **고정한 합성 예시12개 모두 사전 기대와 일치했다.** 파서 결함은 이 범위에서 발견되지 않았고, 문단 수 제한이 입력 바이트 제한과 별도로 문서 형식을 제한하는 예시를 확인했다.

실제 공개 자료나 질문을 재실행한 결과가 아니다. 실제 자료 수용·토크나이저·모델·다운로드·사용자 검수는0이다. C7 source corpus 미충족과 답변 품질 미완료 상태는 그대로다.

## 무엇을 비교했나

실제 추출·정규화·chunk 분할·block 파서·C7 수용 함수·ko/en 직렬화를 사용했다. 원래 수용 결과는 수정하지 않고, 거부된 경우의 추가 직렬화 측정은 `diagnostic_only`로 분리했다. 모델을 호출하지 않고 원문 복원·좌표·크기·수용 경계가 설계대로 동작하는지를 확인한 작업이다.

모든 예시는 설계와 literal fixture에서 먼저 고정했다. 아래 byte 값은 family 전체의 처리된 원문이며, M0는 두 언어 중 더 큰 전체 빈 질문 메시지 크기다. 원래 수용 함수가 통과하지 않은 예시의 M0는 별도 관찰일 뿐이다.

| 예시 | 처리 원문 bytes | block 수 / 그중 공백 | M0 bytes / 상한6656 | 원래 수용 결과 |
| --- | ---: | ---: | ---: | --- |
| F02 · 연속 제목 | 86 | 23 / 0 | 4550 | 통과 |
| F03 · 연속 제목 | 90 | 24 / 0 | 4644 | 통과 |
| F04 · 연속 제목 | 94 | 25 / 0 | 4738 | block 상한 거부 |
| F05 · 문단과 빈 줄 | 33 | 23 / 10 | 4495 | 통과 |
| F06 · 마지막 빈 줄 포함 | 35 | 24 / 11 | 4589 | 통과 |
| F07 · 문단과 빈 줄 | 36 | 25 / 11 | 4678 | block 상한 거부 |
| F10 · 실제 chunk overlap | 1102 | 4 / 0 | 4201 | 통과 |
| F11 · 한국어 문서2048bytes | 2050 | 3 / 0 | 4720 | 통과 |
| F12 · 한국어 문서2049bytes | 2051 | 3 / 0 | 4721 | 문서 byte 상한 거부 |

F01 정규화, F08 소개 문장과 목록, F09 코드블록도 기대와 일치했다. 모든12개에서 각 chunk를 block으로 나눴다가 이어 붙인 내용과 좌표가 원문 slice와 정확히 같았다. F10은 실제 분할 `[0,1000)`, `[850,1100)`의150자 겹침을 유지해 family 원문1102bytes와 emitted chunk1252bytes를 구분했다. F12의 전체 family는4096bytes 이하지만 A문서 하나가2049bytes여서 원래2048 제한으로 거부된다.

모든 별도 관찰에서 schema와 reserved wire 크기도 기존 상한 안이었다. F04/F07은 작은 원문이어도25개 block을 만들면 거부되는 고정 예시다. 이를 실제 거부한 모든 공개 자료의 원인으로 일반화하지 않는다.

## 해석과 다음 판단

선택한 진단은 원문을 자르거나 입력 상한을 바꾸지 않고 parser 오류와 의도된 제한을 구별했다. 실제 오류가 확인됐다면 작은 재현 사례를 바탕으로 수정했을 것이다. 이번 결과는 설계된 동작과 일치하므로 기존 parser나24개 상한을 변경하지 않는다.

다음은 **기존 규칙 아래의 제한된 공개 자료 적합성 검토**다. 두 회의와 일반 문서의 완전한 원문으로 결정 변경·정책·담당 작업 등 전체 질문 의미를 설명할 수 있는지 독립 역할이 검토해야 한다. 이 검토는 아직 배정·실행하지 않았다. 의미를 약하게 만들거나 공개 자료를 합성 자료로 대체해서 성공 처리하지 않는다. 같은 진단이나 닫힌 모델 실험도 다시 실행하지 않는다.

사용자가 판단할 부분은 향후 실제 문서/답변 검수다. 이번 기계적 일치를 사용자 검수나 답변 정확도로 바꾸어 기록하지 않는다. AI가 설계·구현·코드 검토·실행 기록 확인을 담당했고 역할별 노출과 검증 범위는 기여 문서에 남겼다.

## 확인한 실행과 증거

- push39376766443/PR39376771232의 backend·web·java-service 모두 통과한 뒤 실행했다. Push 로그의 Python2932통과/21skip/경고1·Java browser82통과/실패0은 단위 검사 범위와 합산하지 않는다.
- 공식 CLI 종료0, 저장 영수증과 CLI 요약 일치,12개 완료·미실행0·최초 오류 없음, HEAD 전후 동일을 확인했다.
- 원본 code/input binding82개와 현재 bytes가 같으며 기존 동결77개도 그대로다. Parent capture 시간31.202442초에는 Git와 파일 증명이 포함돼 **모델 응답 시간이 아니다**.
- 예약·행12개·terminal·CLI 요약·process capture의5개 원본을 exact copy했다. 동기화용 pending terminal은 local에 보존하고 별도의 성공 증거로 중복 공개하지 않았다.

[CI 관측 기록](../experiments/results/meeting-admission-diagnostic-ci-v1.json), [공개 복사와 전체 측정표](../experiments/results/meeting-admission-diagnostic-v1/publication.json), [행 원본](../experiments/results/meeting-admission-diagnostic-v1/rows.jsonl), [공식 영수증](../experiments/results/meeting-admission-diagnostic-v1/receipt.json), [프로세스 기록](../experiments/results/meeting-admission-diagnostic-v1/process-receipt.json)을 보존했다.

주요 SHA256은 rows `1fd02754a61169500389e3a001a2493fbbd2c941763c650f109f48b7949f527e`, terminal `dfc178687f42b0cadd2df310e8b8c931aec21a1726fd23484854462d53d92b7b`, publication `772828a7bf4a5204816299678c9d63828d2fd908a8abd8e09eb8883ba533a8c4`다. `.local/meetings-admission-diagnostic-v1`은 소비된 공식 실행이므로 삭제하거나 재실행하지 않는다.

## 공개 저장 과정의 줄바꿈 수선

최초 결과 커밋3a9fa48에서 CLI 요약의 마지막 CRLF가 Git에 의해 LF로 바뀌었다(원본638bytes/ef2de51c, 최초 커밋637bytes/cc308c14). Index exact 검사 assertion이 실패했지만 부모의 shell 명령 나열이 이후 commit/push를 중단하지 않은 검증 흐름 오류였다. 원본 파일·공식 진단 결과의 실패가 아니다.

원본 stdout와 local 공개 copy는 그대로 보존했고 해당 파일 한 경로에만 `-text`를 적용해 원래 bytes를 다시 stage한다. 수선 검증과 commit은 분리해서 실행하며 최초 커밋·실패도 남긴다. [공개 저장 수선 기록](../experiments/results/meeting-admission-diagnostic-publication-repair-v1.json)에 차이와 원인을 기록했다. 공식 진단은 다시 실행하지 않는다.
