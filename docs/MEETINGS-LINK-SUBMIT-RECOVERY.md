# 결정 연결 저장 중 입력과 접근 권한 복구

2026-10-20. 실제 Java 서비스와 패키징된 React 화면에서 재현한 세 동작을 수정했다.

- 연결 대상으로 선택한 회의가 비공개로 바뀌어 POST가404를 반환해도 대상 제목·결정·저장 선택이 남았다. 새로고침도 대상 목록을 다시 읽지 않았다.
- 연결 POST의 성공 응답이 늦는 동안 취소하고 폼을 다시 열어 입력하면 이전 응답이 새 폼을 닫았다. 서버에는 먼저 보낸 내용만 저장됐다.
- 중간 수정에서 현재 회의 자체가 삭제된 POST404가 발생해도 수동 새로고침 전까지 현재 회의가 남았다. 이를 추가로 재현해 보완했다.

## 최종 동작

연결 POST403/404는 어느 쪽 접근이 거부됐는지 단정하지 않는다. 대상·링크 캐시와 선택을 먼저 무효화하고 현재 회의에 읽기 요청을 보내 다시 확인한다. 현재 회의도 거부되면 기존 전체 무효화 경로로 화면과 캐시를 지운다. 접근 가능한 현재 회의의 인용 초안은 유지하지만 양쪽 회의를 명시적으로 새로 조회하고 결정을 다시 선택해야 저장할 수 있다.

저장과 접근 확인이 끝날 때까지 연결 필드·취소·폼 닫기를 잠그고 상태 문구를 표시한다. 실패하면 초안을 유지하고 조작을 복구한다. 재시도나 변경 저장을 자동으로 수행하지 않는다.

수정은 `useMeetings.ts`, `MeetingViews.tsx`, 새 `meeting-link-submit.spec.ts`, 테스트 fixture를 등록하는 `test-java.mjs` 네 파일이다. C7 동결77파일이나 모델 동작을 바꾸지 않았다.

## 확인한 결과와 보존한 실패

최종 실제 Java browser 검사는7개 파일의 **39통과/실패0/skip0**다. 신규4·연결 삭제4·상세 복구10·편집 충돌5·저장 대기2·출처 접근11·준비된 회의 흐름3을 확인했다. 브라우저 보고 합계99.315초, 실행 명령 합계143.108초이며 모델 응답 시간 측정이 아니다.

타입 검사·화면 빌드·오프라인 Maven 패키징도 통과했다. 패키징은 `-DskipTests`를 사용했으므로 이 단계에서 Java 단위 테스트를 실행한 것으로 기록하지 않는다. 최종 커밋의 필수 CI는 별도로 확인한다.

초기 테스트 문법 오류, 잘못된 작업공간/selector 설정3실패, 수정 전 실제 동작3실패, 중간 source404 경계1실패를 각각 보존했다. 서로 겹치는 중간 통과 수를 최종39에 합산하지 않는다. 추출·답변 transport와503 주입은 합성 fixture이며 실제 LLM/tokenizer/native 호출은0이다.

네 source 파일의 명시적 hash checkpoint는 신규4개 검사 직후에 기록됐고 남은35개 검사와 현재 파일은 같다. 전체39 실행 직전 hash를 측정했다고 주장하지 않는다. 최종 빌드 이후 수정은 없었으며 정확한 커밋 CI로 검증을 보완한다.

테스트용 Java7개는 모두 종료됐고 다른 프로젝트의 JVM3개를 건드리지 않았다. 저장 대기 모바일 화면과 대상 접근 거부 후 데스크톱 화면2개를 AI가 확인했다. 가로 넘침이나 읽을 수 없는 상태 안내는 관찰하지 않았으며 사용자 검수는0이다.

## 증거와 재현

[공개 검사 결과](../experiments/results/meetings-link-submit-recovery-v1.json)는 local 공개용 projection의 exact copy다. [공개 복사 기록](../experiments/results/meetings-link-submit-publication-v1.json)에 local 원본44980a57·공개본87b8399c·확인한 코드4개/원본 artifact33개의 범위를 기록했다. 원본의 `publication=false`·`ci_claim=false`는 생성 당시의 실행 범위이며 이 복사를 서비스 배포로 해석하지 않는다.

기존 개발 환경과 Maven 캐시에서:

```powershell
npm --prefix web run typecheck
npm --prefix web run build
.\server\mvnw.cmd -o -B -q -f server/pom.xml -DskipTests package
npm --prefix web run test:e2e -- tests/meeting-link-submit.spec.ts tests/meeting-link-recovery.spec.ts tests/meeting-detail-recovery.spec.ts tests/meeting-conflict-recovery.spec.ts tests/meeting-save-pending.spec.ts tests/meeting-source-access.spec.ts tests/meeting-ready.spec.ts
```

실행기는 각 spec에 격리된 데이터베이스와 Java 서비스를 사용한다. 외부 모델이나 사용자 문서가 필요하지 않다. 실제 모델의 의미 품질·실서비스 지연·배포 완료는 이 검사로 입증되지 않는다.
