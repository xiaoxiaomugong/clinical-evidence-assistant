import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, NavLink, useLocation } from 'react-router-dom';
import { safeSourceUrl } from './api';
import type { Source } from './types';

export const Arrow = () => <span className="arrow" aria-hidden="true">↗</span>;
export const displayDate = (value: string | null) => value || '未记录';
export const sourceLabel = (value: string) => ({ knowledge_page: '知识页', pubmed_snapshot: '文献快照' }[value] ?? value);

export function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const menu = useRef<HTMLButtonElement>(null);
  const main = useRef<HTMLElement>(null);
  const firstRender = useRef(true);

  useEffect(() => {
    setMenuOpen(false);
    const title = main.current?.querySelector('h1')?.textContent || '循证知问';
    document.title = `${title} · 循证知问`;
    let robots = document.querySelector<HTMLMetaElement>('meta[name="robots"]');
    if (!robots) { robots = document.createElement('meta'); robots.name = 'robots'; document.head.append(robots); }
    robots.content = ['/ask', '/professional'].includes(location.pathname) ? 'noindex, nofollow' : 'index, follow';
    if (!firstRender.current) { main.current?.focus({ preventScroll: true }); window.scrollTo({ top: 0, behavior: 'instant' }); }
    firstRender.current = false;
  }, [location.pathname]);

  return <>
    <a className="skip-link" href="#main" onClick={(event) => { event.preventDefault(); main.current?.focus(); }}>跳到主要内容</a>
    <div className="prototype-strip"><span><span className="status-dot" />本地试用</span><span>基于内置资料 · 未进行在线检索</span><Link to="/methodology">了解资料与边界 <Arrow /></Link></div>
    <header className="site-header" onKeyDown={(event) => { if (event.key === 'Escape' && menuOpen) { setMenuOpen(false); menu.current?.focus(); } }}>
      <Link className="brand" to="/" aria-label="循证知问首页"><span className="brand-mark" aria-hidden="true">✳</span><span>循证知问<small>EVIDENCE, WITH CONTEXT</small></span></Link>
      <button ref={menu} className="menu-toggle" aria-label={menuOpen ? '关闭导航' : '打开导航'} aria-expanded={menuOpen} aria-controls="main-nav" onClick={() => setMenuOpen(!menuOpen)}>菜单 <span aria-hidden="true">☰</span></button>
      <nav id="main-nav" className={menuOpen ? 'open' : ''} aria-label="主导航"><NavLink to="/ask">公众版</NavLink><NavLink to="/topics">主题库</NavLink><NavLink to="/methodology">方法与来源</NavLink><NavLink className="nav-pro" to="/professional">进入专业版 <Arrow /></NavLink></nav>
    </header>
    <main id="main" ref={main} tabIndex={-1}>{children}</main>
    <footer className="site-footer"><div><Link className="footer-brand" to="/">✳ 循证知问</Link><p>理解证据，也理解它的边界。</p></div><div className="footer-links"><Link to="/methodology">方法与来源</Link><Link to="/privacy">隐私说明</Link><Link to="/terms">使用说明</Link></div><small>仅供健康知识学习与研究，不构成诊疗建议。<br />资料日期与审核状态请以具体页面记录为准。</small></footer>
  </>;
}

export function PageHead({ kicker, title, description, children, breadcrumb }: { kicker: string; title: string; description: string; children?: ReactNode; breadcrumb?: ReactNode }) {
  return <header className="page-head"><div className="breadcrumbs"><Link to="/">首页</Link><span aria-hidden="true">/</span>{breadcrumb || <span>{title}</span>}</div><div className="page-title-row"><div><span className="eyebrow">{kicker}</span><h1>{title}</h1><p className="lead">{description}</p></div>{children}</div></header>;
}

export function ErrorNotice({ message, retry, requestId }: { message: string; retry?: () => void; requestId?: string }) {
  return <div className="status-card warning" role="alert"><div className="status-icon" aria-hidden="true">◷</div><h2>暂时没有完成这次请求</h2><p>{message}</p>{retry && <button className="button primary" onClick={retry}>重试本次请求 <span aria-hidden="true">→</span></button>} <Link className="text-link status-topic-link" to="/topics">浏览主题库</Link>{requestId && <p className="fine-print request-id">请求编号：{requestId}</p>}</div>;
}

export function SourceList({ sources, openSource }: { sources: Source[]; openSource: (source: Source) => void }) {
  return <section className="source-section" id="answer-sources" tabIndex={-1}><h3>沿着引用，查看来源 <small>{sources.length} 条来源</small></h3>{sources.map(source => <button className="source-row" key={source.id} onClick={() => openSource(source)}><span className="citation-square">{String(source.id).padStart(2, '0')}</span><span><span className="source-name">{source.title}</span><span className="source-details">{sourceLabel(source.source_type)} · {source.year ?? '年份未记录'}{Object.entries(source.identifiers).map(([key, value]) => ` · ${key.toUpperCase()} ${value}`).join('')}</span><span className="source-details">研究类型：{source.study_type || '未记录'} · 发表状态：{source.publication_status || '未记录'} · 证据类型：{source.evidence_level || '未记录'}</span></span><Arrow /></button>)}</section>;
}

export function SourceDialog({ source, close }: { source: Source; close: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const url = safeSourceUrl(source.url);
  useEffect(() => {
    const element = dialog.current;
    const trigger = document.activeElement;
    element?.showModal();
    return () => { if (element?.open) element.close(); if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus(); };
  }, []);
  return <dialog ref={dialog} className="source-dialog" aria-labelledby="source-title" onCancel={event => { event.preventDefault(); close(); }} onClick={event => {
    if (event.target !== event.currentTarget) return;
    const rect = event.currentTarget.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) close();
  }}><div className="dialog-body"><button className="dialog-close" aria-label="关闭来源详情" onClick={close}>×</button><span className="eyebrow">SOURCE NOTE / {String(source.id).padStart(2, '0')}</span><h2 id="source-title">{source.title}</h2><div className="source-attributes"><span className="pill green">{sourceLabel(source.source_type)}</span><span className="pill">{source.year ?? '年份未记录'}</span>{Object.entries(source.identifiers).map(([key, value]) => <span className="pill" key={key}>{key.toUpperCase()} {value}</span>)}</div><dl className="source-facts"><dt>研究类型</dt><dd>{source.study_type || '未记录'}</dd><dt>发表状态</dt><dd>{source.publication_status || '未记录'}</dd><dt>证据类型</dt><dd>{source.evidence_level || '未记录'}</dd></dl><h3 className="excerpt-heading">资料摘录</h3><div className="source-excerpt">{source.excerpt || '此来源未提供可展示的摘录。'}</div><p className="fine-print">请在原始来源中查看完整方法、结果与限制。收录来源不代表已独立评定证据确定性。</p>{url ? <a className="button primary" href={url} target="_blank" rel="noopener noreferrer">打开原始来源 <Arrow /><span className="sr-only">（新窗口）</span></a> : <p className="fine-print">原始来源链接未记录或暂不可用。</p>}</div></dialog>;
}
