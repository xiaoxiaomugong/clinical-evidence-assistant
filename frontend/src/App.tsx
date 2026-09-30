import { useEffect, useRef, useState } from 'react';
import type { FormEvent, RefObject } from 'react';
import { Link, NavLink, Route, Routes, useNavigate } from 'react-router-dom';
import { ApiError, getTopics, queryEvidence, validateQuestion } from './api';
import { Arrow, displayDate, ErrorNotice, Layout, PageHead, SourceDialog, SourceList } from './components';
import { Home, NotFound, ReadingPage, TopicPage, Topics } from './pages';
import type { TopicsState } from './pages';
import type { Audience, Pico, QueryRequest, QueryResponse, Source, Topic } from './types';

const audienceName = (audience: Audience) => audience === 'professional' ? '专业版' : '公众版';
const examples = ['关于早晨和晚间服用降压药，研究发现了什么？', '他汀与肌肉症状之间有哪些研究证据？', '地中海饮食与心血管风险有哪些研究证据？'];
const picoFields = [
  ['population', 'P · 人群', '例如：成人高血压研究人群'],
  ['intervention', 'I · 干预', '例如：晚间服药'],
  ['comparison', 'C · 对照', '例如：早晨服药'],
  ['outcome', 'O · 结局', '例如：心血管结局'],
] as const;

interface QueryState { loading: boolean; result: QueryResponse | null; error: ApiError | null; notice: string | null }
const initialQuery: QueryState = { loading: false, result: null, error: null, notice: null };

export default function App() {
  const navigate = useNavigate();
  const [draft, setDraft] = useState('');
  const [pico, setPico] = useState<Pico>({});
  const [picoOpen, setPicoOpen] = useState(false);
  const [query, setQuery] = useState<QueryState>(initialQuery);
  const [topics, setTopics] = useState<TopicsState>({ data: null, error: null, loading: true });
  const [topicsAttempt, setTopicsAttempt] = useState(0);
  const [source, setSource] = useState<Source | null>(null);
  const activeRequest = useRef<AbortController | null>(null);
  const lastRequest = useRef<QueryRequest | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setTopics(previous => ({ ...previous, loading: true, error: null }));
    getTopics(controller.signal).then(data => { if (!controller.signal.aborted) setTopics({ data, loading: false, error: null }); })
      .catch(error => { if (!controller.signal.aborted) setTopics({ data: null, loading: false, error: error instanceof ApiError ? error.message : '暂时无法读取主题，请稍后重试。' }); });
    return () => controller.abort();
  }, [topicsAttempt]);
  useEffect(() => () => { activeRequest.current?.abort(); }, []);

  async function submit(request: QueryRequest) {
    if (activeRequest.current) return;
    const controller = new AbortController();
    activeRequest.current = controller;
    lastRequest.current = request;
    setSource(null);
    setQuery({ loading: true, result: null, error: null, notice: null });
    try {
      const result = await queryEvidence(request, controller.signal);
      if (activeRequest.current === controller) setQuery({ loading: false, result, error: null, notice: null });
    } catch (error) {
      if (activeRequest.current === controller) setQuery({ loading: false, result: null, error: error instanceof ApiError ? error : new ApiError('暂时无法完成请求，请稍后重试。'), notice: null });
    } finally {
      if (activeRequest.current === controller) activeRequest.current = null;
    }
  }
  function stopWaiting() {
    const controller = activeRequest.current;
    activeRequest.current = null;
    controller?.abort();
    setQuery({ ...initialQuery, notice: '已停止等待。本次处理可能仍在服务端继续；页面不会自动重试。' });
  }
  function askTopic(topic: Topic) {
    activeRequest.current?.abort(); activeRequest.current = null;
    setQuery(initialQuery); setDraft(`关于${topic.title}，有哪些研究证据与适用范围？`);
    navigate('/ask');
  }
  const retryTopics = () => setTopicsAttempt(value => value + 1);
  const workbenchProps = { draft, setDraft, pico, setPico, picoOpen, setPicoOpen, query, submit, stopWaiting, openSource: setSource, topics: topics.data?.topics ?? [], retry: () => { if (lastRequest.current) void submit(lastRequest.current); } };
  return <Layout><Routes>
    <Route path="/" element={<Home topics={topics} retry={retryTopics} />} />
    <Route path="/ask" element={<Workbench audience="public" {...workbenchProps} />} />
    <Route path="/professional" element={<Workbench audience="professional" {...workbenchProps} />} />
    <Route path="/topics" element={<Topics topics={topics} retry={retryTopics} />} />
    <Route path="/topics/:id" element={<TopicPage askTopic={askTopic} />} />
    <Route path="/methodology" element={<ReadingPage page="methodology" />} />
    <Route path="/privacy" element={<ReadingPage page="privacy" />} />
    <Route path="/terms" element={<ReadingPage page="terms" />} />
    <Route path="*" element={<NotFound />} />
  </Routes>{source && <SourceDialog source={source} close={() => setSource(null)} />}</Layout>;
}

interface WorkbenchProps {
  audience: Audience; draft: string; setDraft: (value: string) => void;
  pico: Pico; setPico: (value: Pico) => void; picoOpen: boolean; setPicoOpen: (value: boolean) => void;
  query: QueryState; submit: (request: QueryRequest) => Promise<void>; stopWaiting: () => void;
  openSource: (source: Source) => void; topics: Topic[]; retry: () => void;
}

function Workbench(props: WorkbenchProps) {
  const pro = props.audience === 'professional';
  const question = useRef<HTMLTextAreaElement>(null);
  const result = useRef<HTMLElement>(null);
  const [inputError, setInputError] = useState<string | null>(null);
  useEffect(() => { setInputError(null); }, [props.audience]);
  function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (props.query.loading) return;
    const invalid = validateQuestion(props.draft, pro ? props.pico : undefined);
    setInputError(invalid);
    if (invalid) { question.current?.focus(); return; }
    const pico = Object.fromEntries(Object.entries(props.pico).filter(([, value]) => value.trim()).map(([key, value]) => [key, value.trim()]));
    void props.submit({ question: props.draft.trim(), audience: props.audience, ...(pro && Object.keys(pico).length ? { pico } : {}) });
    result.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  const form = <form className="question-card" onSubmit={onSubmit} noValidate>
    <label className="field-label" htmlFor="question">{pro ? '研究问题' : '你想了解什么？'}<small>一般知识与研究问题</small></label>
    <textarea ref={question} id="question" name="question" value={props.draft} onChange={event => { props.setDraft(event.target.value); setInputError(null); }} aria-describedby="input-hint input-error" aria-invalid={!!inputError} placeholder="例如：关于早晨和晚间服用降压药，研究发现了什么？" />
    <div className="input-meta"><span id="input-hint">请勿输入可识别个人的信息</span><span className={props.draft.length > 2000 ? 'error-text' : ''}>{props.draft.length} / 2000</span></div>
    {inputError ? <p id="input-error" className="input-error error-text" role="alert">{inputError}</p> : <span id="input-error" />}
    {pro && <details className="pico-details" open={props.picoOpen} onToggle={event => props.setPicoOpen(event.currentTarget.open)}><summary><span>补充 PICO 检索条件</span><span className="tag">可选</span></summary><div className="pico-fields">{picoFields.map(([key, label, placeholder]) => <label key={key} htmlFor={`pico-${key}`}>{label}<input id={`pico-${key}`} name={key} value={props.pico[key] || ''} placeholder={placeholder} onChange={event => { props.setPico({ ...props.pico, [key]: event.target.value }); setInputError(null); }} /></label>)}<p className="fine-print">每项最多 500 字；问题与条件合计最多 4000 字（含字段标签）。请填写一般研究条件。</p></div></details>}
    <div className="submit-row"><small>基于内置知识页与文献快照检索，<br />结果将显示资料日期与原始来源。</small><button className="button primary" type="submit" disabled={props.query.loading}>{props.query.loading ? '正在查找证据' : pro ? '检索证据' : '查找证据'} <span aria-hidden="true">→</span></button></div>
    <div className="example-box"><p>还没有具体问题？试试这些</p><div className="example-chips">{examples.map(example => <button key={example} type="button" className="example-chip" onClick={() => { props.setDraft(example); setInputError(null); question.current?.focus(); }}>{example}</button>)}</div></div>
  </form>;
  const response = <section ref={result} className="result-area" aria-label="问答结果" aria-busy={props.query.loading}><QueryResult query={props.query} audience={props.audience} openSource={props.openSource} stopWaiting={props.stopWaiting} retry={props.retry} question={question} /></section>;
  return <div className="wrap"><PageHead kicker={pro ? 'FOR CLINICAL LEARNING & RESEARCH' : 'HEALTH KNOWLEDGE, MADE CLEAR'} title={pro ? '带着问题，回到证据。' : '把健康问题，问得更明白。'} description={pro ? '整理研究条件，阅读证据摘要，逐条核对来源。' : '一起读研究，也了解结论的适用范围。'}><div className="mode-switch" aria-label="选择阅读方式"><NavLink to="/ask">公众版 · 易读解释</NavLink><NavLink to="/professional">专业版 · 证据检索</NavLink></div></PageHead><div className={`ask-layout${pro ? ' professional' : ''}`}>{pro ? <><div className="pro-left">{form}<SideNote topics={props.topics} /></div><div className="pro-right">{response}</div></> : <><div className="ask-main">{form}{response}</div><div className="ask-sidebar"><SideNote topics={props.topics} /></div></>}</div></div>;
}

function SideNote({ topics }: { topics: Topic[] }) {
  return <aside className="side-note"><span className="eyebrow">A SMALL NOTE BEFORE YOU ASK</span><h3>好问题，从保留边界开始</h3><p>描述你想了解的研究或一般知识，让证据帮助你理解。</p><ul><li>避免填写姓名、电话和病历号</li><li>个体用药调整请咨询医生</li><li>留意研究人群与资料日期</li></ul><Link className="text-link" to="/methodology">我们如何呈现证据 <span aria-hidden="true">→</span></Link><div className="topic-links">{topics.map(topic => <Link key={topic.id} to={`/topics/${encodeURIComponent(topic.id)}`}>{topic.title}</Link>)}</div></aside>;
}

function QueryResult({ query, audience, openSource, stopWaiting, retry, question }: { query: QueryState; audience: Audience; openSource: (source: Source) => void; stopWaiting: () => void; retry: () => void; question: RefObject<HTMLTextAreaElement | null> }) {
  if (query.loading) return <div className="status-card"><div className="status-icon"><div className="spinner" aria-hidden="true" /></div><h2 role="status">正在查找与核对证据</h2><p>正在等待服务返回经过检查的结果。来源与引用会在处理完成后一同显示。</p><div className="progress-track" aria-hidden="true"><div /></div><button className="button small ghost" onClick={stopWaiting}>停止等待</button><p className="fine-print">停止等待会中断浏览器接收响应，服务端可能仍在处理。页面不会自动重试。</p></div>;
  if (query.error) return <ErrorNotice message={query.error.message} requestId={query.error.requestId} retry={retry} />;
  if (!query.result) return <>{query.notice && <p className="same-result-note" role="status">{query.notice}</p>}<div className="empty-state"><div className="empty-glyph" aria-hidden="true"><i /><i /><i /></div><h2>先有问题，再看证据。</h2><p>提交一个一般知识或研究问题后，<br />在这里阅读回答、适用范围和原始来源。</p><div className="empty-flow"><span>一般问题</span><span aria-hidden="true">→</span><span>证据摘要</span><span aria-hidden="true">→</span><span>原始来源</span></div></div></>;
  const result = query.result;
  const originalLabel = result.audience !== audience ? <p className="same-result-note">当前保留的是{audienceName(result.audience)}结果。切换入口不会自动重新生成；再次提交将使用{audienceName(audience)}。</p> : null;
  if (result.status === 'refused') return <>{originalLabel}<div className="status-card warning"><div className="status-icon" aria-hidden="true">◇</div><span className="eyebrow status-eyebrow">KEEP THE BOUNDARIES VISIBLE</span><h2 role="status">这次暂时无法提供回答</h2><p>{result.message || '现有证据不足以支持回答，请缩小一般研究问题的范围。'}</p><button className="button primary" onClick={() => question.current?.focus()}>返回修改问题 <span aria-hidden="true">→</span></button> <Link className="text-link status-topic-link" to="/topics">浏览主题库</Link><p className="fine-print request-id">请求编号：{result.request_id}</p></div></>;
  if (!result.answer) return <ErrorNotice message="暂时没有可展示的回答，请重新提交。" retry={retry} />;
  const answer = result.answer;
  return <>{originalLabel}<article className="answer-card"><div className="answer-top"><span className="eyebrow">READ THE EVIDENCE</span><span className="pill green">{result.generation_method === 'llm' ? 'AI 生成摘要' : '来源摘录整理'} · {audienceName(result.audience)}</span></div><h2 role="status">{result.audience === 'professional' ? '本次证据摘要' : '先看研究说了什么'}</h2><p className="answer-kicker">有来源的回答，也需要结合原文理解。</p>{result.degraded && <p className="same-result-note">本次使用了回退结果。{result.message || '以下内容基于本地资料，并保留实际生成方式。'}</p>}<div className="answer-intro">{answer.summary}</div>{answer.claims.map((claim, index) => <section className="answer-claim" key={index}><h3><span>{String(index + 1).padStart(2, '0')}</span>研究发现与范围</h3><p><span>{claim.text}</span>{claim.citations.map(id => {
    const source = result.sources.find(source => source.id === id);
    return source && <button key={id} className="citation-button" onClick={() => openSource(source)} aria-label={`查看引用 ${id}：${source.title}`}>{id}</button>;
  })}</p></section>)}{answer.limitations.length > 0 && <aside className="context-box"><h3>这些边界，也值得一起读</h3><ul>{answer.limitations.map((limitation, index) => <li key={index}>{limitation}</li>)}</ul></aside>}<div className="answer-meta"><span>资料日期：{displayDate(result.corpus.updated_at)}</span><span>语料版本：{result.corpus.version}</span><span>在线检索：{result.online_search ? '已完成' : '未进行'}</span><span>证据确定性：未独立评定</span></div><div className="answer-actions"><button className="text-link" onClick={() => { const sources = document.getElementById('answer-sources'); sources?.scrollIntoView({ behavior: 'smooth', block: 'start' }); sources?.focus({ preventScroll: true }); }}>查看 {result.sources.length} 条引用来源 <span aria-hidden="true">↓</span></button><Link className="text-link" to="/methodology">了解检查方法 <Arrow /></Link></div></article><p className="result-note">{answer.disclaimer}</p><SourceList sources={result.sources} openSource={openSource} /><p className="fine-print request-id">请求编号：{result.request_id}</p></>;
}
