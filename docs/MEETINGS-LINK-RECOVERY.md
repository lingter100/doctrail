# 결정 연결 삭제 후 지연 응답 복구

2026-10-15. 결정 연결을 삭제한 뒤 먼저 시작된 조회 응답이 도착하면 삭제된 연결이 화면에 다시 나타나는 경합을 수정했다. 실제 Java 서버에서는 삭제됐지만 React가 오래된 목록을 다시 표시하던 문제다. DB나 API 의미를 바꾸지 않고 기존 요청 소유권을 재사용한다.

## 재현과 수정

회의에L1이 표시된 상태에서L2를 추가하면 자동 상세/연결 조회가 시작된다. 그 실제 Java GET 응답을 보류한 사이L1을 해제하면 서버는204를 반환하고L2만 남는다. 이전 응답을 늦게 전달하면 원래 화면은L1·L2를 다시 표시했다. 첫 재현은0통과/1실패였으며 결과·trace·화면을 보존했다.

성공한 DELETE는 이전 상세/연결 요청을 무효화하고 해당 항목을 즉시 제거한 뒤 새 요청으로 남은 연결을 확인한다. 실패한 DELETE에서는 기존 연결을 유지하고 명시적 재시도만 허용한다. 작업공간 이동 뒤 늦은 성공 응답은 이전 회의를 다시 열지 않는다.

첫 수정의20개 통과 뒤 부모 검토가 별도 문제를 찾았다. 실패 안내의 ‘새로 불러오기’가 진행되는 중 연결을 삭제하면 이전 refresh의 finally가 무효화돼 `refreshing`이 남을 수 있었다. 새 조회도 실패하면 재시도 버튼이 계속 비활성 상태였다. 이 경로도 첫 실행0통과/1실패로 재현한 뒤 삭제 성공 시 취소한 refresh 상태를 함께 해제했다. 최종 검사는 다시 명시적으로 누른 GET200까지 확인한다.

## 최종 검증

| 실제 Java·패키지 React 검사 | 결과 | 시간 |
|---|---:|---:|
| 새 연결 복구 | 4통과 | 8.779초 |
| 기존 편집 충돌 | 5통과 | 10.630초 |
| 기존 목록 실패 복구 | 9통과 | 17.427초 |
| 기존 회의 흐름 | 3통과 | 14.978초 |

최종 batch `kApN5c` 합계21통과/0실패/0skip/0flaky이며 각 서비스의 packagedUi/serverStopped를 확인했다. TypeScript와 production build도 통과했다. Maven `-DskipTests package`는 패키징 검증이고 Java 전체 테스트 주장은 아니다. 원본 실패 두 batch와 중간20통과는 최종 결과와 구분한다.

[검증 영수증](../experiments/results/meetings-link-recovery-v1.json) SHA256 `84c62a511eb0ab74a39684f9a25a1db9f443f53680656e8b133e5e542fd49051`에 source3·모든 run/report·화면 hash를 기록했다. 부모 AI가 최종 화면의 삭제 안내와 살아 있는L2만 표시되는 상태도 확인했다. 모델 전송은 명시적 합성 fixture이고 일부 HTTP 오류/전달 지연을 주입했다. 실제LLM0·사용자검수0이며 일반 장애 빈도나 모델 품질을 측정한 결과가 아니다.

```powershell
npm --prefix web run typecheck
npm --prefix web run build
./server/mvnw.cmd -B -q -f server/pom.xml -DskipTests package
npm --prefix web run test:e2e -- meeting-link-recovery.spec.ts meeting-ready.spec.ts meeting-conflict-recovery.spec.ts meeting-list-state.spec.ts
```

브라우저 요청 취소는 이미 완료된 서버 쓰기를 되돌리지 않는다. 저장 실패를 자동 재요청하지 않으며 화면 복구는 현재 세션 메모리 범위다. 원격 필수 CI는 커밋 뒤 STATUS에 별도로 기록한다.
