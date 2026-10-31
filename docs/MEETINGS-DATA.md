# 회의 기능 개발·통합 검증 자료

이 자료는 새 기능의 재현 가능한 개발·통합 검증용이다. 독립된 성능 벤치마크, 실제 고객 회의, 사용자 검수 자료가 아니다. 기존 M2/M3/M4 최종 test와 M5-B validation을 사용하지 않는다.

## 실제 공개 자료

Project Jupyter의 [공개 저장소](https://github.com/jupyter/jupyter)에서 revision `6b5eb0f469c7bc3ea43d6d2a0ba1057853c9a3a5`를 고정했다. [BSD-3-Clause 원문](https://github.com/jupyter/jupyter/blob/6b5eb0f469c7bc3ea43d6d2a0ba1057853c9a3a5/LICENSE)의 저작권·조건·면책을 fixture와 함께 보존한다. Project Jupyter의 보증이나 협업을 뜻하지 않는다.

- 2025년 2월 공개 community call 회의록.
- 2025년 6월 공개 community call 회의록.
- 일반 문서인 community call 진행자 안내서.

정확한 경로·출처 URL·원본 SHA-256·가공본 SHA-256은 [manifest](../data/manifests/meeting-public-v1.json)에 있다. UTF-8/LF로 정규화하고 회의 접속 링크와 메일링리스트 연락처가 포함된 행만 제거했다. 나머지 본문은 재작성·번역하지 않았다. 회의록의 발언·공지·안건은 확정 결정이나 담당자가 배정된 작업과 같지 않으므로 AI가 없는 결정을 만들어 내지 않는지도 확인한다. 공개 참석자 이름은 원문 출처 확인을 위해 유지하며 개인정보를 보충하지 않는다.

소량의 공개 fixture는 `tests/fixtures/meetings/public/`에 있다. 원본 전체 코퍼스나 비공개 업로드를 저장소에 넣지 않는다. 재다운로드와 변환 재현:

```powershell
uv run --locked --no-sync python -m scripts.prepare_meeting_fixtures --download
uv run --locked --no-sync python -m scripts.prepare_meeting_fixtures
```

첫 명령은 고정된 공개 원문만 받아 manifest 해시를 비교한다. 두 번째 명령과 CI 검사는 네트워크나 모델 없이 저장 fixture를 검증한다.

## 별도 합성 운영 사례

AI가 작성한 한국어 출시 회의·후속 회의와 영어 운영 안내서를 `tests/fixtures/meetings/synthetic-*`에 구분했다. 90일 제안과 30일 확정의 구별, 30일→7일의 명시적 변경, 이름·날짜가 있는 작업과 없는 작업, 원문 수정·삭제·권한 변경을 검사하기 위한 통제 자료다. 실제 회의록으로 집계하지 않는다.

AI 생성 결과와 테스트가 사용자 편집 API로 저장한 변경을 구분한다. 자동 브라우저가 편집 버튼을 눌렀다고 사용자 검수가 늘어나지 않는다. 모든 자료의 사용자 검수는 0이다. 실제 모델 출력의 의미 지지·중요 내용 누락은 자동 quote 검사와 별도로 검토하고, 실패한 출력도 보존한다.

## 확인 범위와 해석

1. 실제 공개 원문을 업로드한 뒤 AI 요약과 인용 구절을 다시 원문과 대조한다.
2. 두 날짜의 회의와 일반 문서를 같은 검색 요청에서 찾고, 선택한 회의/기간/사람 조건을 검색 전에 적용한다.
3. 합성 사례로 제안·결정·변경·미정 작업을 확인한다. 없는 담당자·기한을 채우면 실패로 기록한다.
4. 권한이 없는 문서, 로그아웃, 처리 중 수정·삭제, 사용자 편집 충돌과 재시도를 검증한다.
5. 정상 답변·근거 부족을 구분하며 실제 Java HTTP 소요 시간과 Python 모델 시간은 별도로 표시한다.

몇 건의 개발 예시 통과를 일반적인 회의 요약 정확도나 상용 서비스 준비 완료로 확대하지 않는다. 기능 동작·회귀 테스트·실제 모델 품질·사용자 검수·외부 배포 상태를 각각 기록한다.
