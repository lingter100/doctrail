# C3 원문·문항·실제 입력 준비

## 실제 validation 입력 준비와 중립 검사 등록

Item v2 커밋272f867뒤격리담당자가공식offline준비를한번실행했다.8/8통과·실패/미측정0,입력1088..3450tokens이다. 질문/whole-context/payload와139보호파일을보존했으며재시도·생성·native·download0이다. 원본은 `.local/meetings-c3-validation-prepared-v1`에있고 `data/evaluation/meetings-c3-validation-inputs-v1`에 input/receipt를그대로복사했다. Input SHA42722cb2dcd0de88d84c4384f7862b6b02757c0c7ed5dbfa5179a0f6617ec6f3, receipt23ddd4d6c2d924405a2d524b39df031dccb202ba737e564f83a108e928ac7668. 전용preparation-summary에경로/hash/count만공개하며부모는검증의미내용을보지않는다. 이전source일부노출은별도이탈로계속고지한다.

양split공식준비뒤동결register-neutral을실행해 `data/evaluation/meetings-c3-neutral-plan-v1.json`을사전등록했다(SHA c11b256c75f719b6436b124742866fd326080ae4f207cdbc32860526db6283b8). Normal첫입력360tokens, normal둘째입력은실제첫계획뒤측정한다. Stress두입력은각5081tokens·각384출력의별도강제부하다. 둘째stress는첫출력에의존하지않는자원전용이며품질결과가아니다. 예정native최대4, 요청공유90초및정리/재시작계약은원래대로다. 이기록은등록과모델없는neutral_check통과이며실제native는아직0이다.

```powershell
uv run --locked --no-sync --group retrieval python -m scripts.probe_meeting_requirements register-neutral --plan data/evaluation/meetings-c3-neutral-plan-v1.json --output .local/meetings-c3-neutral-v1 --code-freeze data/evaluation/meetings-c3-toolchain-source-freeze-v1.json --calibration-receipt data/evaluation/meetings-c3-calibration-inputs-v1/receipt.json --validation-receipt data/evaluation/meetings-c3-validation-inputs-v1/receipt.json --runtime-receipt models/meetings-qwen35-v1/setup-receipt.json
```

이미 등록한 경로에 다시 실행하지 않는다. 커밋 후 한 번의 실제 run-neutral과 원본 재생 검증 이후에만 품질 실행계획을 봉인한다.

## 후속: validation item v2 동결

격리validation8의첫사전검토는7승인/1거절이었다. 원본은4e621cc에서보존했고, 검토자가지적한한oracle의사실설명/근거만새v2로보완했다. 질문및context-selection파일은byte동일,다른7oracle사례canonical동일이다. 별도재검토8승인/0거절/남은수정0과strict6파일동결이완료됐다. `meetings-c3-validation-v1/item-freeze-v2.json` SHA854305b8eda2f0044db6751c6542d97237c653c8395124b24f8def8f335227f4. 공식입력준비는동결커밋후에실행하며이기록시점validation tokenizer/native0이다. 상세의미검토는부모에게노출하지않고별도summary/hash만전달했다.

2026-10-14 현재 calibration6의 공식 offline 입력 검사를 완료했다. 모델 답변 생성·의미 품질·서비스 채택은 아직0이다. 검증 원문의 부모 일부 노출은 [별도 이탈 기록](MEETINGS-C3-SOURCE-EXPOSURE.md)에 보존하며 완전 비노출 평가라고 하지 않는다.

## 원문과 문항 고정

코드66은 `2f3e9e9`, calibration 원문9는 `d02697e`에서 고정·필수 CI 통과했다. Calibration은 실제 FastAPI 공개2문서와 새 AI 합성2문서·20청크이며, Java 전체 처리 대조2통과와 별도 source4승인을 거쳤다. 새6문항을 별도 작성·사전검토한 후 `57981ca`에서 itemfreeze6과 validation source9를 커밋했다. GitHub author/committer는 모두 `lingter100`으로 확인했다. 원격 검사 상태는 STATUS에서 구분한다.

Calibration item 검토는6승인/거절0/수정0, KO3·EN3, 답변4·일부 필수정보 부재2다. 검토자는 필수정보28개 중 지원26·전체 원문에도 없는 정보2, 필수 복수문서3건과 양방향 언어교차를 확인했다. 부모는23개 whole-context 선택의 원본 일치와 schema·역할/hash를 재확인했다. 이는 AI 사전검토와 구조 검증이며 인간 검수0이다. 작성 당시 pending 상태는 별도 사후 영수증으로 연결한다.

## 실제 offline 준비

새 출력 디렉터리에서 다음 명령을 한 번 실행했다. 재실행할 때 이미 사용한 출력 경로를 재사용하지 않는다. 공식 평가 재실행 권한을 뜻하는 재현 예시는 아니다.

```powershell
uv run --locked --no-sync --group retrieval python -m scripts.prepare_meeting_requirements_inputs prepare --phase calibration --draft data/evaluation/meetings-c3-calibration-v1/draft.json --oracle data/evaluation/meetings-c3-calibration-v1/oracle.json --source-freeze data/evaluation/meetings-c3-calibration-v1/source-freeze-v1.json --item-freeze data/evaluation/meetings-c3-calibration-v1/item-freeze-v1.json --code-freeze data/evaluation/meetings-c3-toolchain-source-freeze-v1.json --output .local/meetings-c3-calibration-inputs-v1
```

| 확인 항목 | 실제 결과 |
|---|---|
| 첫 단계 공식 입력 수 |6/6 측정, 실패0·미측정0 |
| 입력 길이 |최소1,704·최대3,118 tokens, 상한5,120 |
| 원래 payload |내용·null·순서·전체 청크 보존 |
| 두 번째 입력 |실제 첫 계획에 의존, 아직 미측정 |
| 모델/native/download 호출 |각각0 |
| 사용자 검수 |0 |

실제 준비 원본 `input.json`과 `receipt.json`을 [공개 입력 폴더](../data/evaluation/meetings-c3-calibration-inputs-v1/)에 바이트 그대로 복사했다. Input SHA `3a21aa717aee74e0247ad9ee62418edfc7d02a988ff664da3b9b9a181d3b4da1`, receipt SHA `0260c6ee24b658742398025f1f2f8219c37867b28204fdf3ec8e558b3c8aeb74`. 모든 snapshot hash·원본 payload·공개 사본 일치와 동결 probe의 survey 검증을 모델 없이 통과했다. 출력 디렉터리 이름은 실제 원본을 보존하고 후속 실행은 허용된 공개 receipt 경로를 참조한다.

이 길이 결과에 맞춰 문항·청크·prompt를 수정하지 않는다. 길이 통과는 답변의 정확성이나 두 단계 실행 가능성 증거가 아니다. Validation8은 독립 작성·별도 사전검토·item 고정 뒤 격리 역할만 공식 입력을 준비한다. 양쪽 준비 통과 후 새 neutral4를 먼저 등록·검증하며, calibration6/6 gate 통과 전 validation 품질 생성은 금지한다. 최대32native·무료 로컬·실패 재시도0·기존 잠긴 pool 보존을 유지한다.
