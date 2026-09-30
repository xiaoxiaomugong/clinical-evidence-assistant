import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ApiError, getTopic, safeSourceUrl } from './api';
import { Arrow, displayDate, ErrorNotice, PageHead } from './components';
import type { Topic, TopicDetail, TopicsResponse } from './types';

export interface TopicsState { data: TopicsResponse | null; error: string | null; loading: boolean }

function TopicGrid({ state, retry, large = false }: { state: TopicsState; retry: () => void; large?: boolean }) {
  if (state.loading) return <div className="library-notice" role="status"><span className="spinner" aria-hidden="true" />正在读取主题与来源…</div>;
  if (state.error) return <div className="library-notice" role="alert"><p>{state.error}</p><button className="text-link" onClick={retry}>重新加载主题 <span aria-hidden="true">↻</span></button></div>;
  if (!state.data?.topics.length) return <p className="library-notice">暂时没有可展示的主题。</p>;
  return <div className={`topic-grid${large ? ' large' : ''}`}>{state.data.topics.map((topic, index) => <TopicCard key={topic.id} topic={topic} index={index} large={large} />)}</div>;
}

function TopicCard({ topic, index, large }: { topic: Topic; index: number; large: boolean }) {
  return <Link className="topic-card" to={`/topics/${encodeURIComponent(topic.id)}`}><span className="topic-number">{String(index + 1).padStart(2, '0')}</span><span className="corner-arrow" aria-hidden="true">↗</span><h3>{topic.title}</h3><p>{topic.summary}</p>{large && <><span className="topic-update">资料更新：{displayDate(topic.updated_at)}</span><span className="text-link">查看主题与来源 <span aria-hidden="true">→</span></span></>}</Link>;
}

export function Home({ topics, retry }: { topics: TopicsState; retry: () => void }) {
  return <div className="wrap"><section className="hero"><div className="hero-copy"><span className="eyebrow">A CLEARER WAY TO UNDERSTAND HEALTH</span><h1>健康信息很多，<br /><em>让证据帮你看清。</em></h1><p className="lead">了解研究说了什么，也看清它适用于谁。<br />从一个问题出发，找到可以回查的来源。</p><div className="hero-actions"><Link className="button primary" to="/ask">了解健康知识 <Arrow /></Link><Link className="button ghost" to="/professional">检索临床证据 <Arrow /></Link></div><p className="hero-footnote">面向健康知识学习与研究，个体诊疗请咨询专业人员。</p></div><div className="hero-scene" aria-label="示意：回答可逐条查看证据来源"><div className="scene-grid" /><div className="scene-orbit" /><div className="evidence-sheet"><div className="sheet-head"><span className="tag">THE EVIDENCE NOTE / 001</span><span className="sheet-logo" aria-hidden="true">✳</span></div><h3>每一个结论，<br />都有值得细读的来源。</h3><div className="sheet-line" /><div className="sheet-line short" /><div className="sheet-citation"><span className="citation-square">01</span><span>阅读研究发现<small>FINDINGS, WITH CONTEXT</small></span></div><div className="sheet-citation"><span className="citation-square">02</span><span>核对适用范围<small>PEOPLE, METHODS & LIMITS</small></span></div><div className="sheet-check"><b aria-hidden="true">↗</b>沿着引用，回到原文</div></div><span className="scene-note">A NOTE, GROUNDED IN SOURCES</span></div></section><section className="trust-strip" aria-label="资料来源说明"><p>收录资料<br />保留原始来源</p><div className="source-wordmarks"><span>PubMed</span><span>WHO</span><span className="sans">THE LANCET</span><span className="sans">Diabetes Care</span></div><small>展示来源名称<br />不表示合作或背书</small></section><section className="section"><div className="section-head"><div><span className="eyebrow">START WITH A TOPIC</span><h2>从你关心的主题开始</h2><p>先把一个问题弄清楚，再向更深处了解。</p></div><Link className="text-link" to="/topics">浏览主题库 <span aria-hidden="true">→</span></Link></div><TopicGrid state={topics} retry={retry} />{topics.data && <p className="corpus-note">语料版本 {topics.data.corpus.version} · 资料日期 {displayDate(topics.data.corpus.updated_at)} · 未进行在线更新</p>}</section><section className="guide-section"><div><span className="eyebrow">HOW IT WORKS</span><h2>答案之外，<br />还有理解的路径。</h2></div><div className="guide-steps">{[['提出一般问题', '从你想了解的知识出发，保留必要的研究条件。'], ['读懂研究发现', '一起看研究对象、结论，以及仍不确定的部分。'], ['回到证据来源', '沿着编号查看文献，让理解有迹可循。']].map(([title, copy], index) => <div key={title}><span className="step-index">0{index + 1}</span><h3>{title}</h3><p>{copy}</p></div>)}</div></section></div>;
}

export function Topics({ topics, retry }: { topics: TopicsState; retry: () => void }) {
  return <div className="wrap topics-index"><PageHead kicker="THE TOPIC LIBRARY" title="从一个主题，慢慢读懂。" description="从项目知识页出发，把研究发现、适用人群和资料来源放在一起。" /><TopicGrid state={topics} retry={retry} large /><p className="corpus-note">更新日期和审核状态按知识页原有记录展示，不代表已完成新一轮独立临床评审。</p></div>;
}

export function TopicPage({ askTopic }: { askTopic: (topic: Topic) => void }) {
  const { id = '' } = useParams();
  const [detail, setDetail] = useState<TopicDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setDetail(null); setError(null);
    getTopic(id, controller.signal).then(value => { if (!controller.signal.aborted) setDetail(value); }).catch(error => { if (!controller.signal.aborted) setError(error instanceof ApiError ? error.message : '暂时无法读取主题，请稍后重试。'); });
    return () => controller.abort();
  }, [id, attempt]);
  useEffect(() => { if (detail) document.title = `${detail.title} · 循证知问`; }, [detail]);
  if (error) return <div className="wrap topics-index"><PageHead kicker="TOPIC NOTE" title="暂时无法读取这个主题" description="你可以重试，或从主题库继续阅读。" /><ErrorNotice message={error} retry={() => setAttempt(value => value + 1)} /></div>;
  if (!detail) return <div className="wrap topics-index"><PageHead kicker="TOPIC NOTE" title="正在读取主题…" description="获取知识页内容与来源记录。" /><p className="library-notice" role="status">正在加载主题内容…</p></div>;
  return <div className="wrap"><PageHead kicker="TOPIC NOTE" title={detail.title} description={detail.summary} breadcrumb={<><Link to="/topics">主题库</Link><span aria-hidden="true">/</span><span>{detail.title}</span></>} /><div className="article-layout"><div><article className="article-card"><span className="pill green">项目知识页</span><h2 className="topic-article-title">把研究发现与边界放在一起</h2>{detail.content.map((paragraph, index) => <section className="topic-claim" key={index}><p>{paragraph}</p></section>)}</article><section className="source-section"><h3>继续阅读原始来源 <small>{detail.references.length} 条来源</small></h3>{detail.references.map((reference, index) => {
    const url = safeSourceUrl(reference.url);
    const content = <><span className="citation-square">{String(index + 1).padStart(2, '0')}</span><span><span className="source-name">{reference.title}</span><span className="source-details">{reference.identifier || '标识符未记录'}{!url ? ' · 原始链接未记录或不可用' : ''}</span></span>{url && <Arrow />}</>;
    return url ? <a className="source-row" href={url} key={index} target="_blank" rel="noopener noreferrer">{content}<span className="sr-only">（新窗口）</span></a> : <div className="source-row" key={index}>{content}</div>;
  })}</section></div><aside className="side-note"><span className="eyebrow">ABOUT THIS NOTE</span><h3>一份可以回查的笔记</h3><dl className="topic-facts"><dt>资料更新</dt><dd>{displayDate(detail.updated_at)}</dd><dt>审核状态</dt><dd>{detail.review_status}</dd><dt>审核者记录</dt><dd>{detail.reviewer || '未记录'}</dd><dt>资料版本</dt><dd>{detail.version}</dd></dl><h3>适用范围</h3><ul>{detail.scope.map(scope => <li key={scope}>{scope}</li>)}</ul><button className="button primary" onClick={() => askTopic(detail)}>围绕这个主题提问 <Arrow /></button><p className="fine-print topic-boundary">知识页原有审核记录不等同于本次网站已完成独立临床评审。个体诊疗请咨询专业人员。</p></aside></div></div>;
}

const readingPages = {
  methodology: { kicker: 'METHOD & SOURCES', title: '让来源清楚，让边界可见。', intro: '每一段解释，都应有一条可以继续阅读的路径。', sections: [
    ['当前如何查找证据', '提交的问题会发送到本地服务，经过隐私与诊疗边界检查后，检索内置知识页和精选文献快照。服务整理来源陈述，进行引用、数字及支持性规则检查，再返回回答；证据不足或无法安全回答时会说明原因。当前没有进行在线检索。'],
    ['资料来自哪里', '知识页和精选文献快照保留原有标题、年份、来源链接及 PMID、DOI 等标识符。语料日期表示本地资料版本的日期，不代表覆盖此后所有研究。来源摘录应与原文的方法、人群、结果及局限一起阅读。'],
    ['公众版与专业版', '公众版集中呈现回答与来源。专业版可补充人群、干预、对照、结局四项 PICO 检索条件，两版共用同一套证据与安全边界。当前回答为来源摘录整理，尚未提供独立审核的通俗改写。专业版入口不代表医生身份认证。'],
    ['怎样理解生成标识', '“来源摘录整理”表示从已有资料中提取、组织陈述；只有实际使用模型生成的结果才标为“AI 生成摘要”。降级结果会保留实际生成方式和资料日期。加载时只表示正在等待服务，不假定某一内部检索阶段已经完成。'],
    ['引用存在，不等于结论已经被证明', '程序检查不能替代独立临床评审，也不能排除所有医学错误。当前没有独立评定证据确定性。研究质量、适用人群、结局与限制仍需回到原文判断；不把工程测试分数当作医学正确率。'],
  ] },
  privacy: { kicker: 'PRIVACY, BY DESIGN', title: '理解健康，不必交出隐私。', intro: '这里说明当前本地试用的数据处理方式。', sections: [
    ['草稿与页面状态', '问题草稿、PICO 条件和回答保存在当前页面内存中。切换入口会保留这些内容，刷新或关闭页面后清除。页面不使用本地存储、问答历史库或第三方统计脚本；问题不会写入页面地址。'],
    ['提交后会发生什么', '点击提交会把问题、所选阅读方式及填写的 PICO 条件发送到本站接口。当前本地服务仅使用内置资料完成检索与整理，不调用在线文献检索或外部模型，也不持久化题干与回答。请勿输入姓名、手机号、身份证号、病历号或完整病历；自动检查无法识别所有隐私信息。'],
    ['网络与外部链接', '页面资源由本站提供，不加载外部字体或分析脚本。主动打开原始文献链接时，浏览器会访问相应外部网站，适用该网站自己的数据处理政策。停止等待会中断浏览器接收响应，不代表已终止服务器中的处理。'],
    ['公开上线前需要补充的说明', '本页对应当前本地试用。实际运营主体、托管服务、日志与数据保留期限、联系及删除请求渠道尚未配置。若以后接入在线服务或面向公众部署，需要按实际实现更新说明；这里不展示尚不存在的联系方式或处理承诺。'],
  ] },
  terms: { kicker: 'USING EVIDENCE WITH CONTEXT', title: '带着边界，阅读证据。', intro: '从一般问题出发，结合来源理解回答。', sections: [
    ['使用范围', '本工具用于一般健康知识学习、临床教学与研究，不提供个体诊断、处方、剂量、停药或换药建议。专业版与公众版适用相同边界。个人健康或用药问题请咨询专业人员。'],
    ['如何使用', '选择阅读方式，输入一般问题，也可以点选示例问题再提交。回答仅来自真实服务结果。正文引用编号可打开来源详情；专业版可补充 PICO 条件。切换入口不会自动重新生成，已有结果保留原来的阅读方式标记。'],
    ['资料的时间与审核状态', '当前使用本地内置资料，可能缺少较新研究。页面展示的资料日期及审核记录来自现有文件，不代表已完成本次网站的独立临床评审。对不充分或范围以外的问题，系统可能拒答；有引用的内容同样需要审慎核查。'],
    ['当前试用功能', '当前为免登录、单次提问的本地试用，没有收藏、支付、文件上传、问答分享或已接通的反馈收集。异常时可以主动重试；页面不会自动重复提交问题。'],
  ] },
};

export function ReadingPage({ page }: { page: keyof typeof readingPages }) {
  const content = readingPages[page];
  return <div className="wrap reading-page"><PageHead kicker={content.kicker} title={content.title} description={content.intro} /><article className="reading-card">{content.sections.map(([title, paragraph]) => <section className="reading-block" key={title}><h2>{title}</h2><p>{paragraph}</p></section>)}</article></div>;
}

export function NotFound() {
  return <div className="wrap reading-page"><PageHead kicker="PAGE NOT FOUND" title="这一页暂时没有内容。" description="从首页或主题库，继续探索现有资料。" /><Link className="button primary" to="/">返回首页 <Arrow /></Link></div>;
}
