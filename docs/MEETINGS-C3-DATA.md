# C3 자료 계열 사전 등록

[등록부](../data/evaluation/meetings-c3-family-registry-v1.json)는 질문·정답·문맥 선택 이전의 metadata다. C3 코드와 prompt가 검증·고정되기 전에는 본문 채택·합성 원문·질문을 작성하지 않는다. Calibration6/격리 validation8 계획이며 실제 문항과 모델 호출은 아직0이다.

| 계열 | 구분 | 예정 출처·주제 | 예정 문항 |
|---|---|---|---:|
| C3-F01 | calibration 공개 | FastAPI의 요청 이후 작업과 앱 수명주기 | 3 |
| C3-F02 | calibration 합성 | 가상 지역 도서관의 이동서가 재배치 | 3 |
| C3-F03 | validation 공개 | MkDocs의 문서 작성·게시 절차 | 4 |
| C3-F04 | validation 합성 | 가상 지역 영화제의 자막 파일 검수 | 4 |

목적에 맞춰 계열을 배정한 작은 표본이며 무작위 추출이나 통계적 독립을 주장하지 않는다. 한 계열의 수정본·번역·가까운 바꿔쓰기는 같은 split에만 속한다. 이전 실험의 질문·원문·가상 사건을 이름이나 숫자만 바꿔 재사용하지 않는다. 이전 잠긴 validation과 최종 test도 계속 잠긴다.

FastAPI는 `f5c6e9b4f9cadc1bf0f9a1fd672e621206b63007`, MkDocs는 `2862536793b3c67d9d83c33e0dd6d50a791928f8`의 metadata를 고정했다. 파일 경로·크기·Git blob ID와 실제 tree ID를 확인했다. [FastAPI MIT 조건](https://github.com/fastapi/fastapi/blob/f5c6e9b4f9cadc1bf0f9a1fd672e621206b63007/LICENSE)은 저작권/허가 고지 보존을, [MkDocs BSD-2-Clause 조건](https://github.com/mkdocs/mkdocs/blob/2862536793b3c67d9d83c33e0dd6d50a791928f8/LICENSE)은 저작권·조건·면책 고지 보존을 요구한다. 고정한 LICENSE 원본을 Git blob SHA1/크기까지 대조하여 저장했다.

이는 개별 문서를 이미 채택했다는 뜻이 아니다. split 담당자가 원문의 별도 고지·외부 포함물·문맥 적합성을 확인해야 한다. Markdown 안의 외부 예시 파일을 가져오지 않고 본문에 있는 것처럼 처리하지 않는다. 판단할 수 없는 경우는 HOLD로 남긴다.

부모는 calibration FastAPI 검색 결과의 일부 문장을 봤다. 전체 본문은 아직 읽지 않았으며 노출을 등록부에 적었다. Validation MkDocs는 저장소/경로/크기/LICENSE만 확인했고 문서 본문을 읽지 않았다. 이후 부모와 후보 설계·구현자는 validation 원문·질문·정답·의미 검토 설명을 열지 않는다. 저자와 별도 검토자가 원문과 문항을 먼저 확정한 후 token 길이를 검사하며, 길이/출력 결과에 맞춘 문항 교체는 하지 않는다.

필수 사실 3~6개, split별 복수 문서 답변 최소2개, 양방향 한영 교차 사례를 포함한다. 보류 문항은 일부 사실만 있고 필요한 다른 사실은 채택한 계열의 전체 원문에도 없는 경우다. 정답 청크를 일부러 제외하지 않는다. 사람 검수·사용자 피드백은 아직0이다.
