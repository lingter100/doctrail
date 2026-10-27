# 회의 상태의 실제 Java 백업·복원 검증

현재 상태: 실제 Java와 합성 회의·HTTP 분석 응답으로12개 운영 항목을 통과했다. 최종 CLI exit0, 전체11.60초이며 관련56회귀 검사와 독립 코드 검토를 마쳤다. 앞선 인코딩·관찰기 실패를 보존했다. [실측 결과](../experiments/results/meetings-java-restore-v1.json)를 참고한다. 모델 품질이나 사용자 검수 결과는 아니다.

## 검증하는 사용자 흐름

기존 Java 서비스에 텍스트 회의2개를 등록한다. 분석 저장 후 요약과 담당 작업을 사용자가 편집하고, 결정2개를 확인해 명시적인 변경 링크를 연결한다. 비공개 회의는 다른 작업공간 구성원에게 숨겨지고 공유 회의는 읽혀야 한다.

서비스를 종료하고 같은 DB에서 재시작한 뒤 보존 상태를 확인한다. 다시 종료해 SQLite 백업을 만들고 별도 새 경로로 복원한다. 복원 전 로그인 쿠키는 거부돼야 하며, 재로그인 후 원문·요약·AI 초안·사용자 편집 이력·완료 작업·결정 링크·근거 좌표가 같아야 한다. 복원 뒤에는 분석 서비스를 끄고 BM25 검색과 원문 이동만 사용한다.

검사는 무결성·외래키와 관련 테이블의 값, 원본/백업 파일의 불변성, 인용의 Unicode 코드포인트 좌표를 확인한다. 다른 구성원의 공유 자료 접근 성공과 비공개 자료 접근 거부를 함께 검사한다.

## 재현 명령

기존 설치·Java 패키징 방법은 [Java 전환 안내](JAVA-MIGRATION.md)를 따른다. 이미 빌드한 JAR의 해시를 호출자가 명시하며 이 보조 도구가 빌드·다운로드·모델 호출을 수행하지 않는다. JAR 해시 지정은 사용하려는 파일의 동일성을 고정하는 절차이며 임의 파일의 신뢰성을 보증하지 않는다.

```powershell
$jarPath = 'server/target/doctrail-server-0.1.0.jar'
$expectedJarSha = (Get-FileHash -LiteralPath $jarPath -Algorithm SHA256).Hash.ToLowerInvariant()
.\.venv\Scripts\python.exe -B -X utf8 -m scripts.verify_meeting_operations_companion `
  --jar $jarPath `
  --expected-jar-sha256 $expectedJarSha `
  --output .local/meeting-operations-manual-01 `
  --execute-synthetic-java
```

출력 경로는 저장소 `.local` 아래의 **아직 없는 폴더**여야 한다. 이미 있는 실행을 덮어쓰지 않는다. 실패를 수정한 뒤 다시 검사할 때도 새 폴더를 사용한다. 실행 결과의 `report.json`과 실제 명령 종료 코드를 함께 확인한다. `private` 안에는 합성 DB·로그·원본 API 응답이 있으므로 전체 폴더를 공개 산출물로 올리지 않는다.

## 구현 선택과 해석의 한계

기존 `verify_java_service.py`는 동결 실험에 결속돼 있어 변경하지 않는다. 새 companion은 그 파일의 Java 실행·HTTP 검사 함수와 기존 SQLite 백업 함수, 기존 Node 전송 fixture를 가져다 사용한다. 서비스 구현이나 별도 테스트 서버를 복제하지 않는다.

Java 서버는 루프백 주소로 제한하고, 검사에서 만든 Java·Node 프로세스만 종료한다. helper 모듈의 subprocess 참조만 제한적으로 감싸 동일한 실제 생성 핸들을 보관한다. 전역 Popen이나 기존 helper 파일·정리 동작은 바꾸지 않는다. 종료 정보 기록 후 자체 참조를 해제하고 하나의5초 기한 안에서 신원의 부재를 확인하며, 불확실한 종료·접근 거부·지속되는 동일 신원은 실패다. 본문 실패 뒤 정리 오류가 발생해도 원래 실패를 유지하고 후행 오류를 별도로 남긴다. 환경 설정은 검사 후 복원한다.

이번 통과 결과도 실제 LLM의 요약 정확성·답변 품질, 브라우저 외관·사용성, 부하·장애 중 백업, 공개 서비스 배포가 검증되는 것은 아니다. 사용자 직접 검수와 최종 AI 평가는 별도다. 이번 검증은 정지된 서비스의 회의 상태를 새 DB로 안전하게 복원하는 범위다.

## Windows 출력 인코딩

Python은 위 명령처럼 -X utf8로 실행한다. 보조 도구는 자식 JVM의 stdout.encoding과 stderr.encoding을 UTF-8로 고정하고 Python의 실제 기본 해독기가 UTF-8인지 시작 전에 확인한다. 이는 [Java 21 System 문서](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/lang/System.html)의 스트림 인코딩 속성을 사용한다. Windows 전역 환경이나 동결 helper를 바꾸지 않으며 상속 JVM 설정을 제거하고 검사 뒤 원래 환경을 복원한다. 첫 실패와 후속 결과는 별개 출력 폴더로 보존한다.

## 2026-10-27 공개 원문 보정 fixture 확장 후 결속 갱신

수동 보정의 공개 원문 검사를 명시 opt-in으로 추가하면서 합성 transport 파일이 바뀌었지만 companion의 고정SHA는 옛 값을 유지했다. b16d5ed의 양쪽 CI가 Java 시작 전 binding-preflight/helper_or_fixture_binding으로 실패했다. 원래 보고서·ZIP·로그를 보존했으며 복원 동작의 실패로 분류하지 않는다. [최초 CI 실패](../experiments/results/meetings-manual-engine-source-ci-v1.json)를 참고한다.

기본 호출의 옵션은 false이고 기존 companion은 인자 없이 호출한다. 공개 분기와 관련 import/false-default 옵션만 제외하면 이전 정규화 소스와 일치함을 확인했다. guard를 없애지 않고 fixture SHA 한 문자열만 현재 게시 바이트에 맞췄다. 기존56합성검사5.23초/Ruff를 통과했고 테스트 본문은 변경하지 않았다.

이미 검증한 별도 복사본 JAR와 명시Java21에서 새 합성DB로 실제 companion1회를 실행해14.781초에12항목을 통과했다. setup/restart/restored Java3회와 소유 프로세스 종료·부재를 확인했고 fixture는 분석2회/답변0회였다. 원래 JAR·개인 DB·이전 CI 실패는 보존했다. [수정 결과](../experiments/results/meetings-operations-fixture-binding-repair-v1.json)는 정확 게시 소스 CI·실제 AI 품질·사용자 검수와 별개다.
