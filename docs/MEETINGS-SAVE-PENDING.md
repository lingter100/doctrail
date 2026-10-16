# 저장 응답 대기 중 편집 유실 복구

2026-10-16. 실제 Java의 저장 성공 응답을 지연해 문제를 먼저 재현하고, React 입력 잠금으로 수정했다. 로컬 최종 관련 브라우저23개가 통과했다. 모델 분석 전송은 명시적 합성 fixture이며 실제LLM·사용자검수는0이다.

## 문제와 수정

회의 분석은 요약·메타데이터 근거·항목·담당자·상태를 하나의 CAS 요청으로 저장한다. 저장 버튼을 누른 순간의 스냅샷을 보낸 뒤에도 입력18개가 활성화돼 있었다. 사용자가 응답을 기다리며 요약·담당자·상태를 추가로 바꾸면, 이전 스냅샷의 성공 응답이 편집기를 닫아 추가 입력이 사라졌다. 서버가 저장한 값은 요청과 일치하므로 서버 CAS만으로 이 화면 문제를 막을 수 없다.

전체 분석 입력을 하나의 disabled fieldset으로 묶고 저장 중이라는 설명을 표시한다. form submit에도 busy 검사를 추가한다. 성공 후 다시 편집하면 입력이 활성화되고, 실패하면 기존 초안 그대로 다시 활성화된다. 자동 재저장이나 새 상태 저장소는 추가하지 않는다. 기존409 충돌 복구의 명시적 로컬/서버 선택도 유지한다.

응답 뒤 추가 편집을 병합하는 대안은 별도 dirty snapshot·CAS 기준 관리가 필요하다. 현재 짧은 저장 요청 동안 입력을 잠그는 것이 기존 화면 구조에 맞고 저장한 범위를 명확하게 보여준다. 페이지 이동·새로고침까지 초안을 영구 보존하는 기능은 이 변경의 범위가 아니다.

## 실제 재현과 검사

- 첫 `.local/web-e2e-batch-Tpd4ig/web-e2e-wg9M5v` 실패는 label locator 시간 초과이며 제품 결함의 증거와 구분한다.
- 수정 전 `.local/web-e2e-batch-y9FydU/web-e2e-IlzCp0`에서 실제 Java PUT 성공 응답만 보류했다. 서버 version이 이미 증가한 것을 확인하고, 화면은 추가 요약·담당자·done을 받았다. 응답을 풀자 편집기가 닫히고 서버에는 앞서 제출한 요약·담당자·doing만 남았다. 활성18개와 전후 값, baseline component/test를 보존했다.
- 최종 `.local/web-e2e-batch-fEzRhN`은 새2 + 충돌5 + 연결4 + 목록9 + 기존회의3 = **23통과/0실패/0skip/0flaky**다. 실제 Java/SQLite/세션/분석 CAS/packaged React를 사용했고5개 spec 모두 서버 종료를 확인했다.
- 새 성공 검사는 모든 입력의 disabled, 실제 제출 스냅샷 저장, 완료 후 재편집을 확인했다. 별도 합성PUT503은 Java에 전달하지 않고 주입했으며, 초안 유지·편집 재개·PUT1회/자동 재시도 없음을 확인했다. 합성503을 실제 Java 장애로 기록하지 않는다.
- TypeScript/build/Java21 package-DskipTests가 통과했다. package는 전체 Java 테스트를 실행했다는 뜻이 아니다. 390px 대기 화면은 부모와 구현 역할이 저장된 스크린샷에서 확인했으며 사용자 검수는 아니다.

```powershell
npm --prefix web run typecheck
npm --prefix web run build
./server/mvnw.cmd -B -q -f server/pom.xml -DskipTests package
npm --prefix web run test:e2e -- meeting-save-pending.spec.ts meeting-conflict-recovery.spec.ts meeting-link-recovery.spec.ts meeting-list-state.spec.ts meeting-ready.spec.ts
```

## 보존 정보

`experiments/results/meetings-save-pending-v1.json` SHA`8908c6a45e8e044d3526e849f7a7a0d16eaf51ff372ce3989e73cb7eee102f0b`에 source3·원본 실패·최종23검사·스크린샷·합성 경계가 연결돼 있다. 최종 batch SHA는`82b00e0f93be3aa2554b6bfa55e49e834caa1d3ae8918359090a88c32ecee1e5`다.

로컬 검사 뒤 component만 CRLF→LF로 정규화했다. 영수증에는 검사 당시SHA와 커밋할SHA를 둘 다 남겼고 그 외 byte 변화는 없다. 이 정규화 이후의 canonical source 원격 CI는 STATUS에 별도 기록한다. 기존 frozen 모델 소스·자료는 바꾸지 않았다.

이번 수정은 실제 입력 유실 문제를 막은 것이며 회의 분석이나 자연어 답변 정확성의 증거가 아니다. 일반 문서/복수 회의 질의응답 품질과 Phase1 전체 완료는 아직 남아 있다.
