# C4 새 원문 준비 결과

2026-10-16. 모델 품질 실행 전 원문 준비 단계다. 공개 원문과 합성 조직 문서를 구분해 고정했으며, 질문·oracle·context 선택·tokenizer·품질 추론은 아직 0이다.

| 구분 | 구성 | 전체 문서/청크 | 독립 source 검토 | 실제 Java parity |
|---|---|---|---|---|
| calibration | 공개 3 + 합성 3 | 6 / 32 | 수락 6, 거절·수정 0 | 2 통과 |
| validation | 공개 3 + 합성 3 | 6 / 20 | 수락 6, 거절·수정 0 | 2 통과 |

각 split의 두 family는 서로 다른 날짜의 회의 2개와 관련 일반 문서 1개로 구성된다. 전체 원문을 파싱한 청크와 좌표를 실제 Java 구현과 비교했다. 이 검사는 작은 발췌만의 일치나 모델 답변 정확성 검사가 아니다. 최초 parity 결과를 보존했으며 검토를 위해 같은 Maven 실행을 반복하지 않았다.

공개 출처는 calibration의 `scikit-image/skimage-archive@3bbcc6e8a7bd2c05675b316773796cc7f7fe0a96`(CC0-1.0), validation의 `nodejs/diagnostics@3162f5cdfe86a0830d6ce0eb525d9fbe1d0caee6`(MIT)다. 담당자와 별도 검토자가 고정 revision의 원문·license 바이트와 Git blob을 대조했다. 각 split 디렉터리의 manifest와 license에 출처를 보존한다. 합성 문서는 각각 다른 가상 조직의 운영 문서이며 실제 사용자 자료로 표시하지 않는다.

## 고정 결과와 재현 경계

- calibration [source freeze](../data/evaluation/meetings-c4-calibration-v1/source-freeze-v1.json): 정확한 14개 binding, SHA256 `8b1bac818cc1cc786ae75c275c58444ce6928ffb0940f0a4ccfdf229a9f53ce1`.
- validation [source freeze](../data/evaluation/meetings-c4-validation-v1/source-freeze-v1.json): 정확한 15개 binding, SHA256 `b4a132dadd9cef1b5ba5b0c15e2a28024b8fb5141a8200de30afe812c3c52698`.
- 고정된 전체 도구 85개와 선행 CI 영수증은 불변이다. Source freeze의 `bound_files`는 작업 파일과 Git index 바이트를 모두 대조한다. 동결된 processing validator와 `document_record`로 전체 청크를 재생했다.
- 새 원문 12개는 LF/no-BOM이다. 공개 calibration 원문 2개에 원래 있던 행말 공백은 출처의 정확한 바이트를 유지하기 위해 고치지 않는다. 해당 원문·hash에만 한정해 whitespace 결과를 구분하며 일반 코드/문서 검사를 끄지 않는다.
- 첫 Git index 대조에서 Java가 작성한 parity JSON 2개의 CRLF가 기본 LF 규칙으로 정규화돼 freeze hash와 달라지는 것을 발견했다. 커밋 전 두 정확한 경로만 `.gitattributes`의 `-text`로 지정해 원본 영수증 바이트를 보존한다. Source/receipt/freeze를 다시 쓰지 않으며 첫 index 검사 실패도 로컬 보존한다.
- 후속 whitespace 검사에서 원래 공개 MIT license의 마지막 빈 줄도 확인됐다. License의 고정 hash와 해당 경고 하나를 대조해 그대로 보존한다. Raw/의미 설명을 콘솔에 출력하지 않았으며 두 초기 index 검사 실패는 모델·자료 실패와 구분한다.

각 split의 정규화 전체 중복·family 간 긴 문단 중복은 검출되지 않았다. 그러나 과거 자료의 정규화 fingerprint가 없고 초기 자료의 identity coverage도 불완전하다. 과거 본문을 다시 열지 않았으며 번역·근접 재서술까지 모두 없다는 주장은 하지 않는다. Validation은 calibration fingerprint metadata와 prior index를 함께 고정한다.

## 탐색 노출과 원본 보존

원문 채택 전에 두 작성자가 같은 공개 저장소를 제안했다. 먼저 예약한 validation에 배정하고 calibration은 다른 출처를 선택했다. Calibration 작성자는 당시 대체 후보의 `GOVERNANCE.md`와 2024년 3월·5월 회의 본문도 보았다. 정확한 모든 경로/hash는 확인되지 않았다. Validation이 실제 채택한 일반 문서와 2025년 회의 경로는 보고된 대체 후보와 다르지만, 영향이 없거나 완전히 비노출이었다고 주장하지 않는다. 공유 license는 이용 조건 확인이다. 부모는 validation 본문을 열지 않았다.

따라서 source 커밋 후 calibration 질문은 이 탐색에 참여하지 않은 새 역할이 작성한다. 원문 작성자·검토자와 질문 작성자·검토자는 최종 출력 judge에서 제외한다. 원문을 질문이나 토큰 결과에 맞춰 수정하지 않는다.

Calibration 원본 author receipt에는 개인 환경의 절대 경로가 포함됐다. 원본 SHA `1108ec8e86c5290bb05f2cfe3f19bb144734f484b145589bc31b099447c413ea`를 `.local/c4-calibration-source-publication-v1/source-author-receipt-original.json`에 정확히 이동해 보존하고, 공개본은 별도 `source-author-public-receipt.json`으로 만들었다. Java 환경 경로 5개만 가렸으며 공개 URL·자료·측정치는 유지했다. 첫 미게시 파생본은 URL도 잘못 가려졌기 때문에 별도 보존하고 수정했다. 기존 author checks/provenance의 원본 hash는 역사적 기록이며 새 공개본의 hash로 바꾸지 않았다. 이 receipt는 source freeze binding 대상이 아니므로 freeze 14개는 그대로다.

Validation 보조 도구의 첫 HEAD 동일성 assertion 실패는 원문 출력 전 발생했다. 별도 v2에서 역사적 커밋 ancestry와 현재 HEAD를 구분했다. Reviewer의 첫 tree-SHA 비교 assertion도 commit API와 tree API를 혼동한 검사 오류였으며, 정확한 commit tree와 전체 entry 대조로 해결했다. 실패 기록을 보존했고 source를 바꾸거나 모델을 호출하지 않았다.

다음은 source freeze를 커밋한 뒤 새 calibration 6개와 격리 validation 8개 질문·정답·전체 context 선택, 별도 item 검토·동결·커밋이다. 이후에만 공식 offline tokenizer를 split마다 한 번 실행한다. 작은 평가의 AI 작성/검토는 사용자 검수나 일반화 증거가 아니다. Phase1과 PR14는 미완료이며 무료·로컬 한도를 유지한다.
