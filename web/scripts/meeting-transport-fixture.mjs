// Deterministic HTTP contract fixture ONLY. This is not a language model, a
// generation-quality test, or a substitute for the separate real GPU checks.
import { createServer } from 'node:http';
import { once } from 'node:events';
export const fixtureMarker = 'SYNTHETIC_MEETING_TRANSPORT_FIXTURE';
export async function startMeetingTransportFixture() {
  const token = 'synthetic-local-browser-transport-token-2026';
  const calls = { analyze: 0, answer: 0 };
  const attempts = new Map();
  const server = createServer(async (request, response) => {
    try {
      if (request.method !== 'POST' || request.headers.authorization !== `Bearer ${token}`) { response.writeHead(403).end(); return; }
      const parts = []; for await (const part of request) parts.push(part);
      const body = JSON.parse(Buffer.concat(parts).toString('utf8'));
      const envelope = { schema_version: 1, model: 'synthetic-browser-transport-fixture-NOT-LLM', revision: 'fixture-v1' };
      let result;
      if (request.url === '/analyze') {
        calls.analyze++;
        const attempt = (attempts.get(body.document_id) || 0) + 1; attempts.set(body.document_id, attempt);
        if (body.content.includes('FIXTURE_FAIL_REANALYSIS') && attempt > 1) { response.writeHead(503).end(); return; }
        if (!body.content.includes(fixtureMarker)) { response.writeHead(422).end(); return; }
        const span = quote => { const index = body.content.indexOf(quote); if (index < 0) throw Error('Fixture quote missing'); const start_offset = Array.from(body.content.slice(0, index)).length; return { quote, start_offset, end_offset: start_offset + Array.from(quote).length }; };
        const decision = '단계별 배포로 진행하기로 결정했다.';
        const action = '민수는 후속 점검을 맡는다.';
        result = { ...envelope, analysis: { meeting_title: null, meeting_date: '2026-10-13', participants: ['민수'], purpose: null,
          summary: '합성 회귀용 고정 초안: 단계별 배포와 후속 점검을 논의했다.', summary_evidence: [span(decision)],
          metadata_evidence: [{ field: 'meeting_date', ...span('2026-10-13') }, { field: 'participants', ...span('민수') }],
          items: [
            { id: 'fixture-decision', type: 'decision', text: decision, ...span(decision), assignee: null, due_date: null, priority: null, status: 'needs_confirmation' },
            { id: 'fixture-action', type: 'action', text: action, ...span(action), assignee: null, due_date: null, priority: null, status: 'needs_confirmation' },
          ],
        } };
        if (body.content.includes('FIXTURE_GROUNDED_SUMMARY_V2')) {
          // Opt-in synthetic wire contract for real Java persistence/UI tests.
          // The accepted marker is fabricated; it is not an AI review result.
          const claims = [
            { id: 0, text: '합성 초안: 단계별 배포를 결정하고 민수가 후속 점검을 맡는다.', citations: [span(decision), span(action)] },
            { id: 1, text: '합성 초안: 민수가 후속 점검을 담당한다.', citations: [span(action)] },
          ];
          const unique = new Map();
          for (const claim of claims) {
            claim.citations.sort((a, b) => a.start_offset - b.start_offset || a.end_offset - b.end_offset);
            for (const citation of claim.citations) unique.set(`${citation.start_offset}:${citation.end_offset}`, citation);
          }
          result.analysis.summary_version = 2;
          result.analysis.summary_claims = claims;
          result.analysis.summary = claims.map(claim => claim.text).join('\n');
          result.analysis.summary_evidence = [...unique.values()].sort((a, b) => a.start_offset - b.start_offset || a.end_offset - b.end_offset);
          result.summary_review = { policy: 'grounded-review-v1', status: 'accepted' };
        }
      } else if (request.url === '/answer') {
        calls.answer++;
        const context = body.contexts.find(value => value.text.includes(fixtureMarker));
        if (!context) { response.writeHead(422).end(); return; }
        const quote = '단계별 배포로 진행하기로 결정했다.';
        const start_offset = context.start_offset + Array.from(context.text.slice(0, context.text.indexOf(quote))).length;
        result = { ...envelope, status: 'answered', reason: null, claims: [{ text: '합성 전송 검사용 고정 답변: 단계별 배포를 선택했다.', citations: [{ chunk_id: context.chunk_id, quote, start_offset, end_offset: start_offset + Array.from(quote).length }] }] };
      } else { response.writeHead(404).end(); return; }
      response.writeHead(200, { 'Content-Type': 'application/json' }).end(JSON.stringify(result));
    } catch { response.writeHead(500).end(); }
  });
  server.listen(0, '127.0.0.1'); await once(server, 'listening');
  return { url: `http://127.0.0.1:${server.address().port}`, token, calls, close: () => new Promise(resolve => server.close(resolve)) };
}
