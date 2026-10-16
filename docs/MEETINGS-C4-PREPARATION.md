# C4 공식 입력 준비와 실행 경계

2026-10-16. 수락한 item과 독립 최종 판정 역할을 먼저 `f542691150da6d024830cc0eb4074041f6cac5c0`으로 커밋했다. 코드85·원문·문항의 실제 Git 검사를 통과한 뒤 동결된 `scripts.prepare_meeting_thinking_inputs`로 split별 offline 준비를 각각 한 번 실행한다. 모델 생성과 다른 단계다.

## Calibration 실측

공식 CLI는 한 번 실행되어6/6 통과했다. 입력 길이는 최소1,255·최대3,868토큰으로 상한5,120 이내다. Tokenizer load1·native/model/download0이며 CLI 경과57.391초는 준비 도구 실행 시간이지 서비스 응답 시간이 아니다. 전체 context/payload와 원래 불수락7파일, 수락v2 및 동결 코드·원문은 변하지 않았다.

원본은 `.local/meetings-c4-calibration-prepared-v1/`에 남겼다. 개인 환경 경로가 없음을 확인한 정확한 바이트 복사본을 `data/evaluation/meetings-c4-calibration-inputs-v1/`에 기록했다.

- `input.json`: `8fe62a35bc9d28cd66f1d3d1eb5dcf2bdae126dfe2838bd59ba3ea8e3bad8c60`
- `receipt.json`: `2fc5e869d501f2870774131aa886157bb221c31eb876eb778fda4cabde771620`

## Validation 실측과 실행계획

격리 담당자가 같은 커밋에서 공식 CLI를 한 번 실행해8/8 통과했다. 입력은902~3,887토큰, tokenizer load1·native/model/download0, CLI 경과57.719초다. 원문·payload·context·동결 파일은 불변이다. 부모는 본문·질문·oracle·의미 검토를 열지 않고 metadata와 hash만 받았다.

개인 환경 경로 검사 뒤 `data/evaluation/meetings-c4-validation-inputs-v1/`에 원본 `.local/meetings-c4-validation-prepared-v1/`의 정확한 바이트를 복사했다.

- `input.json`: `78eb18ffdaae823d415001b078625876603bc18bb36e9172e2cedf1f4acc4126`
- `receipt.json`: `3821048055f4ace4fa9b8af0da1bb1f0ecc110118112026b338f31810314505c`

새 실행계획 `data/evaluation/meetings-c4-quality-execution-plan-v1.json` SHA `ca2c21eb5e039dc230193513d990a23545659147173d1bbe065995edcaa5034d`에 두 split의 입력/영수증/원문/item, 코드85, 서로 다른 판정자2명의 attestation/seed와 제외역할22개를 연결했다. 경로 검사는 통과했으며 실제 Git을 사용하는 실행 `check`는 이 계획 커밋 후에 한다. 아직 실제 C4 품질 호출은0이다.

문항·판정 역할 커밋f542691의 push38857698147/PR38857702290 필수3job도 각각 모두 성공했다. 준비 통과나 CI를 답변 품질 통과로 세지 않는다.

## 실행 순서와 재현 주의

공식 CLI는 `uv run --group retrieval --no-sync python -m scripts.prepare_meeting_thinking_inputs --phase calibration|validation`에 각 `--draft`, `--oracle`, `--source-freeze`, `--item-freeze` 경로와 `--*-sha256`을 명시한다. 원래 실행의 정확한 참조는 각 receipt의 `references`에 있다. 로컬 캐시 tokenizer만 사용하며 다운로드를 허용하지 않는다.

공식 출력 경로는 실패도 소비하는 단발 예약이다. 이미 끝난 준비를 동일 저장소에서 다시 실행하지 않는다. 원문·문항·전체 청크를 길이에 맞춰 자르거나 재선정하지 않는다. 준비 실패와 모델 생성 실패를 구분하고 원본 영수증을 보존한다.

두 split의 준비가 통과해야 정확한 입력·영수증·코드85·판정자 attestation/seed를 하나의 새 실행계획에 묶어 커밋한다. 그 뒤 calibration만 최대6번 생성한다. 요청90초·전체928출력·최종JSON384재토큰·retry0 등 고정 계약을 유지한다. 새 smoke나 warmup은 추가하지 않는다. 원래6/6 의미·운영 관문 통과 후에만 validation 최대8번을 허용하며 준비 자체는 개방 승인이 아니다.

최종 답변을 익명으로 판정하고 judgment hash를 잠그기 전에는 매핑이나 reasoning을 판정자에게 열지 않는다. 통과하더라도 검색 품질·서비스 전체 지연·사용자 만족·Phase1 완료를 자동으로 입증하지 않는다.
