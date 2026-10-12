# M4 fit 초안 작성 기록

- 작성일: 2026-10-12. 작성 역할은 fit 질문 작성이며 독립 의미 검수 역할이 아니다.
- 작성 모델 설정: `gpt-6-astra` / `xhigh` (배정된 도구 수락 설정). 서비스 추론 모델과 구분한다.
- 작성 지침: `data/training/generation/protocol-v1.md`.
- 읽은 데이터: 할당된 fit author pack의 16개 train 문서 전체. Calibration/dev/test 질문·문서와 검색 결과는 읽지 않았다.
- 초기 V1 팩과 최종 V3 팩의 `documents` 및 `allowed_document_ids`가 완전히 같음을 직접 비교했다. 최종 팩은 사전등록 계획/인벤토리 바인딩만 갱신하며 모든 행은 최종 V3 해시를 사용한다.
- 최종 author pack SHA-256: `92a710c9c60957478fd6195394799214421922750a1c0f6aae79582e015e43bc`.
- 최종 plan SHA-256: `579e8ce0c6efbdc6aafe7906e873dbf051e0fecd0266e2f6cacefcda70c3e8ba`; 부모가 전달한 사전등록 커밋: `611a66a`.
- 초안 SHA-256: `5d095cda4710c05fc84f2844c03802aa817a244b0fee3111725bb62fa3ca3f4f`.

## 결과

64행 / 64개 독립 질문 의도 / 16개 코퍼스 계열, 각 문서·계열 4개다. 부족분은 없다. 한국어 50개, 영어 14개다. 한국어 질문·영어 근거 42개이며 유형은 `cross_lingual` 42개, `semantic` 16개, `exact_term` 6개다. 질문은 단일 사실·조건·명령 동작을 요청하며 답안은 해당 인용만으로 짧게 작성했다. 제목만을 답의 근거로 삼거나 번역·말바꾸기로 수를 채우지 않았다.

## 자동 확인과 한계

기존 `scripts.prepare_training`의 `chunks_for`, `evidence_span`, `query_shingles`, `jaccard`를 import하여 **fit 팩 문서만** 검사했다. 코퍼스 로더, dev/test 평가, 음성 채굴, 모델 추론, 훈련, 의존성 동기화는 실행하지 않았다. 모든 행의 원문 인용이 한 번 정확히 나타나며 `occurrence=0`이다. 인용 길이는 47~299 코드포인트이고 모두 변경하지 않은 기존 청크 하나 이상에 완전히 들어간다. 처음 확인에서 `m4-fit-029`의 단락 앞부분이 청크 경계를 넘는 것을 발견해 동일 사실을 직접 지지하는 연속된 구절로 줄였으며 질문·답의 의도는 바꾸지 않았다.

정규화 문자 3-gram Jaccard 0.8 이상 질문 쌍은 0개다. UTF-8, BOM 없음, LF 및 최종 줄바꿈을 확인했다. ID 연속성, 고유 의도, 계열당 최대 4개, 언어/교차 언어 유형 일치, 단일 evidence, 팩 해시와 provenance 값도 확인했다. 자동 검사는 의미 라벨의 정확성을 증명하지 않는다.

모든 행의 `semantic_review.status`와 `provenance.human_review`는 `pending`이다. 다음 단계는 독립 AI 의미 검수, E5 토큰 유지 확인 및 별도의 음성 후보 검수다. 이 초안만으로 훈련 준비 완료 또는 사용자 검수 완료를 주장하지 않는다.

원문은 The Kubernetes Authors의 공개 문서(CC-BY-4.0)이며 고정 source revision의 실제 문서다. 질문·참고 답안·rationale은 AI 작성이다. 정식 결과의 문서별 출처 URL/저자/라이선스는 author pack을 통해 compiler가 보존한다.
