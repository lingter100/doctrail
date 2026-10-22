import type { Detail, Hit } from './types';
import { ApiError, errorMessage } from './api';

export type Span = { quote: string; start_offset: number; end_offset: number };
export type Evidence = Span & { document_id: string; revision: number; chunk_id?: string; title?: string; meeting_date?: string | null; page?: number | null };
export type ItemType = 'topic' | 'proposal' | 'decision' | 'unresolved' | 'action';
export type ItemStatus = 'needs_confirmation' | 'confirmed' | 'todo' | 'doing' | 'done';
export type MeetingItem = Span & { id: string; type: ItemType; text: string; assignee: string | null; due_date: string | null; priority: 'low' | 'medium' | 'high' | null; status: ItemStatus };
export type Analysis = { meeting_title: string | null; meeting_date: string | null; participants: string[]; purpose: string | null; summary: string; summary_evidence?: Span[]; metadata_evidence: (Span & { field: string })[]; items: MeetingItem[] };
export type MeetingDetail = { document: Detail; meeting: { document_id: string; analysis_status: 'queued' | 'running' | 'ready' | 'failed' | 'stale'; analysis_error: string | null; source_revision: number; version: number; ai_analysis: Analysis | null; analysis: Analysis | null; provenance: 'ai' | 'user_edited'; meeting_date?: string | null; participants?: string[] } };
export type TaskItem = MeetingItem & { meeting_id: string; title: string; workspace_id: string; source_revision: number; version: number };
export type DecisionLink = Span & { id: string; source_id: string; target_id: string; source_item_id: string; target_item_id: string; source_title?: string; target_title?: string; source_meeting_date?: string | null; target_meeting_date?: string | null; source_item_text?: string; target_item_text?: string; relation: 'related' | 'supersedes'; created_by: string; created_at?: string; source_revision: number; target_revision: number };
export type KnowledgeHit = Hit & { workspace_id: string; document_kind: 'meeting' | 'document'; meeting_date: string | null };
export type KnowledgeResult = { query: string; method: string; results: KnowledgeHit[]; status?: 'answered' | 'abstained'; reason?: string | null; claims?: { text: string; citations: Evidence[] }[]; model_called?: boolean; experimental?: boolean };
export const itemLabels: Record<ItemType, string> = { topic: '논의 주제', proposal: '제안', decision: '결정 사항', unresolved: '미해결 사항', action: '후속 작업' };
export const statusLabels: Record<ItemStatus, string> = { needs_confirmation: '확인 필요', confirmed: '확정', todo: '할 일', doing: '진행 중', done: '완료' };
export const analysisLabels = { queued: '분석 대기', running: 'AI 분석 중', ready: '분석 완료', failed: '분석 실패', stale: '원문 변경 · 재분석 필요' };
export function knowledgeAbstention(reason: string | null | undefined): string {
  switch (reason) {
    case 'no_evidence': return '현재 검색 조건에 맞는 원문 근거가 없어요. 검색 범위나 회의 조건을 조정해 주세요.';
    case 'insufficient_evidence': return '찾은 원문만으로는 질문에 답할 근거가 충분하지 않아요. 검색된 원문을 확인하거나 질문과 검색 조건을 구체화해 주세요.';
    case 'conflicting_evidence': return '찾은 원문의 내용이 서로 달라 답변을 보류했어요. 원문을 비교하고 회의 날짜 등 검색 조건을 확인해 주세요.';
    case 'unsupported_question': return '현재 답변 기능으로 처리하기 어려운 질문이에요. 원문에서 확인할 수 있는 내용을 구체적으로 질문해 주세요.';
    default: return '답변을 보류했어요. 검색된 원문을 확인하거나 질문과 검색 조건을 조정해 주세요.';
  }
}

export function knowledgeError(error: unknown): string {
  if (!(error instanceof ApiError)) return '서버에 연결하지 못했어요. 연결 상태를 확인한 뒤 다시 시도해 주세요.';
  if (error.status === 401) return errorMessage(error);
  if (error.status === 403 || error.status === 404) return '자료를 확인할 수 없어요. 현재 접근 가능한 자료와 검색 조건을 다시 확인해 주세요.';
  const code = error.code;
  if (code === 'search_context_changed') return '검색 중 원문이나 접근 권한이 변경됐어요. 현재 접근 가능한 자료로 다시 확인해 주세요.';
  if (code === 'embedding_profile_changed') return '검색 모델 설정이 변경됐어요. 현재 검색 방식을 확인한 뒤 다시 검색해 주세요.';
  if (code === 'generation_timeout') return '답변 생성 시간이 초과됐어요. 잠시 후 직접 다시 시도하거나 원문 검색으로 확인해 주세요.';
  if (code === 'generation_busy' || code === 'model_busy' || code === 'inference_busy') return '다른 AI 요청을 처리하고 있어요. 잠시 후 직접 다시 시도해 주세요.';
  if (code === 'generation_unavailable' || code === 'generation_failed') return '답변 생성에 일시적인 문제가 생겼어요. 잠시 후 직접 다시 시도하거나 원문 검색으로 확인해 주세요.';
  if (['generation_invalid_response', 'generation_invalid_json', 'generation_invalid_schema', 'generation_invalid_evidence', 'generation_duplicate_item', 'generation_unsupported_field', 'generation_unsupported_metadata', 'generation_conflicting_metadata', 'generation_output_truncated'].includes(code)) return 'AI 응답의 형식이나 근거를 검증하지 못했어요. 답변으로 사용하지 않았으니 원문 검색으로 확인해 주세요.';
  if (code === 'generation_language_mismatch') return 'AI 응답이 요청한 언어와 달라 답변으로 사용하지 않았어요. 원문 검색으로 근거를 확인할 수 있어요.';
  if (['generation_disabled', 'generation_not_configured', 'generation_cleanup_failed'].includes(code)) return '현재 답변 생성 기능을 사용할 수 없어요. 원문 검색으로 근거를 확인해 주세요.';
  if (code === 'context_budget_exceeded') return '찾은 근거가 한 번에 답변할 수 있는 분량을 넘었어요. 원문은 그대로 보관되어 있어요. 검색 조건을 좁히거나 원문 검색으로 확인해 주세요.';
  if (['generation_input_limit', 'generation_partition_limit', 'answer_context_limit', 'visible_corpus_too_large', 'query_too_long'].includes(code)) return '현재 요청을 처리할 수 있는 범위를 넘었어요. 질문이나 검색 조건을 좁히거나 원문 검색으로 확인해 주세요.';
  if (code === 'inference_timeout') return '관련 근거를 찾는 시간이 초과됐어요. 검색 조건을 조정하거나 잠시 후 직접 다시 검색해 주세요.';
  if (['inference_disabled', 'inference_unavailable', 'inference_invalid_response'].includes(code)) return '현재 모델 검색을 사용할 수 없어요. 검색 방식을 확인하거나 잠시 후 직접 다시 검색해 주세요.';
  return '검색 또는 답변 요청을 완료하지 못했어요. 검색 조건을 확인하거나 잠시 후 직접 다시 시도해 주세요.';
}

export function meetingError(error: unknown): string {
  if (!(error instanceof ApiError)) return errorMessage(error);
  if (error.status === 409) return '원문이나 분석이 변경되어 저장하지 않았어요. 새로 불러온 뒤 수정 내용을 다시 확인해 주세요.';
  if (error.code === 'context_budget_exceeded') return '찾은 근거가 한 번에 답변할 수 있는 분량을 넘었어요. 원문은 그대로 보관되어 있어요. 검색 조건을 좁히거나 원문 검색으로 확인해 주세요.';
  if (error.code === 'inference_timeout') return '관련 근거를 찾는 시간이 초과되어 답변을 만들지 못했어요. 검색 조건을 좁히거나 원문 검색으로 확인해 주세요.';
  if (error.code === 'generation_busy') return '다른 AI 요청을 처리하고 있어요. 잠시 후 다시 시도해 주세요.';
  if (error.code === 'generation_cleanup_failed') return 'AI 연결을 안전하게 종료했는지 확인하지 못해 답변 생성을 중단했어요. AI 연결을 다시 시작하기 전에는 원문 검색을 이용해 주세요.';
  if (error.code === 'generation_language_mismatch') return 'AI 응답이 요청한 언어와 달라 답변으로 사용하지 않았어요. 원문 검색으로 근거를 확인할 수 있어요.';
  if (error.code.includes('not_configured') || error.code.includes('disabled')) return 'AI 모델이 연결되지 않았어요. 원문 등록과 키워드 검색은 계속 사용할 수 있어요.';
  if (error.code.includes('invalid_response') || error.code.includes('generation_failed')) return 'AI 응답의 형식이나 근거를 검증하지 못했어요. 답변으로 사용하지 않았으니 다시 시도해 주세요.';
  if (error.status === 503) return 'AI 모델이 준비되지 않았거나 사용할 수 없어요. 잠시 후 다시 시도해 주세요.';
  if (error.status === 504) return 'AI 처리 시간이 초과됐어요. 원문은 보존되어 있어요. 잠시 후 다시 시도해 주세요.';
  if (error.code.includes('too_long') || error.code.includes('token') || error.code.includes('too_large')) return '현재 분석 한도를 넘었어요. 원문 분량을 줄여 별도 회의로 등록해 주세요.';
  if (error.code.includes('quote') || error.code.includes('evidence') || error.code.includes('analysis') || error.code.includes('link')) return '항목과 근거를 확인해 주세요. 인용문은 원문 구절과 정확히 일치해야 해요.';
  return errorMessage(error);
}
