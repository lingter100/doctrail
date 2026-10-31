# Java 자동 검사의 시간 제한과 진단 기록

2026-10-26. 구현·로컬 검증과 독립 코드 검토 완료, 변경 소스3e323c98의 양쪽 필수 CI도 완료했다. 실제 Linux 정상 경로에서 Maven·보고서·업로드가 성공했고 내려받은 보고서의 Java232검사/실패0을 확인했다. Linux 합성 지연 종료는 별도 미검증이다. [원격 검사·진단 파일 확인](../experiments/results/java-ci-bounded-source-ci-v1.json)을 보존한다. [검증 기록](../experiments/results/java-ci-bounded-verification-v1.json)을 함께 본다. [설계](CI-JAVA-BOUNDED-VERIFICATION.md)와 [원래 실행 중단 기록](../experiments/results/java-ci-stall-v1.json)을 구분한다.

## 해결하려는 문제

같은 소스의 PR 검사는 통과했지만 push의 Maven 단계가 30분 넘게 끝나지 않았다. 부모가 해당 실행만 중단했으며, 종료 뒤 원격 로그도 조회할 수 없어 원인은 확정하지 못했다. 이번 변경은 작업을 제한 시간 안에 끝내고 다음 실패에서 진단 자료를 남긴다. 원래 장애 원인을 고쳤다는 주장은 하지 않는다.

## 동작

기존 Maven verify와 전체 제품 테스트를 유지한다. JUnit 개별 테스트·생명주기에 120초, Surefire 테스트 JVM에 300초, Maven 단계에 10분, Java job 전체에 30분 제한을 둔다. Maven의 실제 종료 코드를 그대로 사용하며 실패를 성공으로 바꾸거나 자동 재실행하지 않는다.

원본 로그는 실행 머신 내부에 남긴다. 순수 Python 도구가 단계명·종료 상태·테스트 개수·시간과 익명 스레드 정보를 추려 `java-maven-safe-<run_id>-<attempt>` artifact의 두 파일로 제공한다. 업로드 파일은 `safe-report.json`, `safe-thread-stacks.txt`이며 보존 기간은 3일이다. 테스트 이름·예외 내용·문서 내용·환경 변수는 공개 보고서 대상이 아니다.

`status: partial`은 진단 자료가 일부 없거나 제외됐다는 뜻이다. Maven 성공 여부는 `metadata.exit_code`와 원래 job 결과로 확인한다. 종료 기록이 없으면 `termination_unobserved`로 남기며 시간 초과 원인이라고 추측하지 않는다. runner 자체가 사라지거나 전체 job이 취소되면 후속 업로드도 보장할 수 없다.

## 확인한 범위

| 검증 | 실측 결과 | 해석 |
| --- | --- | --- |
| 순수 보고서 검사 | 22개 통과, 0.50초, Ruff 통과 | 잘못된 XML·누락·출력 범위·비밀 표식 처리 확인 |
| 임시 Java 정상 테스트 1회 | Maven exit0, 8.016초 | 같은 캐시의 wrapper·JUnit·Surefire 정상 실행 |
| interrupt를 무시하는 임시 테스트 1회 | Maven exit1, 14.656초 | 검증용 JUnit2초/Surefire10초로 제한; 외부30초 강제 종료 미사용 |
| 지연 진단 | 스레드7개, 제외21건, partial | 미완성 XML과 제외 프레임을 숨기지 않고 표시 |

두 실제 Java 실행은 별도 합성 임시 프로젝트를 사용했다. 제품 JAR는 다시 빌드하지 않았다. 소유 프로세스20개가 종료됐음을 확인했다. Windows 로컬 결과가 GitHub Linux runner의 모든 장애와 업로드를 보증하지는 않는다. 초기 검사 실패, 과도한 프로세스 사전 거부, UTF-16 XML 반례와 첫 불완전 스택 보고서는 원본으로 보존했다.

## 재현과 실패 확인

일반 검사: `.venv/Scripts/python.exe -B -m pytest tests/test_summarize_java_ci.py -q`.

이미 보존한 해당 실행의 입력으로 보고서를 만드는 명령은 다음과 같다. 기존 출력 폴더는 덮어쓰지 않으므로 새 경로를 지정한다. `--step-outcome`은 실제 Maven 단계 결과에 맞춘다.

```powershell
python -B scripts/summarize_java_ci.py --raw-dir .local/java-ci-private --reports-dir server/target/surefire-reports --output .local/java-ci-safe-new --step-outcome failure
```

GitHub에서는 실패한 원래 실행의 job 결과와 두 artifact 파일을 함께 확인한다. partial 보고서를 테스트 통과나 실제 모델 정확성으로 해석하지 않는다. 재실행 전에 원본 실패와 변경 이유를 남긴다. 이 작업의 실제 모델 호출·사용자 검수·공개 서비스 배포는0이다.
