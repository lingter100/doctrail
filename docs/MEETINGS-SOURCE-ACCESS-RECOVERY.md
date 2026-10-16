# 회의 원문 접근 거부와 편집 복구

2026-10-16. 회의 화면에서 전체 원문이나 근거 문장을 열 때 서버가 접근을 거부해도, 이전에 읽은 회의 요약·작업·결정 연결이 남는 문제를 수정했다. 일반 문서 검색의 공용 원문 패널에 회의 화면의 요청 소유권과 접근 거부 처리를 연결했다.

현재 회의의403/404는 상세·목록·작업과 진행 중인 관련 응답을 무효화한다. 사용자가 목록을 다시 확인하기 전까지 기존 결과를 보여주지 않는다. 외부 연결 회의의 원문만 차단되면 현재 회의와 편집 초안을 유지하고 연결·대상 후보를 비운다. 다른 회의나 작업공간으로 이동한 뒤 도착한 과거 실패는 새 화면에 적용하지 않는다. 일시적인500/503에서는 내용을 권한 문제로 지우지 않는다.

충돌 복구용 `recovery.links`도 같은 범위에서 비운다. 이를 빠뜨리면 실제404를 처리한 직후 연결을 숨겨도, ‘서버 버전 사용’ 또는 ‘내 초안 유지’를 선택할 때 과거 연결이 다시 나타난다. 이 경로 역시 수정 전에 실제 Java에서 재현했다. 자동 저장이나 실패 요청의 자동 재전송을 추가하지 않았다.

## 실제 확인과 남은 한계

최종52개는 Java21 + 다시 빌드한 packaged React + Chromium에서 통과했다. 신규11, 상세10, 충돌5, 연결4, 저장2, 목록9, 기본3, 지식 검색 원문8개이며 실패·skip·flaky는0이다. 모든8개 실행의 소유 JVM 종료도 확인했다. 타입 검사·React 빌드·Java 패키징이 통과했고 패키징의 `-DskipTests`는 Java 단위 테스트 실행으로 세지 않는다.

권한 변경→404는 실제 Java 응답이다. 403과500/503은 해당 오류 경로를 확인하려고 명시적으로 주입했다. AI 분석·답변은 결정적인 합성 transport fixture를 사용했으므로 실제 LLM 호출은0이다. 이 검사는 화면·권한·비동기 복구의 근거이며 모델 의미 품질이나 실제 사용자 검수의 근거가 아니다. 서버 응답 전까지 권한 변경을 즉시 알아내는 기능은 아니다.

최초2실패는 현재 회의의 원문404 뒤 상세가 남는 제품 결함이다. 이 baseline은 기존 packaged UI를 재사용했고 runner가 index와 dist 일치를 확인했다. 최종 검사는 명시적으로 빌드·재패키징했다. 추가1실패는404 뒤 서버 버전을 선택할 때 연결이 복원되는 제품 결함이다. 별도 중간 검사에서 selector4실패와 최초 links GET보다 권한을 먼저 바꾼 준비 race1실패도 보존했다. 이들은 테스트 준비 문제로 분류하고 제품 결함과 합산하지 않는다.

최종 소스4개와 원본148개 artifact hash를 부모가 대조했다. [로컬 검증 영수증](../experiments/results/meetings-source-access-recovery-v1.json)은 SHA `dd4aa1ba9debdd8819a4f53864970b4e95a6d92aafd14176b178aca3425777c8`의 정확한 복사본이고 [공개 복사 기록](../experiments/results/meetings-source-access-recovery-publication-v1.json)은 별도다. 원본은 `.local/meetings-source-access-v1/`에 유지한다. 영수증의 CI·commit0은 로컬 검증 당시 상태이며 후속 Git/CI 결과는 STATUS에서 확인한다.

## 재현 방법

Java21 환경에서 React 빌드와 Java 패키징을 마친 뒤 실행한다. 테스트 runner가 임시 DB·Java 서버·합성 모델 transport를 준비하고 정리한다.

```powershell
npm --prefix web run typecheck
npm --prefix web run build
./server/mvnw.cmd -B -q -f server/pom.xml package -DskipTests
$env:DOCTRAIL_E2E_SPEC = 'meeting-source-access.spec.ts'
npm --prefix web run test:e2e
Remove-Item Env:DOCTRAIL_E2E_SPEC
```

실제 사용자는 두 계정으로 공유 회의를 연 뒤 소유자가 비공개로 바꾸고, 이미 열린 화면에서 전체 원문/근거를 눌러 복구 동작을 확인할 수 있다. AI가 수행한 검사와 사용자가 직접 확인한 내용은 [기여 기록](CONTRIBUTIONS.md)에서 구분한다.
