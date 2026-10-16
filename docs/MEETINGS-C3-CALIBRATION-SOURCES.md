# C3 calibration 출처 채택과 전체 문서 처리

2026-10-14 · 작성 역할 `/root/c2_calibration_source`. 공개 문서 2개와 새 한국어 합성 원문 2개를 source-only 단계에서 채택했다. 전체 4문서/20청크의 Python/실제 Java 일치를 확인했다. 이 문서는 작성자의 채택·자기 점검 기록이며 별도 출처 검토 완료나 질문/모델 준비 완료를 주장하지 않는다. 질문·oracle·선택 context·공식 tokenizer·서비스 모델 호출·유료 사용·사람/사용자 검수는 모두 0이다.

작업 시작 기준은 부모가 원격 CI 성공을 확인한 전체 toolchain 동결 커밋 `2f3e9e9514de2d0d87935c43d6f1e510575c2e06`이다. [66개 바인딩](../data/evaluation/meetings-c3-toolchain-source-freeze-v1.json)의 SHA256은 `0b88ebb62744f0ff0f268aaa4be1d27290e570f98bf5a79b68467f05192dceb3`이며 이 역할은 원격 Git/CI를 다시 조회하지 않았다. 작성 전과 처리 후 66개 로컬 파일 hash 일치를 확인했고 동결 파일은 수정하지 않았다.

## 공개 원문과 이용 조건

[source-manifest.json](../data/evaluation/meetings-c3-calibration-v1/source-manifest.json)에 원문 경로·URL·Git blob·raw/processed SHA256·개별 검토 결과를 기록했다. 두 문서는 FastAPI의 `f5c6e9b4f9cadc1bf0f9a1fd672e621206b63007`에서 내려받은 원문 전체이며 문장을 골라 붙인 발췌가 아니다.

| 원문 | 고정 Git blob SHA1 | bytes | 전체 서비스 청크 |
| --- | --- | ---: | ---: |
| `docs/en/docs/tutorial/background-tasks.md` | `18c9bb6fe5db9f51769bb771f48b9fee4f4aab13` | 4786 | 6 |
| `docs/en/docs/advanced/events.md` | `485340afe2067c8ca2a03d70e4830a240ea085f5` | 7985 | 10 |

원문 bytes와 Git blob ID, 등록된 크기를 실제 대조했다. 고정 [MIT LICENSE](https://github.com/fastapi/fastapi/blob/f5c6e9b4f9cadc1bf0f9a1fd672e621206b63007/LICENSE)는 관련 문서를 포함하며, 해당 원본 1086 bytes도 기존 등록 hash와 비교하여 [라이선스 파일](../data/evaluation/meetings-c3-calibration-v1/licenses/FastAPI-LICENSE)로 보존했다. [ATTRIBUTION](../data/evaluation/meetings-c3-calibration-v1/ATTRIBUTION.md)은 원문/전체 inventory/발췌 재배포에 고지를 함께 유지하도록 명시한다. 이는 원문 2개를 재현 가능한 평가 자료로 의도적으로 보관하는 작업이다.

각 본문 전체에서 별도 저작권/라이선스나 다른 저자의 코드 블록 고지를 발견하지 않았다. 잘리지 않은 고정 tree의 루트와 해당 문서의 모든 상위 디렉터리에서 LICENSE/NOTICE/COPYING/COPYRIGHT 이름을 검사했으며 해당 범위에는 루트 LICENSE만 있었다. [public-fetch-receipt.json](../data/evaluation/meetings-c3-calibration-v1/public-fetch-receipt.json)에 tree ID, 응답 hash, 검사 범위와 결과를 남겼다. 이 결과는 연결된 제3자 페이지의 권리를 판정한 것이 아니다.

Markdown의 예시 파일 참조는 전부 문자 그대로 남겼다. 해당 `.py` 원문, Starlette/ASGI/Celery 문서와 기타 연결 페이지는 내려받거나 렌더링하지 않았다. 본문 자체의 짧은 Python 예시는 보존하되 실행하지 않는다. 이후 질문은 참조된 파일 내용이 본문에 존재한다고 가정해서는 안 된다. 요청 이후 작업과 앱 수명주기의 설명은 상호 보완적이며 두 문서의 시간·범위·자원 사용 조건을 함께 읽을 수 있다. 실제 조직 회의 데이터나 광범위한 표본을 대신하지는 않는다.

## 합성 원문과 작성 제약

새로 작성한 솔그늘도서관 회의 기록과 작업/개관 인계장에는 AI 합성·허구임을 본문에 표시했다. 작성자와 채택자는 같은 역할이다. 사람 이름, 도서관, 날짜와 사건은 모두 허구이며 과거 원문·질문·정답을 다시 열거나 이름/숫자만 바꾸어 재사용하지 않았다.

회의 문서는 재배치 배경, 검토한 제안, 확정한 시범 운영 범위, 담당자와 후속 기록을 다룬다. 인계장은 실제 작업으로 설정한 경과, 현장 조정, 확인 결과와 남은 시범 운영 상태를 다룬다. 회의에서 맡긴 일과 이후 완료 사실을 구분하며, 현장 조정이 부결된 안의 재채택이나 영구 배치 확정으로 바뀌지 않도록 자기 점검했다. 이 자기 점검은 독립 검수에 포함하지 않는다.

회의일 `2026-04-07`은 해당 회의 문서의 `meeting_date`에만 기록했다. 인계장의 작성일/작업일/참조 회의일은 본문의 날짜이며 인계장 `meeting_date`는 null이다. 두 문서는 각각 1414/1392 codepoints, 서비스 청크 각각 2개이다. 글의 단락·행·길이는 후보의 근거 단위나 토큰 상한에 맞춰 재구성하지 않았고 청크 수를 확인한 뒤 원문을 수정하지 않았다. 문서의 내부 일관성을 확인했을 뿐 실제 도서관 운영의 효과나 안전성을 검증한 자료는 아니다.

## 처리와 확인

기존 `prepare_meeting_plaintext_source_inventory` v2를 `adopted-all`로 실행했다. UTF-8 Markdown 전체에 기존 서비스의 BOM 제거/개행 정규화/NFC만 적용하며 렌더링·include 확장·새 요약·문단 이동을 하지 않는다. 네 파일은 이미 LF/NFC여서 raw/processed SHA256이 각각 동일하다. 기존 1000 codepoints, 최소 경계 탐색 500, 겹침 150, LF/공백 경계의 서비스 청크 규칙을 그대로 사용했다. 현재 청크 전체 보존은 후속 질문에 사용할 문맥 선택과 다르며 선택된 문맥은 0이다.

재현 명령은 저장소 루트에서 다음과 같다. 이미 생성된 출력 경로를 덮어쓰지 않는 도구이므로 아래 기록은 수행 이력이며 기존 경로로 재실행하라는 지시가 아니다.

```text
uv run --locked --no-sync python -m scripts.prepare_meeting_plaintext_source_inventory --manifest data/evaluation/meetings-c3-calibration-v1/source-manifest.json --output .local/meetings-c3-calibration-source-inventory-v1 --phase calibration --mode adopted-all
```

Java 21.0.12.1과 고정 Maven wrapper로 `MeetingSourceParityTest`를 실행했다. 서버 디렉터리 기준 `-Dtest=MeetingSourceParityTest`, `-Ddoctrail.sourceInventory=.local/meetings-c3-calibration-source-inventory-v1/inventory.json`, `-Ddoctrail.sourceParityReceipt=<저장소>/.local/meetings-c3-calibration-source-inventory-v1/java-parity.json`을 지정했다. 2개 검사 통과, 실패/오류/skip 0이며 실제 4문서/20청크의 본문·page·codepoint 좌표·순서·chunk ID·hash가 일치했다. 전체 Java 서비스 회귀나 성능 검사는 이 작업에서 반복하지 않았다.

[inventory.json](../data/evaluation/meetings-c3-calibration-v1/inventory.json), [processing-receipt.json](../data/evaluation/meetings-c3-calibration-v1/processing-receipt.json), [java-parity.json](../data/evaluation/meetings-c3-calibration-v1/java-parity.json)은 `.local` 원본의 정확한 바이트 복사다. 원래 processing receipt의 `java_parity_verified:false`와 `synthetic_bodies_authored:0`은 수정하지 않았다. 전자는 도구 자체가 Java를 실행하지 않았다는 뜻이며 별도의 실제 Java 영수증이 후속 확인을 증명한다. 후자는 해당 helper 호출이 합성 본문을 작성하지 않았다는 뜻이며 이 작성 단계의 합성 원문 수는 2다. Java 영수증의 CRLF 40개는 하위 `.gitattributes`의 `-text`로 보존한다.

고정 C3 준비기의 `validate_inventory`와 `validate_processing_receipts`만 별도로 호출해 새 원문 provenance·schema·전체 inventory 재구성·원본 처리/Java 영수증 형식을 확인했다. [source-contract-check-receipt.json](../data/evaluation/meetings-c3-calibration-v1/source-contract-check-receipt.json)에 성공과 복사 hash를 남겼다. 공식 준비 entrypoint, tokenizer, 질문/oracle 검사, 서비스 모델은 호출하지 않았다. 임시 manifest 조립 스크립트의 최초 실행은 Python import 경로 오류로 파일 생성 전에 끝났고, 로컬 조립 스크립트의 경로만 고친 뒤 성공했다. 동결 helper 변경이나 처리 결과 재선택은 없었다.

## 다음 단계와 노출

별도 출처 검토와 부모의 source-freeze 생성/커밋이 남아 있다. source-freeze, 질문, oracle, context-selection 파일은 이 역할이 아직 생성하지 않았다. 후기 질문 작성은 그 동결 이후 별도 지시를 받아 수행한다. 공개자료 사전학습 노출 가능성, 작은 목적표집, 합성 자료의 동일 저자 편향과 사람 검수 0이라는 한계를 유지한다.

이 역할은 과거 C2 calibration 작성자였고 이번에 필수 C3 PLAN에 실린 과거 calibration 진단 예시와 새 정책 설명을 읽었다. 닫힌 pool 파일, validation 본문/oracle, 새 후보 출력은 열지 않았다. source/preparation/parity 계약을 읽은 역할이므로 완전한 후보 비노출을 주장하지 않으며 독립 최종 출력 채점과 validation 작성에서 제외한다. 역할 모델은 부모가 기존 Astra xhigh 역할의 재사용으로 전달했다. 이 작업에서 모델 설정을 변경하거나 새 도구 수락 증거를 만들지는 않았다.
