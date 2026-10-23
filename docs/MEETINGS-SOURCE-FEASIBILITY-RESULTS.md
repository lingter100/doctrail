# 제한된 공개 자료 탐색 결과

2026-10-20. [고정 설계](MEETINGS-SOURCE-FEASIBILITY-PLAN.md)의 두 역할은 조회 예산을 소진하고 종료했다. **원문과 license 본문을 하나도 읽지 못했으므로 자료의 의미·크기 적합성에 관한 결과가 아니다.** 같은 작업의 예산을 늘려 계속하지 않는다.

| 관측 | Calibration | Validation |
| --- | --- | --- |
| 검색·tree 조회 | 4/4회: 검색1·디렉터리3 | 4/4회: 검색2·root tree2 |
| 요청별 검토 metadata | 20·8·5·3개 | 20·20·20·11개 |
| 선택 저장소 | 1개 | 2개 |
| 예약한 완전한 family | 0 | 0 |
| 읽은 원문 / license 본문 | 0 / 0 | 0 / 0 |
| 실제 네트워크 오류 / 무결성 실패 | 0 / 0 | 0 / 0 |
| Admission·문항·tokenizer·모델 실행 | 모두0 | 모두0 |

Calibration은 검색 이후 비재귀 디렉터리 목록을 차례로 따라가다가 세 문서의 경로를 확정하기 전에 예산을 소진했다. Validation은 두 검색에서 후보를 선택하지 못하고 알려진 공식 저장소 두 곳의 root metadata를 확인했지만 license 적용 범위와 완전한 family를 확정하지 못했다. API의 license label이 null이라는 관측은 license 부재나 이용 불허의 증거가 아니다.

Calibration의 원래 코드는 `no_complete_witness_within_budget`다. Validation은 설계가 license 미확정을 묶은 `incomplete_due_to_access_or_integrity`를 반환했다. **후자의 이름과 달리 실제 접근 오류나 무결성 실패는 없었다.** 원래 코드와 설명을 모두 보존하며 성공·실패의 원인을 바꾸지 않는다.

## 확인한 것과 확인하지 못한 것

이번에 확인한 것은 현재의 작은 조회 예산과 탐색 경로로 완전한 후보에 도달하지 못했다는 사실이다. 실제 완료 회의인지, 일반 문서와 의미 관계가 있는지, C7의 전체 입력 조건을 통과하는지는 관찰하지 못했다. 따라서 공개 자료의 보편적 부재, 원문 의미·크기 부적합, parser 결함, 모델 품질 실패, C7 정식 admission 거부를 주장하지 않는다.

기존19개 저장소 제외와 서로 다른 역할의 저장소 예약을 유지했다. 부모는 repo/commit과 안전한 집계·hash만 읽었다. `rust-embedded/wg`는 과거 repository metadata 탐색에 노출됐지만 반환된 기존 본문 저장소 목록에는 없었다는 점도 기록했다. 완전한 중복 부재나 pristine 역할을 주장하지 않는다.

## 보존된 근거

- [Calibration 요약](../data/evaluation/meetings-source-feasibility-v1/calibration/safe-summary-v1.json): `d000993f0d27868069d3b0de51b734df9d7ab02cecd93a7a0beb42700ab83a5b`.
- [Calibration index](../data/evaluation/meetings-source-feasibility-v1/calibration/artifact-index-v1.json): `c08bf84e7018dfc10b7593040826b8c6742835c4b7c209fd0fb451d5dea5029e`, 8개 파일 binding.
- [Validation 요약](../data/evaluation/meetings-source-feasibility-v1/validation/outcome-v1.json): `ad4a614704962c35b3bb8dd230ece7c5bc51e7efc8be1548fa4c3d9894c52862`.
- [Validation index](../data/evaluation/meetings-source-feasibility-v1/validation/artifact-index-v1.json): `5e86f47835ea5ef1fb8113250eb7826ee1ddce01b8c5402168b758b9cad9647e`, 19개 파일 binding.
- [설계 커밋의 CI](../experiments/results/meetings-source-feasibility-design-ci-v1.json): `2e398ec`의 push39379534450/PR39379540590에서 필수3job 모두 성공. 자료 품질이나 이번 결과 커밋의 CI를 대신하지 않는다.

부모가 index의 모든 파일 bytes/hash를 확인했다. 원래 CRLF인 공개 metadata5개는 정확한 경로에 `-text`를 지정해 bytes를 유지한다. 원래 ledger와 metadata 반환 projection은 `.local/meetings-source-feasibility-v1/`에 보존된다. 전체 HTTP 응답·공개 corpus·원문 수집을 완료했다고 표현하지 않는다.

이번 결과로 정식 C7 준비를 재개하지 않는다. 다음에는 실제 원문 관찰까지 도달할 수 있는 탐색 방식 또는 별도 engineering 판단을 검토하되, 기존 자료·상한·실패를 조용히 바꾸지 않는다. 새 실행은 아직 승인 범위가 정해지지 않았다. Phase1 자연어 답변과 전체 프로젝트 목표는 미완료다.
