# 실제 무료 QA 모델 내부 설정 검토

2026-10-28. 새 Qwen2.5-7B와 기존 Ministral3-3B의 GGUF header를 읽고 고정 프로필·이전 metadata와 비교했다. 독립 AI 검토는 차단 결함0·주의사항2이며, 실행 허가나 답변 품질 통과를 뜻하지 않는다.

## 문제와 방법

같은 모델 이름이라도 변환 파일의 tokenizer·대화 template가 원본 저장소 설정과 다를 수 있다. 실행 전에 **실제로 받은 파일의 값**을 확인해 두 모델의 요청에 정확히 연결한다. 저장소의 최신 template로 덮어쓰는 방법은 사용하지 않는다.

기존 bounded KV reader의 정확한 AST를 분리해 metadata만 총14,327,500바이트 읽었다. Tensor를 읽거나 template를 실행하지 않았다. 현재 수정 중인 엔진 runtime도 가져오지 않았다. 새 Qwen의 전체 파일 해시는 앞선 [실제 취득 결과](../experiments/results/meetings-free-qa-acquisition-v2.json)와 변하지 않은 파일 신원을 재사용했다.

| 확인 | 새 Qwen2.5-7B | 기존 Ministral3-3B |
| --- | --- | --- |
| 구조 | qwen2, 두 shard, split0/1 | mistral3, 한 파일 |
| header에서 읽은 바이트 | 5,934,211 +106 | 8,393,183 |
| template 바이트 | 2,509 | 7,753 |
| 과거 공식 GGUF metadata와 template | 일치 | 일치 |
| 비교에 사용할 context | 6,144 유지 | 6,144 유지 |

## 발견한 차이와 남은 확인

Qwen 내장 context는131072이며 별도로 관찰한 원본 config의32768과 다르다. 내장 template도 원본 tokenizer config와 중괄호 두 개가 다르다. 저장 BOS 값이 있어도 add-BOS는false다. 관찰한 내장 값을 그대로 기록했고, 더 긴 입력 지원이나 실제 tokenization의 적합성을 검증했다고 주장하지 않는다. 변환 원본 commit은 여전히unknown이다.

기존3B의 과거 설치 기록은 확인했지만 이번 검토에서 전체 가중치와 runtime55개 파일을 다시 해시하지 않았다. 별도 준비 담당자가 현재 무결성·파일 신원과 모델별 gate를 구성한다. 과거 설치를 새7B 다운로드 기록과 같은 형식의 실제 실행으로 꾸미지 않는다.

부모는 입력51개와 결과36개 해시를 대조했다. [기계 판독 결과](../experiments/results/meetings-free-qa-metadata-review-v1.json)에 관측값·검토·한계를 기록했다. 다음은 현재 실행환경과 코드 검증, 새6개 개발 자료의 별도 봉인, 중립 입력1건의 실제 로딩·전송 확인, 두 모델의 실제 답변 비교다. 새 모델 추론·사용자 의미 검수는 아직0이다.

## 후속: 현재 파일 검증과 후보 결속 검토

별도 담당자는 기존3B·runtime55·설치 기록 등을 포함한62파일4,323,975,120바이트의 전체 SHA를 확인했다. 새 Qwen은 앞선 전체 SHA와 변하지 않은17파일 신원을 재사용했다. 두 모델의 정책·외부 gate 후보를 순수 검사했고, 독립 검토는 차단0·주의1이다. 부모가 입력85개·준비결과35개·검토결과12개·자산신원79개·Git소스8개를 대조했다.

기존3B gate의 source_commit=0c는 **이번 현재 파일 검증에 사용한 공개 함수 버전**만 뜻한다. 원래 설치 실행commit과 새 로컬 검사 wrapper의 Git commit을 뜻하지 않는다. 원래 설치commit은unknown으로 유지하며 두 후보는 실제 실행 등록이나 trusted lock으로 사용하지 않았다. [후속 결과와 검사도구 실패 보존](../experiments/results/meetings-free-qa-asset-gates-v1.json).

모델 자산의 무결성은 준비됐지만 현재 엔진 코드의 독립 검토에서 발견한 최종화 B1 해결·정확CI, 새 자료 봉인과 실제 중립/품질 비교는 남아 있다. 서로 다른 단계의 통과를 전체 실행 준비 완료로 합치지 않는다.
