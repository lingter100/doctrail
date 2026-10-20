# 서비스 RAG 자료 준비와 실행 사전점검

2026-10-20. 실제 서비스 연결 코드의 필수 CI는 통과했다. 새 자료 준비의 첫 시도는 완전한 공개 corpus를 확보하지 못했으며, 실제 모델 연결이나 답변 품질은 아직 실행하지 않았다.

## 첫 자료 준비 결과

| 구분 | 수행한 조회 | 결과와 미실행 |
| --- | --- | --- |
| Calibration | metadata9, README2; 저장소3·공개 후보2 한도 | 적용 이용조건을 확인하지 못했다. 완료 회의 원문·합성·Java·문항·모델0 |
| Validation | metadata9 보수 계수, source body3, license3; 일부 중복 차감 | package.json ISC 선언의 회의 문서 적용 범위와 외부 회의록의 고정 revision을 확인하지 못했다. 부모가 추가 자료 작성 전에 닫았으며 합성·Java·문항·모델0 |

`nodejs/TSC` 초기 후보가 겹쳐 validation에 예약했고 calibration은 다른 저장소를 선택했다. Calibration의 `tc39/notes`, `rust-embedded/wg` 확인에서도 적용 이용조건을 검증하지 못했다. Validation의 `rust-lang/wg-async`에는 Apache-2.0 파일이 있었지만 링크된 외부 회의록까지 같은 허가와 고정 revision이 적용된다고 판단하지 않았다.

이는 공개 자료의 부재, 법적 이용 불가능, 자료의 의미 부적합, 모델 품질 실패를 증명하지 않는다. 처음 정한 한도를 지키며 종료한 수집 시도다. 원본 응답과 예약·실패를 로컬에 보존하고 공개에는 출처·건수·hash·상태만 저장했다. 부모는 calibration24·validation19 artifact binding을 hash/bytes로 확인했으며 실제 원문을 의미상 읽지 않았다.

Validation의 최초 commit API 응답에는 열어보지 않은 patch payload1개가 포함됐다. 의도한 원문 fetch와 응답에 본문이 포함된 사실을 구분한다. 원본을 삭제하지 않았고 이후 revision은 ref/ls-remote로 조회한다. “모든 응답이 순수 metadata” 또는 “노출이 전혀 없다”고 주장하지 않는다.

## 실행 사전점검

캐시 파일70개가 존재하고 크기가 일치했다. 작은62개는 현재 hash도 확인했으며 큰8개는 기존 검증 기록과 현재 크기만 확인했다. 실제 실행 시 기존 모델 identity 검사를 생략할 근거가 아니다.

Java21·Python 의존성·현재 opt-in JAR·브라우저 실행 파일을 확인했다. 서버·모델·토크나이저·브라우저는 실행하지 않았다. 일반 코드13개 binding을 부모가 확인했다.

기존 candidate 실행기는 이전 모델 worker를 선택한다. 기존 브라우저 검사기는 실제 추론 설정을 지우고 합성 응답을 사용하므로 실제 native 검증에 그대로 쓸 수 없다. Windows의 일반 프로세스 종료 방식은 Python의 finally를 거치지 않을 수 있다. 따라서 새 worker를 현재 프로세스의 context로 유지하며 검색·Java와 함께 시작하고 정상 종료하는 최소 실행 조립이 필요하다.

전체 startup120초는 인증된 HTTP 준비까지, 정리5초는 소유 프로세스·handler·thread 종료까지 확인해야 한다. 기존 도구의 개별 대기 시간이나 native 준비 시간만으로 통과를 주장하지 않는다. 동기 파일 읽기·native context를 강제 선점할 수 있다는 보장도 아직 없다.

## 다음 판단

이용조건과 저장소 안의 날짜별 회의 기록 경로를 먼저 확인하는 짧은 metadata 조회를 별도로 수행했다. Metadata 후보는 실제 완료 회의록이나 라이선스 적용이 확인된 자료가 아니다. 새 시도는 이전 결과와 분리해 등록한 뒤 수행하며 기존 실패를 덮어쓰지 않는다.

사용자 요구는 이용 가능한 공개 자료와 재현 가능한 가공이며 GitHub 자료만 사용하라는 조건은 없다. 공식 기관의 명시적인 문서 라이선스·고정 버전/수집 원본을 갖춘 자료도 검토할 수 있다. 플랫폼 선택을 바꾸더라도 전체 원문·공개와 합성 구분·여러 회의와 일반 문서·독립 검토·평가 격리는 유지한다.

[관측 요약](../experiments/results/meetings-service-rag-source-preflight-v1.json), [calibration](../data/evaluation/meetings-service-rag-calibration-v1/safe-summary-v1.json), [validation](../data/evaluation/meetings-service-rag-validation-v1/safe-summary-v1.json), [원래 서비스 계획](MEETINGS-RAG-ACCEPTANCE-PLAN.md)을 함께 읽는다.
