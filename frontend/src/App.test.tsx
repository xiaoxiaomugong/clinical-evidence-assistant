import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { StrictMode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import type { QueryResponse } from './types';

const answered: QueryResponse = {
  request_id: 'request-1', audience: 'public', status: 'answered', degraded: true,
  generation_method: 'extractive', message: null, online_search: false,
  answer: { summary: '检索到以下证据。', claims: [{ text: '研究内容 <img src=x onerror=alert(1)>', citations: [1] }], limitations: ['适用范围有限。'], disclaimer: '仅供学习与研究。' },
  sources: [{ id: 1, title: 'A source', url: 'https://example.org/source', year: 2022, source_type: 'pubmed_snapshot', study_type: 'RCT', evidence_level: null, publication_status: null, identifiers: { PMID: '123' }, excerpt: '原始摘要片段。' }],
  corpus: { version: 'v1', updated_at: '2026-09-01' },
};

beforeEach(() => {
  vi.stubGlobal('scrollTo', vi.fn());
  HTMLElement.prototype.scrollIntoView = vi.fn();
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); this.dispatchEvent(new Event('close')); };
});

function mockApi(reply: QueryResponse = answered) {
  return vi.fn<typeof fetch>(async (url) => {
    if (String(url).endsWith('/topics')) return new Response(JSON.stringify({ topics: [], corpus: answered.corpus }));
    return new Response(JSON.stringify(reply));
  });
}

describe('question workbench', () => {
  it('keeps source details open through StrictMode effect replay and closes on Escape', async () => {
    const user = userEvent.setup();
    HTMLDialogElement.prototype.close = function () {
      this.removeAttribute('open');
      queueMicrotask(() => this.dispatchEvent(new Event('close')));
    };
    vi.stubGlobal('fetch', mockApi());
    render(<StrictMode><MemoryRouter initialEntries={['/ask']}><App /></MemoryRouter></StrictMode>);
    fireEvent.change(screen.getByLabelText('你想了解什么？', { exact: false }), { target: { value: '一般问题' } });
    await user.click(screen.getByRole('button', { name: '查找证据' }));
    await screen.findByText('研究内容 <img src=x onerror=alert(1)>');
    await user.click(screen.getByRole('button', { name: '查看引用 1：A source' }));
    await waitFor(() => expect(screen.getByRole('dialog')).toHaveAttribute('open'));
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { bubbles: false, cancelable: true }));
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
  it('validates input before requests and preserves draft/PICO between audiences', async () => {
    const user = userEvent.setup();
    const fetcher = mockApi();
    vi.stubGlobal('fetch', fetcher);
    render(<MemoryRouter initialEntries={['/professional']}><App /></MemoryRouter>);
    await user.click(screen.getByRole('button', { name: '检索证据' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('填写');
    expect(fetcher.mock.calls.filter(([url]) => url === '/api/v1/queries')).toHaveLength(0);
    await user.type(screen.getByLabelText('研究问题', { exact: false }), '一般研究问题');
    await user.click(screen.getByText('补充 PICO 检索条件'));
    await user.type(screen.getByLabelText('P · 人群'), '成年人');
    await user.click(screen.getByRole('link', { name: '公众版 · 易读解释' }));
    expect(screen.getByLabelText('你想了解什么？', { exact: false })).toHaveValue('一般研究问题');
    await user.click(screen.getByRole('link', { name: '专业版 · 证据检索' }));
    expect(screen.getByLabelText('P · 人群')).toHaveValue('成年人');
  });

  it('submits actual text, renders citations safely, and keeps the original result label after switching', async () => {
    const user = userEvent.setup();
    const fetcher = mockApi();
    vi.stubGlobal('fetch', fetcher);
    render(<MemoryRouter initialEntries={['/ask']}><App /></MemoryRouter>);
    await user.type(screen.getByLabelText('你想了解什么？', { exact: false }), '关于健康的一般问题');
    await user.click(screen.getByRole('button', { name: '查找证据' }));
    expect(await screen.findByText('研究内容 <img src=x onerror=alert(1)>')).toBeInTheDocument();
    expect(document.querySelector('img')).toBeNull();
    const request = fetcher.mock.calls.find(([url]) => url === '/api/v1/queries');
    expect(JSON.parse(String(request?.[1]?.body))).toEqual({ question: '关于健康的一般问题', audience: 'public' });
    await user.click(screen.getByRole('button', { name: '查看引用 1：A source' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('原始摘要片段。');
    await user.click(screen.getByRole('button', { name: '关闭来源详情' }));
    await user.click(screen.getByRole('link', { name: '专业版 · 证据检索' }));
    expect(screen.getByText(/当前保留的是公众版结果/)).toBeInTheDocument();
    expect(fetcher.mock.calls.filter(([url]) => url === '/api/v1/queries')).toHaveLength(1);
  });

  it('disables duplicate submission while pending and replaces old answers with refusal', async () => {
    const user = userEvent.setup();
    let resolveRequest: ((response: Response) => void) | undefined;
    const fetcher = mockApi();
    vi.stubGlobal('fetch', fetcher);
    render(<MemoryRouter initialEntries={['/ask']}><App /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText('你想了解什么？', { exact: false }), { target: { value: '一般问题' } });
    await user.click(screen.getByRole('button', { name: '查找证据' }));
    await screen.findByText('研究内容 <img src=x onerror=alert(1)>');
    fetcher.mockImplementation(() => new Promise(resolve => { resolveRequest = resolve; }));
    await user.click(screen.getByRole('button', { name: '查找证据' }));
    expect(screen.getByRole('button', { name: '正在查找证据' })).toBeDisabled();
    expect(screen.queryByText('研究内容 <img src=x onerror=alert(1)>')).not.toBeInTheDocument();
    await act(async () => resolveRequest?.(new Response(JSON.stringify({ ...answered, status: 'refused', generation_method: 'none', answer: null, sources: [], message: '请先去掉可识别个人的信息。' }))));
    expect(await screen.findByText('请先去掉可识别个人的信息。')).toBeInTheDocument();
    expect(screen.queryByText('A source')).not.toBeInTheDocument();
  });

  it('offers an explicit retry after a network error without displaying raw exceptions', async () => {
    const user = userEvent.setup();
    const fetcher = mockApi();
    vi.stubGlobal('fetch', fetcher);
    render(<MemoryRouter initialEntries={['/ask']}><App /></MemoryRouter>);
    fireEvent.change(screen.getByLabelText('你想了解什么？', { exact: false }), { target: { value: '一般问题' } });
    fetcher.mockImplementation(async (url) => {
      if (String(url).endsWith('/topics')) return new Response(JSON.stringify({ topics: [], corpus: answered.corpus }));
      throw new Error('upstream private traceback');
    });
    await user.click(screen.getByRole('button', { name: '查找证据' }));
    await waitFor(() => expect(screen.getByRole('button', { name: '重试本次请求' })).toBeInTheDocument());
    expect(screen.queryByText(/private traceback/)).not.toBeInTheDocument();
  });
});
