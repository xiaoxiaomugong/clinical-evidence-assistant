import type { Corpus, Pico, QueryRequest, QueryResponse, Source, Topic, TopicDetail, TopicsResponse } from './types';

export class ApiError extends Error {
  constructor(message: string, public status = 0, public requestId?: string) { super(message); }
}

export function validateQuestion(question: string, pico?: Pico): string | null {
  if (!question.trim()) return '先填写一个问题，或点选下方示例。';
  if (question.length > 2000) return '问题最多 2000 字，请缩短后提交。';
  const fields = Object.values(pico ?? {});
  if (fields.some(value => value.length > 500)) return '每项 PICO 条件最多 500 字，请缩短后提交。';
  if (question.trim().length + fields.reduce((sum, value) => sum + (value.trim() ? value.trim().length + 4 : 0), 0) > 4000) return '问题与 PICO 条件合计最多 4000 字（含字段标签和换行）。';
  return null;
}

export function safeSourceUrl(url: string | null): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return ['https:', 'http:'].includes(parsed.protocol) && !parsed.username && !parsed.password ? parsed.href : null;
  } catch { return null; }
}

const record = (value: unknown): value is Record<string, unknown> => typeof value === 'object' && value !== null && !Array.isArray(value);
const string = (value: unknown): value is string => typeof value === 'string';
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(string);
const nullableString = (value: unknown): value is string | null => value === null || string(value);
const corpus = (value: unknown): value is Corpus => record(value) && string(value.version) && nullableString(value.updated_at);
const source = (value: unknown): value is Source => record(value) && Number.isInteger(value.id) && Number(value.id) > 0 && string(value.title)
  && nullableString(value.url) && (value.year === null || Number.isInteger(value.year)) && string(value.source_type)
  && nullableString(value.study_type) && nullableString(value.evidence_level) && nullableString(value.publication_status)
  && record(value.identifiers) && Object.values(value.identifiers).every(string) && string(value.excerpt);

function isQueryResponse(value: unknown): value is QueryResponse {
  if (!record(value) || !string(value.request_id) || !['public', 'professional'].includes(String(value.audience))
    || !['answered', 'refused', 'error'].includes(String(value.status)) || typeof value.degraded !== 'boolean'
    || !['extractive', 'llm', 'none'].includes(String(value.generation_method)) || !nullableString(value.message)
    || !Array.isArray(value.sources) || !value.sources.every(source) || !corpus(value.corpus) || typeof value.online_search !== 'boolean') return false;
  if (value.status !== 'answered') return value.answer === null && value.sources.length === 0;
  const answer = value.answer;
  const ids = new Set(value.sources.map(item => item.id));
  return ids.size === value.sources.length && record(answer) && string(answer.summary) && string(answer.disclaimer)
    && strings(answer.limitations) && Array.isArray(answer.claims) && answer.claims.length > 0
    && answer.claims.every(claim => record(claim) && string(claim.text) && Array.isArray(claim.citations)
      && claim.citations.length > 0 && claim.citations.every(id => typeof id === 'number' && ids.has(id)));
}

const topic = (value: unknown): value is Topic => record(value) && string(value.id) && string(value.title)
  && string(value.summary) && nullableString(value.updated_at) && string(value.review_status)
  && nullableString(value.reviewer) && string(value.version) && strings(value.scope);

function statusMessage(status: number): string {
  if (status === 429) return '当前请求较多，服务繁忙。请稍后再试，或先浏览主题库。';
  if (status === 422 || status === 413) return '问题或检索条件不符合要求，请检查长度和内容后重新提交。';
  if (status === 408 || status === 504) return '本次请求超时，请稍后重试。';
  if (status === 404) return '暂时没有找到这项内容。';
  if (status === 503) return '服务暂时不可用，请稍后重试。';
  return '暂时无法完成请求，请稍后重试。';
}

async function fetchJson(path: string, options: RequestInit = {}): Promise<unknown> {
  const controller = new AbortController();
  let timedOut = false;
  const abort = () => controller.abort();
  if (options.signal?.aborted) abort();
  options.signal?.addEventListener('abort', abort, { once: true });
  const timer = window.setTimeout(() => { timedOut = true; controller.abort(); }, 65000);
  try {
    const response = await fetch(path, { ...options, signal: controller.signal, cache: 'no-store', credentials: 'same-origin', headers: { Accept: 'application/json', ...options.headers } });
    const data: unknown = await response.json().catch(() => null);
    const requestId = record(data) && string(data.request_id) && /^[a-zA-Z0-9_-]{1,80}$/.test(data.request_id) ? data.request_id : undefined;
    if (!response.ok || (record(data) && data.status === 'error')) throw new ApiError(statusMessage(response.status), response.status, requestId);
    if (data === null) throw new ApiError('服务响应不完整，请稍后重试。');
    return data;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (timedOut) throw new ApiError('本次请求超时，请稍后重试。', 408);
    if (options.signal?.aborted) throw new ApiError('已停止等待本次请求。');
    throw new ApiError('暂时无法连接服务，请检查网络后重试。');
  } finally {
    window.clearTimeout(timer);
    options.signal?.removeEventListener('abort', abort);
  }
}

export async function queryEvidence(request: QueryRequest, signal?: AbortSignal): Promise<QueryResponse> {
  const invalid = validateQuestion(request.question, request.pico);
  if (invalid) throw new ApiError(invalid, 422);
  const data = await fetchJson('/api/v1/queries', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request), signal });
  if (!isQueryResponse(data)) throw new ApiError('服务响应不完整，请稍后重试。');
  return data;
}

export async function getTopics(signal?: AbortSignal): Promise<TopicsResponse> {
  const data = await fetchJson('/api/v1/topics', { signal });
  if (!record(data) || !Array.isArray(data.topics) || !data.topics.every(topic) || !corpus(data.corpus)) throw new ApiError('主题列表响应不完整，请稍后重试。');
  return { topics: data.topics, corpus: data.corpus };
}

export async function getTopic(id: string, signal?: AbortSignal): Promise<TopicDetail> {
  const data = await fetchJson(`/api/v1/topics/${encodeURIComponent(id)}`, { signal });
  if (!topic(data) || !record(data) || !strings(data.content) || !Array.isArray(data.references)
    || !data.references.every(item => record(item) && string(item.title) && nullableString(item.url) && nullableString(item.identifier))) throw new ApiError('主题内容响应不完整，请稍后重试。');
  return data as unknown as TopicDetail;
}
