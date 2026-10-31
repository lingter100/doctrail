# 로컬 후보의 입력 한도 초과 후 다음 단계

2026-10-26 · 기존 Astra xhigh의 generic 설계 · 구현·실행 전 제안

**다음 행동 하나는 원문을 전혀 줄이지 않고, 모델에 보내는 반복 구조 정보만 줄이는 opt-in compact wire를 기존 candidate script/test 2개에 추가하는 것이다.** 회의 내용·질문·근거·품질 기준은 그대로 유지한다.

[실제 v2 결과](../experiments/results/meetings-local-candidate-actual-v2.json)는 native 시작·정리까지 운영 경로가 끝났지만, 요약 4개와 QA 4개 모두 답변 생성 전에 입력 4096토큰을 초과했다. completion 0이므로 요약·답변 품질 결과는 없다. CLI 14.578초는 추론 지연이 아니다.

| 개발 원문 | 요약 입력 | QA 입력 |
|---|---:|---:|
| 01 | 4684 | 4636 |
| 02 | 4627 | 4570 |
| 03 | 5771 | 5740 |
| 04 | 4927 | 4888 |

이 수치는 실제 template 포함 관측이다. 현재 원문 단위마다 `kind/id/text/start_offset/end_offset`, gap마다 `kind/text`를 반복 전송한다. 4096 상향은 입력 예산·자원 조건까지 바꾸므로, 먼저 서버가 이미 가진 위치 정보를 전송에서 빼는 좁은 개입을 선택한다. 구조 정보가 차지하는 토큰 수와 compact의 실제 적합성은 **새 tokenization 없이 알 수 없으며 통과를 보장하지 않는다**.

제안하는 `source-parts-compact-v1`은 `source_parts`의 각 unit 객체를 `[original_id, original_text]`, 각 gap 객체를 원래 문자열로 표현한다. 빈 gap도 그대로 남긴다. 모든 항목의 문자열을 순서대로 합치면 원문 전체가 정확히 복원돼야 한다. 제목·언어·질문·candidate_claims와 기타 payload 값은 그대로다. 새 번호 부여·정렬·중복 문구 병합·Unicode 정규화·공백/개행 정리·요약/선택은 하지 않는다. offset은 원래 서버 unit map에 그대로 보존한다. projection의 항목 순서·ID·원문 복원 동등성이 깨지면 모델 호출 전 실행 오류로 STOP하며 불완전한 입력을 보내지 않는다.

시스템 지시문에는 compact를 읽는 아래 범례만 고정 추가한다. 기존 내용·근거·불확실성·형식 지시를 바꾸거나 예시를 추가하지 않는다.

> source_parts is ordered: strings are verbatim gaps; [id,text] pairs are citable units. Read all entries. Evidence IDs refer only to those original unit IDs.

구현 경계는 기존의 작은 순수 projection 하나와 공통 메시지 변환으로 제한한다. `source_payload`가 만든 원형 객체, 원문 및 units는 그대로 보유한다. 요약과 자체 검토는 먼저 기존 `summary_messages(source, claims)`를 호출한다. 특히 검토의 offset/text triple→ID 연결을 먼저 끝낸 뒤, **전송 직전에 user JSON 객체의 source_parts만** 변환한다. QA도 같은 경계를 사용한다. serialized 문자열 전체에 치환을 적용하지 않는다. 기존 `messages/safe_payload`와 응답 parser를 재사용하며 새 런타임·검증기·내용 판정기를 만들지 않는다.

기존 strict 등록 shape에 wire 필드가 없으면 현재 legacy 형식·메시지 바이트를 보존한다. 새 opt-in 등록은 정확한 추가 키 `source_wire_format`을 명시하고 `source-parts-legacy-v1` 또는 `source-parts-compact-v1`만 허용한다. unknown 값·다른 추가 키는 native 전에 거부한다. CLI/env가 이를 덮어쓰거나 실패 후 형식을 자동 전환하지 않는다. 새 등록 SHA와 코드 hash가 projection·범례를 고정하고 report/terminal에도 실제 형식을 남긴다. 기존 등록 파일은 편집하거나 다시 실행하지 않는다.

기존 58개 검사를 유지하며, legacy 메시지 불변·compact exact roundtrip·빈/선행/중간/후행 gaps·CRLF/공백·Unicode/조합형·JSON처럼 보이는 원문·동일 문구의 서로 다른 위치와 ID·긴 원문의 전량 보존을 확인한다. summary/review/QA가 같은 source wire를 쓰고 질문·candidate_claims가 바뀌지 않는지도 확인한다. 잘못된/중복/범위 밖/비정수 evidence ID는 기존 parser가 계속 거부해야 한다. 문자/바이트 크기 비교를 토큰 측정이나 의미 품질 검증으로 기록하지 않는다.

모든 요청은 같은 template/tokenizer로 실제 입력 토큰을 세고 **4096 초과 시 completion 없이 거부**한다. 요약이 들어가도 생성된 candidate를 포함한 자체 검토는 다시 한도를 적용한다. 검토를 생략하거나 초과한 초안을 통과로 세지 않는다. 내용·입력 거부는 다음 고정 항목으로 진행하고, 프로토콜·자원 실패는 STOP하는 기존 경계를 유지한다.

모델·원문 4개·질문 4개·기준·evidence ID/offset map, 출력 768/128/256·요약/검토 공유120초·QA60초·ctx6144·시작120/활성900/정리5/전체1025초·10GiB gate·최대8+4호출/4608출력토큰은 불변이다. 결과 분모도 요약4/QA4로 고정한다. 운영상 입력 거부가 줄어도 완전한 요약·답변·권한·UI의 Phase1 품질 통과로 승격하지 않는다.

부모 수용·공개 후 기존 source2의 최소 구현 → synthetic 검사·독립 검토·정확 소스 CI → **새 등록과 별도 1회 실행 배정**으로 진행한다. 실제 fit·검토·품질은 그 결과에서 판단하고 여전히 초과하면 실패를 그대로 반환한다. 예산 인상·내용 축약·프롬프트 순환·자동 재시도는 추가하지 않는다. 종전 v2는 소비된 결과로 보존하며, 이번 설계에서 모델 hash·native·tokenizer·실험 재생은 0이다.
