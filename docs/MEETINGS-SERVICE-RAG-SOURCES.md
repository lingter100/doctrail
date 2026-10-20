# 서비스 RAG 자료 준비와 실행 사전점검

2026-10-20. 실제 서비스 연결 코드의 필수 CI는 통과했다. 현재 calibration6문서/32청크와 별도 validation6문서/66청크가 원문 전체 등록·독립 source 검토를 통과했다. 실제 모델 연결과 새 자료의 답변 품질은 아직 실행하지 않았다. 아래 첫 시도의 실패는 수정하지 않고 보존한다.

## 현재 수용된 자료와 다음 문항

Calibration은 기존 freeze64개를 유지하고6문항 초안을 독립 검토 중이다. Validation은 공개3·새 AI 합성3개이며 독립 검토 수용6·거부0·원본수정0이다. 부모가 [source freeze](../data/evaluation/meetings-service-rag-validation-v3/source-freeze-v3.json)의51개 bytes/hash를 확인했다. 실제 Java 등록6·재조회6·원문/66청크 일치는 자료 등록 검증이며 회의 자동 분석이나 검색·생성 품질 증거가 아니다.

과거 fingerprint metadata 공백3개와 다른 split의 의미·번역 중복 부재 미확인을 기록한다. 독립 source 검토가 원문에 적힌 기술 주장 자체나 미완료 계획을 확정 사실로 승인하는 것은 아니다. 가장 큰 원문의51청크도 온전히 보존하며 이후 top5 검색·입력 한도의 통과를 미리 주장하지 않는다.

Validation item 작성자와 독립 reviewer는 [별도 등록](../data/evaluation/meetings-service-rag-validation-items-registration-v3.json)에 묶었다. Source freeze/등록 commit·필수 CI 뒤8문항 작성을 배정한다. 같은 split source 역할을 재사용하고 최종 answer judge에서는 제외한다. 사용자 검수0·실제 모델 호출0이며 기존 실패 원본은 모두 유지한다.

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

## Calibration v2 실제 등록 결과

별도 등록 후 `cncf/tag-app-delivery`의 고정 commit에서 공개3개와 Apache-2.0 원문을 확보하고 새 합성3개를 구분했다. 전체6개를 실제 Java 문서 API에 등록해32청크·좌표·원문 저장값과 기존 Python 처리의 일치를 확인했다. 채팅 기록의 의미적 충분성과 완료 회의 여부는 독립 검토 대상이며 작성자 판단만으로 source 수용을 선언하지 않는다.

관찰 코드의 최초 변수 충돌은 HTTP0으로 종료했고 원본 로그를 남겼다. 수정 실행만 성공이며 `/documents` 처리 증거를 `/meetings` 자동 분석 증거로 보고하지 않는다. 모델·tokenizer·문항·사용자 검수0이다.

원래 산출물 목록에는 종료 후 제거되는 SQLite 임시2파일이 포함됐다. 부모가50일치/2누락을 확인한 뒤 작성자가 DB 연결이나 Java 실행 없이 [영속 목록 v3](../data/evaluation/meetings-service-rag-calibration-v2/artifact-index-v3.json)를 만들었다. 부모가57개의 bytes/hash를 확인했고 원래 목록·요약·receipt와 누락을 보존했다. [현재 요약](../data/evaluation/meetings-service-rag-calibration-v2/safe-summary-v3.json)은 독립 source 검토 대기다.

이후 독립 검토는6개 수용·거부0·수정0으로 완료됐다. [독립 요약](../data/evaluation/meetings-service-rag-calibration-v2/source-review-summary-v2.json)과 source freeze64개를 별도로 남겼고 부모도64개 hash를 확인했다. 역사적 normalized metadata 공백과 의미·번역 중복 부재 미입증을 명시한다. 문항/답변 품질 및 사용자 검수는 아직 없다.

## Validation v2 종료와 별도 후속 출처

`w3c/web-performance`에서 저장소 문서에 적용되는 W3C license를 확보했으나 공개 family를 채택하지 못했다. 후보 원문 하나가6,482,022bytes로 기존5MiB 업로드 상한을 넘었고, 두 번째 후보를 완료 회의록으로 확인하지 못했다. 기존 Python 처리의 실제 `file_too_large` 관찰1건과 원문4개를 보존했다. Java·합성·문항·모델 실행0이다.

License 원문2개를 얻는 동안 redirect2회를 포함한 실제 HTTP는4회였다. 처음 분류 오류와 보수적 한도3 초과를 숨기지 않고 [안전 요약](../data/evaluation/meetings-service-rag-validation-v2/safe-summary-v2.json)에 정정했다. 부모가18개 산출물 hash를 확인했다.

다음 출처는 별도로 등록한 `rust-lang/types-team`이다. 부모는 GitHub repository/ref/tree metadata만 확인했으며 root Apache/MIT license 경로와 날짜별 minutes 경로의 실제 적용·내용은 작성자와 독립 검토자가 확인해야 한다. W3C webtransport metadata 조회에서 날짜 문서를 찾지 못한 기록도 남긴다. 새 시도에서 이전 원문·거부·라이선스 기록은 바꾸지 않는다.
