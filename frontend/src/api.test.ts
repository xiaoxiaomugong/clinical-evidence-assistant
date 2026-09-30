import { describe, expect, it, vi } from 'vitest';
import { queryEvidence, safeSourceUrl, validateQuestion } from './api';

describe('question input boundaries', () => {
  it('rejects blank questions and oversized questions or PICO fields', () => {
    expect(validateQuestion('   ')).toContain('填写');
    expect(validateQuestion('问'.repeat(2001))).toContain('2000');
    expect(validateQuestion('问题', { population: '人'.repeat(501) })).toContain('500');
    expect(validateQuestion('问题', { population: '成人' })).toBeNull();
  });

  it('counts formatted PICO labels and newlines at the combined input boundary', () => {
    const pico = { population: '人'.repeat(500), intervention: '干'.repeat(500), comparison: '对'.repeat(500), outcome: '结'.repeat(500) };
    expect(validateQuestion('问'.repeat(1984), pico)).toBeNull();
    expect(validateQuestion('问'.repeat(1985), pico)).toContain('4000');
    expect(validateQuestion('  ' + '问'.repeat(1988) + '  ', { ...pico, population: '  ' + '人'.repeat(496) + '  ' })).toBeNull();
  });
});

describe('public API client', () => {
  it('sends audience and optional PICO to the real query endpoint', async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(new Response(JSON.stringify({
      request_id: 'request-1', audience: 'professional', status: 'refused', degraded: false,
      generation_method: 'none', message: '现有证据不足。', answer: null, sources: [],
      corpus: { version: 'v1', updated_at: null }, online_search: false,
    }), { status: 200 }));
    vi.stubGlobal('fetch', fetcher);
    const result = await queryEvidence({ question: '问题', audience: 'professional', pico: { population: '成人' } });
    expect(result.status).toBe('refused');
    expect(result.answer).toBeNull();
    expect(fetcher).toHaveBeenCalledWith('/api/v1/queries', expect.objectContaining({
      method: 'POST', body: JSON.stringify({ question: '问题', audience: 'professional', pico: { population: '成人' } }),
    }));
  });

  it('shows a safe busy message without leaking raw server errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('private upstream stack', { status: 429 })));
    await expect(queryEvidence({ question: '问题', audience: 'public' })).rejects.toThrow('繁忙');
  });

  it('rejects malformed successful responses instead of showing invented content', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'answered' }), { status: 200 })));
    await expect(queryEvidence({ question: '问题', audience: 'public' })).rejects.toThrow('响应');
  });

  it('only allows http and https source URLs', () => {
    expect(safeSourceUrl('javascript:alert(1)')).toBeNull();
    expect(safeSourceUrl('//evil.example/')).toBeNull();
    expect(safeSourceUrl('https://pubmed.ncbi.nlm.nih.gov/1/')).toBe('https://pubmed.ncbi.nlm.nih.gov/1/');
  });
});
