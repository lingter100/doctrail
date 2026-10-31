# OpenSearch 공개 회의 QA 개발 자료

공개 회의록2개와 운영 규칙1개를 바탕으로 만든 한국어 개발 질문2개입니다. 원문은 실제 공개 문서이고 질문·참고 답변·묶음 메타데이터는 AI가 작성했습니다. 독립 AI가 참고 답변의 근거 충분성을 검토했으며 사람의 검토는0회입니다. 보류한 최종 평가 자료나 모델 성능 측정 자료가 아닙니다.

`manifest.json`에 고정 커밋·원문 URL·Git blob SHA-1·원문 SHA-256·처리 후 UTF-8 SHA-256을 기록했습니다. 모든 원문과 Apache-2.0 LICENSE, 당시 Amazon/계열사 NOTICE를 바이트 변경 없이 보존했습니다. 역사적 SIG 규칙은 명칭 변경을 설명하는 보조 자료이며 질문 문맥에는 포함하지 않습니다.

Python3.11 이상 표준 라이브러리만 사용합니다. 저장소 루트에서 다음 명령으로 원문6개, 질문·검토 파일, 다시 구성한 입력2개와 근거 sidecar의 해시를 검증할 수 있습니다. 네트워크·모델·tokenizer·서비스는 사용하지 않습니다.

```powershell
python -I -B scripts/prepare_meeting_qa_development.py validate
python -I -B scripts/prepare_meeting_qa_development.py prepare --output .local/opensearch-qa-development-copy
```

`prepare`의 출력 폴더는 새 경로여야 합니다. 생성되는 `case-01.input.json`, `case-02.input.json`, `SOURCE-SIDECAR.json`은 승인된 개발 입력의 원래 바이트와 동일합니다. 패킷과 스크립트를 다른 폴더에 복사한 경우 `--bundle <패킷 경로>`로 지정할 수 있습니다. 개인 환경 경로, 모델 파일, 과거 비공개 평가 자료는 필요하지 않습니다.

질문1은6월의 Search SIG 제안,11월의 범위 논의, 일반 출범 절차를 연결합니다. 질문2는 제공 자료에서 확정 범위와 초기 구성원 명단을 확인할 수 없어 답변을 보류합니다. `cases.json`의 참고 답변은 충분한 답변의 예시이며 문자열 일치 정답이 아닙니다. 근거가 같은 충분한 바꿔쓰기를 허용합니다.

주의할 원문 차이는 그대로 남겼습니다.

- 6월 문서는 SIG, 11월 문서는 TAG라는 명칭을 씁니다. 10월의 명칭 변경 정보는 별도 출처를 가진 보조 이력입니다.
- 11월 파일명·날짜 제목은 2025년 11월 12일이지만 내부 의제에는 October 표기가 있습니다. 어느 쪽이 실제로 수정됐다고 단정하지 않습니다.
- 운영 규칙의 `techincal-advisory-groups` 링크 오타를 교정하지 않았습니다.
- 스냅샷 날짜는 제공 판본의 발행 기준이며 그날까지 모든 조직 활동을 포괄했다는 뜻이 아닙니다.

이 묶음은 세 문서 전체를 직접 제공하는 개발 진단용입니다. 검색 성공률, 생성 답변의 정확성, 모든 가능한 충분한 답변의 길이, 과거 모든 자료와의 완전한 독립성을 증명하지 않습니다. 출처·라이선스는 `originals/LICENSE`, `originals/NOTICE`와 `manifest.json`, 내용 검토는 `REVIEW.md`와 `RESULT.json`을 참조하세요.
