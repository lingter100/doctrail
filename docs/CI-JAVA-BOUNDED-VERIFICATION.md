# Java CI의 시간 상한과 안전한 실패 기록

2026-10-26 · 기존 Astra xhigh의 운영 설계 · 구현·실행 전 제안

**다음 변경은 기존 Maven 검증에 시간 상한을 두고, 실패 시 안전하게 추린 진단만 보존하는 것이다.** 현재 실행을 고치거나 재시작하는 작업이 아니다.

부모 관측에서 head `8f3fa342`의 push `40273275050`은 Maven 단계가 장시간 진행 중이었고, 같은 head의 PR `40273280275`는 해당 단계 34초·필수 3개 성공이었다. 현재 원격 로그·스택이 없어 지연 원인은 미확인이다. `ApiIntegrationTest:123`의 ExecutorService close가 작업 종료를 기다릴 수 있다는 정적 조건은 실제 원인 증명이 아니다. compact 후보 코드와의 인과관계도 확인되지 않았다.

현재 POM의 Spring Boot 3.5.16 캐시 메타데이터는 Surefire 3.5.6과 JUnit 5.12.2를 지정한다. 버전 업그레이드·새 실행 프레임워크 없이 이 기능을 사용한다. `server/pom.xml`, 제품 코드·기존 테스트, 동결 runtime/JAR와 compact source2는 수정하지 않는다.

| 경계 | 제안할 고정값 | 의미 |
|---|---:|---|
| JUnit test/lifecycle method | 120초 | timeout 직전 thread dump 후 같은 실행 스레드에 interrupt; 강제 종료 보장은 아님 |
| Surefire fork | 300초 | 멈춘 테스트 JVM을 제한하고 Maven 실패로 반환 |
| Maven verify step | 10분 | 의존성 처리·컴파일·테스트·패키징 전체의 Actions 상한 |
| 안전 요약 / 업로드 step | 각각 1분 | 진단 작업 자체의 대기 제한 |
| java-service job | 30분 | 기존 Java·운영·브라우저 검증을 포함한 job 전체 상한 |

Maven 단계에는 `-Dsurefire.timeout=300 -Djunit.jupiter.execution.timeout.default=120s -Djunit.jupiter.execution.timeout.thread.mode.default=same_thread -Djunit.jupiter.execution.timeout.threaddump.enabled=true -Dmaven.test.redirectTestOutputToFile=true`를 추가한다. 기존 forkCount=1/reuseForks=true 및 종료 유예 기본값은 바꾸지 않는다. JUnit은 interrupt 전에 dump를 만들며, interrupt를 무시하는 close/task는 Surefire fork 상한으로 제한한다. [JUnit 5.12.2](https://docs.junit.org/5.12.2/user-guide/#writing-tests-declarative-timeouts-debugging), [Surefire 3.5.6](https://maven.apache.org/surefire-archives/surefire-3.5.6/maven-surefire-plugin/test-mojo.html)

Maven 명령은 같은 wrapper와 `verify`를 유지한다. `-q`만 제거하고 `--no-transfer-progress`를 사용해 단계 정보를 남기되 stdout/stderr는 runner 내부 파일로만 받는다. `tee`나 실패 시 원본 log 출력은 하지 않는다. 시작 metadata를 먼저 저장하고, 정상 반환 시 원래 exit code와 종료 시각을 기록한 뒤 같은 코드로 step을 끝낸다. timeout·테스트 실패를 성공으로 바꾸는 `continue-on-error`, retry, SkipTests, 테스트 제외는 추가하지 않는다.

설정상 Maven은 step 시작+10분과 job 시작+30분 중 먼저 도달하는 한계의 적용을 받는다. 이는 GitHub가 집행하는 timeout이며, OS 장애까지 정확한 시각의 종료를 보장한다는 뜻은 아니다. 후속 `if: always()`도 runner 소실·job 전체 취소 때 업로드를 보장하지 못한다. exit 기록이 없으면 `exit_code=null / termination_unobserved`로 남기고 원인을 timeout이나 특정 테스트로 단정하지 않는다. [GitHub timeout 문서](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idstepstimeout-minutes)

안전 요약과 업로드는 Maven 직후에 배치하며 성공·실패 모두 실행한다. 기존 3개 필수 job·그 이후 검증은 유지한다. 같은 job의 Maven 실패 후에는 기존 성공 의존 단계가 건너뛰어져야 하고, 진단 단계가 그 실패를 덮지 않는다.

최소 구현 파일은 기존 `.github/workflows/ci.yml`과 NEW 순수 보고서 projection/test 2개로 제한한다. projection은 프로세스를 실행하지 않고, 해당 실행의 Maven 로그·Surefire XML/출력·dump만 읽는다. 기존 Maven/JUnit이 실행·중단·dump 생성을 담당한다. 별도 JVM/PID 감시기나 일반 runner는 만들지 않는다.

공개 artifact는 고정된 `safe-report.json`과 `safe-thread-stacks.txt`만, 기존 SHA-pinned upload-artifact로 3일 보존한다. 보고서에는 run/attempt/head, 고정 한도, 관측 시각·exit/step outcome, 허용된 Maven 단계명, suite별 개수/시간, 누락·잘림·파싱 실패 상태, 원본 파일 크기/SHA만 담는다. stack 파일은 인식된 JUnit dump 안의 익명 thread 번호·상태·class/method/source-line frame만 남긴다. parameterized 표시 이름·thread 이름·exception message·system-out/err 본문·XML properties·환경·명령 인자·경로·인증/문서/DB 내용은 내보내지 않는다.

원본 Surefire 디렉터리, dumpstream, Maven 전체 로그를 wildcard로 업로드하지 않는다. XML의 출력/properties 억제 옵션만으로 실패 보고서가 안전하다고 가정하지 않는다. projection은 링크를 따라가지 않고 유한 크기로 읽으며 잘림을 표시한다. 공개 두 파일 합계는 1MiB 이하로 제한한다. 파싱·진단 실패도 안전한 상태로 보존하되 Maven 원래 실패가 우선이며, 진단 실패 때문에 정상 검증을 성공으로 꾸미지 않는다. Surefire dump 생성 여부는 관측값으로 남긴다. [Surefire 실패 기록](https://maven.apache.org/surefire/maven-surefire-plugin/faq.html#how-to-dump-fatal-errors-and-stack-trace-of-plugin-runtime-if-it-fails)

구현 후 검증은 다음 작은 범위로 나눈다.

- 순수 projection 검사: 성공/실패 XML, 미완성·누락 파일, dump 및 비밀 sentinel이 포함된 이름·본문을 주어 허용된 구조만 나오는지 확인한다. 잘못된 metadata를 성공으로 해석하지 않는다.
- NEW 임시 test project: 고정 wrapper·캐시의 같은 Surefire/JUnit을 offline으로 사용한다. 제품 POM·target/JAR를 건드리지 않는다. 정상 테스트 한 번은 exit 0과 집계를 확인하고, interrupt를 무시하는 합성 hang 한 번은 JUnit 2초/Surefire 10초/외부 30초의 짧은 override로 nonzero 종료·중단 전 stack·안전 기록을 확인한다. 이 수치는 검증용이며 CI의 120/300초를 바꾸지 않는다.
- 이후 새 소스의 정상 CI: 기존 전체 제품 테스트와 Java/운영/UI 검증이 그대로 실행되는지 확인한다. 로컬 동결 JAR를 재빌드하지 않는다. 임시 project의 정상/hang 검사와 플랫폼 timeout을 같은 증거로 취급하지 않으며, 실제 Actions 상한·always 보존은 새 workflow의 설정과 이후 실행 기록으로 구분해 확인한다. 현재 지연 중인 job을 합성 검증에 사용하지 않는다.

이번 작업은 문서와 설계 receipt만 작성한다. 부모 수용·로컬 설계 commit 후 좁은 구현·합성 검증·독립 검토를 따로 배정할 수 있다. 설계 자체의 원격 CI를 구현 선행조건으로 추가하지 않는다. 원격 push는 기존 run 종료 후로 분리하고, 현재 run의 관측·별도 운영 중단 여부는 부모가 결정한다. 이 담당자에게 취소·재실행 권한은 없다. 후보 모델의 기준·예산·실제 품질 검증 경로는 그대로 유지하고, 이번 예방·관측 개선을 기존 CI 지연의 원인 수정으로 보고하지 않는다.
