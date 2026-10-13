# M4 · 학습 저장본의 실제 로컬 운영 결과

2026-10-13, 실행 전 고정 커밋 `61285dd20801a3beb1976adb6142a4218304fa14`, 작업 트리 변경 없음. [사전 설계](M4-OPERATIONS-DESIGN.md)에 따라 실제 로컬 CUDA worker와 Java 21·React 화면을 실행했고 **운영 검사16묶음이 통과**했다. [보고서](../experiments/results/m4-terminal-service-v1.json)와 [단계 journal](../experiments/results/m4-terminal-service-v1.progress.jsonl)은 원본 바이트 그대로다.

이 결과는 학습 모델의 기본 채택이나 새로운 검색 품질 평가가 아니다. 기본 검색은 BM25, 원래 base 실행기는 유지하며 terminal은 명시적인 실험 실행 경로다. 합성 자료의 자동 검사이며 사용자 검수는0이다.

## 문제와 선택

학습 후 오프라인 점수가 올라도 서비스에서 잘못된 가중치를 연결하거나, 문서를 삭제한 뒤 예전 벡터를 반환하거나, 모델 교체 후 이력을 잘못 해석할 수 있다. 이를 막기 위해 checkpoint manifest와 공개 학습 영수증을 검증하고, Java가 health와 각 embedding 응답의 model/revision을 확인하도록 했다. 성공한 검색의 모델은 별도 DB metadata로 저장한다.

기존 실행기를 바꾸는 대신 별도 terminal worker·launcher·검증기를 추가했다. 이전 실험 소스를 보존하면서 base 복귀를 실제로 비교하기 위해서다. 원래 tokenizer·FP32 E5·FP16 BGE·512토큰·후보 정책도 유지했다. 브라우저의 profile 조건은 모델 선택 권한이 아니라 오래된 화면의 검색을 거부하는 장치다.

## 실제 수행한 범위

| 검사 | 확인한 결과 |
|---|---|
| 모델·파일 | Terminal/base/BGE 파일과 영수증 검증. Terminal manifest revision 일치, CUDA E5 FP32/BGE FP16 |
| 화면 산출물 | 실제 Java가 제공한 HTML·JS·CSS 바이트가 빌드 해시와 일치. 실행 전후 source/JAR/dist 동일 |
| 세션·권한 | 비회원 작업공간 검색404, 개인 문서 접근·수정·재처리·삭제404. 모든4방식에서 현재 허용 문서만 반환 |
| 권한 회수 | Workspace 문서를 private로 바꾸면 회원의 검색·원문·피드백에서 제외, 이력의 가시 근거 수도0 |
| 근거·갱신 | 현재 원문·Unicode offset·revision 일치. 수정과 동일 본문 재처리 후 chunk ID 교체, 과거 피드백409 |
| 삭제·cache | 삭제 문서가 모든 검색에서 제외. 실제 terminal passage 호출의 miss→hit→본문 변경 miss 관측 |
| 이력·복구 | 성공한 모델 identity 저장. 같은 임시 DB로 base에 복귀해 검색 성공, terminal 이력 보존. 오래된 profile 재실행409·새 이력 없음 |
| 장애 | 실제 terminal worker 종료 후 모델 검색503·실패 이력 없음. 기본 BM25는 계속 검색 성공 |
| 실제 브라우저 | 등록·업로드·모델3방식·원문·피드백·이력 재검색 통과. 데스크톱·390px 화면, 가로 넘침/미처리 오류 없음 |
| 로그·정리 | 지정 원문/질문·비밀번호·세션·내부 token sentinel이 로그에 없음. 소유 terminal/base 프로세스 종료·임시 DB 삭제 |

느린 추론 중 권한·문서 변경, timeout·busy·응답 identity 교체 같은 결정적 경합은 base/terminal 양쪽 **합성 worker Java 검사**로 확인했다. 실제 GPU의 순차 HTTP 검사와 이 모의 검사를 혼동하지 않는다. 브라우저 screenshot도 AI가 확인했으며 사람의 사용성 평가가 아니다.

## HTTP 시간: 원시 관측, 성능 비교 아님

아래는 가시 합성 문서2개/청크2개의 순차 요청이며 같은 worker와 cache를 공유한다. 각 방식의 첫 요청이 전체 cold start를 의미하지 않는다. 전체 코퍼스·동시 부하·p95·운영 SLO로 확대할 수 없다. Python 오프라인 평가 시간과도 다르다.

| 방식 | 첫 HTTP(ms) | 반복 HTTP(ms) | 첫 Java 처리(ms) | 반복 Java 처리(ms) |
|---|---:|---:|---:|---:|
| BM25 | 39.414 | 24.646 | 12.78 | 6.06 |
| Dense | 624.795 | 97.174 | 585.00 | 66.06 |
| Hybrid | 99.134 | 96.427 | 73.48 | 62.53 |
| Hybrid + reranker | 631.490 | 206.400 | 596.48 | 184.53 |

정확한 원시값은 보고서를 기준으로 한다. Worker+Java 준비 시간은 terminal 약32.78초(부모의 파일 사전 검사 제외), base 약21.24초였다. 실행 순서·파일 cache·사전 검사 경계가 다르므로 시작 속도 우위를 비교하지 않는다. 로컬 RTX4050 6GB에서 실행했지만 이 운영 검사에서 peak GPU 메모리·전력·금액은 측정하지 않았다. 유료 API·GPU 임대·클라우드 사용은0이다.

## 실패와 검증의 한계

전체 브라우저 회귀의 첫 실행은20통과/2실패였다. 같은 임시 서버에 추가 테스트의 가입이 누적되어 정상 인증 제한20회/분에 걸렸다. 보안 제한을 완화하거나 재시도로 숨기지 않고, 검사 파일마다 별도 Java·DB를 사용하도록 고쳤다. 이후22개가 통과했고 파일+grep 선택 검사1개도 통과했다. 실패·성공 trace와 실행 로그는 `.local`에 보존한다.

잠금 후속 수정까지 포함한 최종 로컬 검증은 Python518개, Java82개, Playwright22개(Chromium19·순수 helper3), 실제 기본 Java HTTP11묶음, 타입 검사·production build·Ruff 통과다. 신규 Python 계약40개는 모델 없는 합성 검사다. 기존 Starlette/httpx 사용 중단 경고1개와 Java 테스트 도구 경고가 남는다. 원격 CI는 무거운 모델을 실행하지 않으며 별도 상태로 기록한다.

Main-dev의 다중 문서 @5 퇴보1→0/7과 전체 @5 퇴보6개는 그대로 남아 있다. 이번 합성 시나리오 통과로 그 문제가 해결된 것은 아니다. Terminal을 연결한 hybrid/rerank의 새로운 품질 평가도 하지 않았다. 규모 상한4096청크, 직렬 모델 요청, 메모리 cache, 질문/화면 사용자 검수0, 생성 답변 미구현, 최종 test 잠금, 공개 서비스 배포0이다.

## 재현과 다음 단계

[실행 안내](MODEL-SERVING.md)의 설치·빌드 후 새 출력 폴더로 실행한다. 이미 있는 폴더는 거부하고 실패도 report/journal을 남긴다. 실제 검증은 임시 DB만 사용한다. 모델 재학습이나 완료 평가 재실행은 이 명령의 일부가 아니다.

```powershell
uv run --locked --group retrieval --no-sync python -m scripts.verify_terminal_service --browser --output-dir .local/m4-terminal-service-new-attempt
```

Public report SHA-256: `bf99571b9dd547b8a26be6646c1866daae80546cc889144df5abca3ab4c66054`. Journal SHA-256: `0acac1d0369849111f28684338aaadf40db17479dcb5426c5dc1b07f1f887a77`. Raw 로그·임시 데이터·모델 가중치·cache는 커밋하지 않았다.

다음은 M5 근거 기반 답변·보류 설계다. 다중 문서 근거 누락과 미주석 대체 정답을 고려해 검색 점수와 답변 가능성을 구분하고, 로컬 생성 모델의 자원·라이선스와 인용 검증 조건을 먼저 확인한다. 이 단계에서 기존 dev/test를 다시 튜닝 자료로 쓰지 않는다. 사용자가 직접 판단할 부분은 질문 라벨의 타당성, 실제 문서 탐색·근거 읽기의 편의성, 향후 유료·공개 배포 승인이다.

### PR 검토 후 잠금 정리 보완

자동 코드 리뷰에서 검증 도중 잠금 파일이 외부에서 삭제·교체되면 기존 실행이 새 실행의 잠금을 지울 수 있음을 지적했다. 생성 당시 임의 소유권 token과 파일 identity를 기록하고, 종료 때 둘 다 일치하는 일반 파일만 정리하도록 보강했다. 교체된 실행 잠금·같은 파일의 token 변경·복사 token의 새 파일·이미 사라진 잠금을 회귀 검사한다. 협력적 파일 표식이므로 운영자가 살아 있는 lock을 강제로 삭제하거나 최종 확인 직후 공격적으로 교체하는 경우까지 원자적으로 방어하는 OS 잠금은 아니다. 실행 중 lock을 수동 삭제하지 않는다.

이 수정은 실행기 lifecycle만 바꾼다. 위 실제 GPU 보고서는61285dd의 역사적 증거로 그대로 보존하며 수정 후 실측인 것처럼 표시하지 않는다. 모델·검색 정책·Java·React는 바뀌지 않았고 CUDA나 완료된 품질 평가는 재실행하지 않았다. 후속 모델 없는 회귀 결과와 필수 CI는 STATUS에 기록한다.
