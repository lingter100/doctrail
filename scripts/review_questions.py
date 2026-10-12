"""Build a local source-grounded review packet; preserve submitted reviews as events.

The assistant must never submit this form or fabricate a human's review decisions.
An exported identity is self-declared, not verified expert identity. M2 evaluation
still refuses the test split, regardless of recorded review events.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from scripts.question_dataset import digest_file, read_questions, row_digest, validate_questions

ROOT = Path(__file__).resolve().parents[1]

HTML = """<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DocTrail · 평가 질문 검수</title>
<style>
*{box-sizing:border-box}body{margin:0;color:#18362f;background:#f5f6f2;font:15px/1.7 system-ui,sans-serif}
header{background:#193f35;color:white;padding:24px 5vw}header p{margin:6px 0;max-width:950px;color:#d5e8df}
main{max-width:1100px;margin:24px auto;padding:0 20px}section{background:white;border:1px solid #dce3da;border-radius:12px;padding:24px;margin:18px 0}
label{display:block;font-weight:600;margin-top:12px}input,textarea,select,button{font:inherit;border:1px solid #b8c9bd;border-radius:6px;padding:9px 12px}input,textarea,select{max-width:100%;background:white}textarea{width:100%;min-height:90px}button{cursor:pointer;background:#215b46;color:white}button.secondary{background:white;color:#215b46}button:disabled{opacity:.4;cursor:default}
blockquote{margin:12px 0;padding:14px;border-left:3px solid #367653;background:#f4f8f2;white-space:pre-wrap;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f6f2;padding:12px}small{color:#59685e}.row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}.badge{font-size:12px;background:#e6eee4;border-radius:16px;padding:2px 10px}h1{margin:0;font-size:26px}h2{font-size:21px}.source{margin:18px 0;border-top:1px solid #e2e8df;padding-top:12px}a{color:#256647}#message{white-space:pre-line;color:#7b4218}.checks label{font-weight:400}#questionSelect{flex:1;min-width:220px}details summary{cursor:pointer}
</style>
<header><h1>DocTrail / 평가 질문 검수</h1><p>AI가 작성한 질문 후보야. 질문과 근거의 의미가 맞는지 직접 판단해줘. 자동 검사는 글자 위치와 데이터 분리만 확인했으며, 정답의 품질을 보증하지 않아.</p></header>
<main><section><div class="row"><span class="badge" id="dataset"></span><span id="progress"></span></div>
<label for="reviewer">검수자 이름 또는 식별자</label><input id="reviewer" autocomplete="off" placeholder="직접 입력">
<p><small>입력한 신원은 자체 기재 정보야. 승인·수정 요청·제외 판단은 다운로드한 파일에만 저장돼. 페이지를 닫거나 새로고침하면 저장하지 않은 내용은 사라져.</small></p>
<div class="row"><select id="questionSelect" aria-label="질문 선택"></select><button id="prev" class="secondary">이전</button><button id="next" class="secondary">다음</button></div>
<details><summary>평가 대상 문서 전체 보기 · 근거 없음 판단 범위</summary><p id="scope"></p><input id="sourceFilter" aria-label="문서 목록 검색" placeholder="제목·경로로 문서 찾기"><div id="inventory"></div></details></section>
<section><div class="row"><span id="kind" class="badge"></span><span id="qid"></span></div><h2 id="query"></h2>
<label>AI가 작성한 참고 답안</label><p id="answer"></p><p id="reason"></p>
<div id="evidence"></div><details><summary>정답 라벨의 한계와 검수 방법</summary><p>같은 근거 그룹의 문장들은 대안이야. 서로 다른 그룹은 모두 찾아야 답할 수 있어. 다른 문서에도 유효한 답이 있다면 수정 요청에 적어줘. 근거 없음·모호함 질문은 전체 자료 범위에서 검토해야 해. 확신이 없으면 승인하지 않아도 돼. 본문 주변과 원문 링크를 함께 확인해줘.</p></details>
<div class="checks"><label><input type="checkbox" id="checkedQuery"> 질문의 자연스러움과 의도·조건 상태(명확함 또는 필수 조건 누락)를 확인했어.</label><label><input type="checkbox" id="checkedEvidence"> 모든 필수 근거 또는 근거 없음/모호함의 이유를 확인했어.</label></div>
<label for="decision">판단</label><select id="decision"><option value="">선택 필요</option><option value="approved">승인</option><option value="needs_revision">수정 요청</option><option value="rejected">제외</option></select>
<label for="note">판단 이유와 수정 사항</label><textarea id="note" placeholder="다른 정답 문서, 불충분한 근거, 잘못된 전제 등을 적어줘."></textarea>
<div class="row"><button id="save">이 질문 판단 저장</button><button id="download" class="secondary">검수 파일 다운로드</button></div><p id="message" role="status"></p></section>
<small>이 페이지는 로컬 검수 자료야. 서버로 전송하지 않아. 원문 저작자: The Kubernetes Authors / CC-BY-4.0. 발췌·정제 표시와 원문 링크는 각 근거에 있어.</small></main>
<script id="packet" type="application/json">__PACKET__</script>
<script>
const p=JSON.parse(document.getElementById('packet').textContent);const $=id=>document.getElementById(id);
let index=0;const decisions=new Map();
$('dataset').textContent=p.split+' · 질문 후보 '+p.questions.length+'개';
$('scope').textContent='검색 대상은 학습/개발/최종 평가 분할을 모두 포함한 '+p.inventory.length+'개 문서야. 문서 제목만 확인해 부재를 확정할 수는 없어. 고정 문서 목록 SHA256: '+p.manifest_sha256;
function renderInventory(){const term=$('sourceFilter').value.toLocaleLowerCase();$('inventory').replaceChildren();for(const d of p.inventory){if(!(d.title+' '+d.path).toLocaleLowerCase().includes(term))continue;const item=document.createElement('p');const a=document.createElement('a');a.href=d.source_url;a.target='_blank';a.rel='noopener noreferrer';a.textContent=d.title+' / '+d.language+' / '+d.path;item.append(a);$('inventory').append(item)}}$('sourceFilter').oninput=renderInventory;renderInventory();
for(const [i,q] of p.questions.entries()){const o=document.createElement('option');o.value=String(i);o.textContent=q.id+' · '+q.query;$('questionSelect').append(o)}
function render(){const q=p.questions[index];$('questionSelect').value=String(index);$('qid').textContent=q.id;$('query').textContent=q.query;$('kind').textContent=q.category+' / '+q.language;$('answer').textContent=q.reference_answer||'작성된 정답 없음';$('reason').textContent=q.negative_reason||'';$('evidence').replaceChildren();
for(const e of q.review_evidence){const d=document.createElement('div');d.className='source';const a=document.createElement('a');a.href=e.source_url;a.target='_blank';a.rel='noopener noreferrer';a.textContent=e.title+' · '+e.language;d.append(a);const label=document.createElement('div');label.textContent=e.evidence_group_id+' / ['+e.start_offset+', '+e.end_offset+') · 정제본에서 발췌';d.append(label);const quote=document.createElement('blockquote');quote.textContent=e.quote;d.append(quote);const dt=document.createElement('details');const sm=document.createElement('summary');sm.textContent='주변 문맥 확인';const pre=document.createElement('pre');pre.textContent=e.context;dt.append(sm,pre);d.append(dt);$('evidence').append(d)}
const old=decisions.get(q.id);$('decision').value=old?.decision||'';$('note').value=old?.note||'';$('checkedQuery').checked=old?.checked_query||false;$('checkedEvidence').checked=old?.checked_evidence||false;$('message').textContent='';$('progress').textContent=decisions.size+' / '+p.questions.length+'개 판단 저장';$('prev').disabled=index===0;$('next').disabled=index===p.questions.length-1}
$('questionSelect').onchange=()=>{index=Number($('questionSelect').value);render()};$('prev').onclick=()=>{if(index>0){index--;render()}};$('next').onclick=()=>{if(index<p.questions.length-1){index++;render()}};
$('save').onclick=()=>{const q=p.questions[index];const reviewer=$('reviewer').value.trim(),decision=$('decision').value,note=$('note').value.trim();if(!reviewer||!decision){$('message').textContent='검수자와 판단을 입력해줘.';return}if(decision==='approved'&&(!$('checkedQuery').checked||!$('checkedEvidence').checked)){$('message').textContent='승인하려면 질문과 근거를 직접 확인해야 해.';return}if((decision!=='approved'||q.category==='no_evidence'||q.category==='ambiguous')&&note.length<10){$('message').textContent='이 판단은 이유를 10자 이상 기록해줘.';return}decisions.set(q.id,{question_id:q.id,question_sha256:q.question_sha256,reviewer,decision,note,checked_query:$('checkedQuery').checked,checked_evidence:$('checkedEvidence').checked,reviewed_at:new Date().toISOString()});$('progress').textContent=decisions.size+' / '+p.questions.length+'개 판단 저장';$('message').textContent='페이지에 판단을 저장했어. 끝내기 전에 검수 파일을 다운로드해줘.'};
$('download').onclick=()=>{if(!decisions.size){$('message').textContent='저장한 판단이 없어.';return}const result={schema_version:1,kind:'self_declared_user_review',manifest_sha256:p.manifest_sha256,questions_sha256:p.questions_sha256,split:p.split,decisions:[...decisions.values()]};const b=new Blob([JSON.stringify(result,null,2)+'\\n'],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='doctrail-'+p.split+'-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};render();
</script></html>"""


def build_packet(
    rows: list[dict], corpus: list[dict], manifest_hash: str, question_hash: str
) -> dict:
    validate_questions(rows, corpus, manifest_sha256=manifest_hash)
    splits = {row["split"] for row in rows}
    if len(splits) != 1 or not rows:
        raise ValueError("Review one non-empty split at a time")
    docs = {doc["id"]: doc for doc in corpus}
    if any(urlparse(doc["source_url"]).scheme != "https" for doc in corpus):
        raise ValueError("Review sources must use HTTPS URLs")
    packet = []
    for row in rows:
        evidence = []
        for item in row["evidence"]:
            doc = docs[item["document_id"]]
            evidence.append(
                {
                    **item,
                    "title": doc["title"],
                    "language": doc["language"],
                    "source_url": doc["source_url"],
                    "context": doc["content"][
                        max(0, item["start_offset"] - 200) : item["end_offset"] + 200
                    ],
                }
            )
        packet.append({**row, "question_sha256": row_digest(row), "review_evidence": evidence})
    return {
        "split": next(iter(splits)),
        "manifest_sha256": manifest_hash,
        "questions_sha256": question_hash,
        "questions": packet,
        "inventory": [
            {key: doc[key] for key in ("id", "title", "language", "source_url", "path")}
            for doc in corpus
        ],
    }


def render_packet(packet: dict) -> str:
    # A source quote may contain HTML or </script>; never interpret it as markup.
    payload = json.dumps(packet, ensure_ascii=False).replace("<", "\\u003c").replace("&", "\\u0026")
    return HTML.replace("__PACKET__", payload)


def validate_review(review: dict, rows: list[dict], manifest_hash: str, question_hash: str) -> dict:
    if (
        review.get("schema_version") != 1
        or review.get("kind") != "self_declared_user_review"
        or review.get("manifest_sha256") != manifest_hash
        or review.get("questions_sha256") != question_hash
    ):
        raise ValueError("Review schema or dataset hash mismatch")
    if {row["split"] for row in rows} != {review.get("split")}:
        raise ValueError("Review split mismatch")
    ids = {row["id"]: row for row in rows}
    events = review.get("decisions")
    if not isinstance(events, list) or not events:
        raise ValueError("No review decisions")
    seen = set()
    for event in events:
        question_id = event.get("question_id")
        if question_id not in ids or question_id in seen:
            raise ValueError("Unknown or duplicate question review")
        seen.add(question_id)
        row = ids[question_id]
        if event.get("question_sha256") != row_digest(row):
            raise ValueError("Question changed after review")
        if not isinstance(event.get("reviewer"), str) or not event["reviewer"].strip():
            raise ValueError("Self-declared reviewer missing")
        decision = event.get("decision")
        if decision not in {"approved", "needs_revision", "rejected"}:
            raise ValueError("Unknown review decision")
        if decision == "approved" and not (
            event.get("checked_query") is True and event.get("checked_evidence") is True
        ):
            raise ValueError("Approval requires explicit query and evidence checks")
        if (decision != "approved" or row["category"] in {"no_evidence", "ambiguous"}) and len(
            event.get("note", "").strip()
        ) < 10:
            raise ValueError("Review rationale required")
        try:
            timestamp = datetime.fromisoformat(event["reviewed_at"])
            if timestamp.tzinfo is None or timestamp > datetime.now(UTC):
                raise ValueError("Invalid review timestamp")
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Invalid review timestamp") from exc
    return {
        "kind": "validated_self_declared_review_events",
        "decisions": len(events),
        "approved": sum(event["decision"] == "approved" for event in events),
        "identity_verification": "not_performed",
        "test_evaluation_unlocked": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--review", type=Path, help="Actual user-exported JSON; never fabricate it")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Refusing to overwrite an existing packet or review receipt")
    rows = read_questions(args.questions)
    manifest_hash = digest_file(args.manifest)
    question_hash = digest_file(args.questions)
    from scripts.prepare_corpus import load_verified_corpus

    corpus = load_verified_corpus(args.manifest)
    validate_questions(rows, corpus, manifest_sha256=manifest_hash)
    if args.review:
        raw = args.review.read_bytes()
        review = json.loads(raw)
        summary = validate_review(review, rows, manifest_hash, question_hash)
        result = (
            json.dumps(
                {
                    "recorded_at": datetime.now(UTC).isoformat(),
                    "review_file_sha256": hashlib.sha256(raw).hexdigest(),
                    "summary": summary,
                    "submitted_review": review,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
    else:
        packet = build_packet(rows, corpus, manifest_hash, question_hash)
        result = render_packet(packet)
        summary = {"status": "local_review_packet_created", "questions": len(rows)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        output.write(result)
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
