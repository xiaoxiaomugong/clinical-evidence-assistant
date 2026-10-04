/* Local interaction prototype. No API calls, storage, analytics or medical inference. */
(() => {
  'use strict';
  const { topics, sources } = window.PROTOTYPE_CONTENT;
  const main = document.getElementById('main');
  const state = { draft: '', pico: { population: '', intervention: '', comparison: '', outcome: '' }, picoOpen: false, result: null, pending: null, timer: null, route: '/' };
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const byId = id => topics.find(topic => topic.id === id) || topics[0];
  const unique = list => [...new Set(list)];
  const idsFor = topic => unique(topic.claims.flatMap(claim => claim.sourceIds));
  const arrow = '<span class="arrow" aria-hidden="true">↗</span>';
  const announce = message => { document.getElementById('announcer').textContent = message; };
  const isAsk = () => state.route === '/ask' || state.route === '/professional';
  const audience = () => state.route === '/professional' ? 'professional' : 'public';
  const audienceName = value => value === 'professional' ? '专业版' : '公众版';
  const snippet = { hypertension:'了解血压管理与相关研究。', lipids:'看懂风险评估与降脂证据。', diabetes:'认识不同治疗研究的关注点。', stroke:'了解再次发生风险的研究。', lifestyle:'从饮食与活动理解健康。' };

  function topicCard(topic, large = false) {
    return `<a class="topic-card" href="#/topics/${topic.id}"><span class="topic-number">${topic.number}</span><span class="corner-arrow" aria-hidden="true">↗</span><h3>${esc(topic.name)}</h3><p>${esc(large ? topic.description : snippet[topic.id])}</p>${large ? '<span class="text-link">查看主题与来源 <span aria-hidden="true">→</span></span>' : ''}</a>`;
  }

  function home() {
    return `<div class="wrap"><section class="hero"><div class="hero-copy"><span class="eyebrow">A CLEARER WAY TO UNDERSTAND HEALTH</span><h1>健康信息很多，<br><em>让证据帮你看清。</em></h1><p class="lead">了解研究说了什么，也看清它适用于谁。<br>从一个问题出发，找到可以回查的来源。</p><div class="hero-actions"><a class="button primary" href="#/ask">了解健康知识 ${arrow}</a><a class="button ghost" href="#/professional">检索临床证据 ${arrow}</a></div><p class="hero-footnote">面向健康知识学习与研究，个体诊疗请咨询专业人员。</p></div><div class="hero-scene" aria-label="示意：回答可逐条查看证据来源"><div class="scene-grid"></div><div class="scene-orbit"></div><div class="evidence-sheet"><div class="sheet-head"><span class="tag">THE EVIDENCE NOTE / 001</span><span class="sheet-logo" aria-hidden="true">✳</span></div><h3>每一个结论，<br>都有值得细读的来源。</h3><div class="sheet-line"></div><div class="sheet-line short"></div><div class="sheet-citation"><span class="citation-square">01</span><span>世界卫生组织 · 指南<small>ADULT HYPERTENSION / 2022</small></span></div><div class="sheet-citation"><span class="citation-square">02</span><span>TIME study · 随机试验<small>THE LANCET / 2022</small></span></div><div class="sheet-check"><b aria-hidden="true">↗</b>沿着引用，回到原文</div></div><span class="scene-note">A NOTE, GROUNDED IN SOURCES</span></div></section><section class="trust-strip" aria-label="示例文献来源"><p>示例文献<br>来自公开来源</p><div class="source-wordmarks"><span>PubMed</span><span>WHO</span><span class="sans">THE LANCET</span><span class="sans">Diabetes Care</span></div><small>展示来源名称<br>不表示合作或背书</small></section><section class="section"><div class="section-head"><div><span class="eyebrow">START WITH A TOPIC</span><h2>从你关心的主题开始</h2><p>先把一个问题弄清楚，再向更深处了解。</p></div><a class="text-link" href="#/topics">全部示例主题 <span aria-hidden="true">→</span></a></div><div class="topic-grid">${topics.map(topic => topicCard(topic)).join('')}</div></section><section class="guide-section"><div><span class="eyebrow">HOW IT WORKS</span><h2>答案之外，<br>还有理解的路径。</h2></div><div class="guide-steps"><div><span class="step-index">01</span><h3>提出一般问题</h3><p>从你想了解的知识出发，<br>保留必要的研究条件。</p></div><div><span class="step-index">02</span><h3>读懂研究发现</h3><p>一起看研究对象、结论，<br>以及仍不确定的部分。</p></div><div><span class="step-index">03</span><h3>回到证据来源</h3><p>沿着编号查看文献，<br>让理解有迹可循。</p></div></div></section></div>`;
  }

  function pageHead(kicker, title, description, switcher = false, breadcrumb = '') {
    return `<header class="page-head">${breadcrumb || '<div class="breadcrumbs"><a href="#/">首页</a><span aria-hidden="true">/</span><span>'+esc(title)+'</span></div>'}<div class="page-title-row"><div><span class="eyebrow">${kicker}</span><h1>${title}</h1><p class="lead">${description}</p></div>${switcher ? `<div class="mode-switch" aria-label="选择阅读方式"><a href="#/ask" class="${audience()==='public'?'active':''}" ${audience()==='public'?'aria-current="page"':''}>公众版 · 易读解释</a><a href="#/professional" class="${audience()==='professional'?'active':''}" ${audience()==='professional'?'aria-current="page"':''}>专业版 · 证据检索</a></div>` : ''}</div></header>`;
  }

  function scenarioPanel() {
    return `<details class="scenario-panel"><summary>原型工具 · 体验不同状态</summary><div class="scenario-buttons"><button data-scenario="answered">示例回答</button><button data-scenario="loading">加载中</button><button data-scenario="insufficient">证据不足</button><button data-scenario="privacy">隐私拦截</button><button data-scenario="busy">服务繁忙</button></div><p>这些按钮切换固定演示状态，不执行实际检测。</p></details>`;
  }

  function sideNote() {
    return `<aside class="side-note"><span class="eyebrow">A SMALL NOTE BEFORE YOU ASK</span><h3>好问题，从保留边界开始</h3><p>描述你想了解的研究或一般知识，让证据帮助你理解。</p><ul><li>避免填写姓名、电话和病历号</li><li>个体用药调整请咨询医生</li><li>留意研究人群与资料日期</li></ul><a class="text-link" href="#/methodology">我们如何呈现证据 <span aria-hidden="true">→</span></a><div class="topic-links">${topics.map(topic => `<a href="#/topics/${topic.id}">${topic.name}</a>`).join('')}</div></aside>`;
  }

  function questionCard(pro) {
    return `<form id="question-form" class="question-card" novalidate><label class="field-label" for="question">${pro?'研究问题':'你想了解什么？'}<small>一般知识与研究问题</small></label><textarea id="question" name="question" maxlength="4000" aria-describedby="input-hint input-error" placeholder="例如：关于早晨和晚间服用降压药，研究发现了什么？">${esc(state.draft)}</textarea><div class="input-meta"><span id="input-hint">请勿输入可识别个人的信息</span><span id="char-count">${state.draft.length} / 4000</span></div><p id="input-error" class="fine-print error-text" role="alert"></p>${pro ? `<details class="pico-details" id="pico-details" ${state.picoOpen?'open':''}><summary>补充 PICO 检索条件 <span class="tag">可选</span></summary><div class="pico-fields">${[['population','P · 人群','例如：成人高血压研究人群'],['intervention','I · 干预','例如：晚间服药'],['comparison','C · 对照','例如：早晨服药'],['outcome','O · 结局','例如：心血管结局']].map(([key,label,placeholder])=>`<label for="pico-${key}">${label}<input id="pico-${key}" name="${key}" data-pico="${key}" value="${esc(state.pico[key])}" placeholder="${placeholder}" maxlength="300"></label>`).join('')}</div></details>`:''}<div class="submit-row"><small>提交将展示对应主题的固定示例，<br>不针对输入生成医学回答。</small><button class="button primary" type="submit">${pro?'查看证据示例':'查看回答示例'} <span aria-hidden="true">→</span></button></div><div class="example-box"><p>还没有具体问题？试试这些</p><div class="example-chips">${topics.filter(topic=>['hypertension','lipids','lifestyle'].includes(topic.id)).map(topic=>`<button type="button" class="example-chip" data-example="${topic.id}">${esc(topic.question)}</button>`).join('')}</div></div></form>`;
  }

  function askPage() {
    const pro = audience() === 'professional';
    return `<div class="wrap">${pageHead(pro?'FOR CLINICAL LEARNING & RESEARCH':'HEALTH KNOWLEDGE, MADE CLEAR',pro?'带着问题，回到证据。':'把健康问题，问得更明白。',pro?'整理研究条件，阅读证据摘要，逐条核对来源。':'用容易理解的方式读研究，也了解结论的适用范围。',true)}<div class="ask-layout ${pro?'professional':''}">${pro?`<div class="pro-left">${questionCard(true)}${scenarioPanel()}${sideNote()}</div><div class="pro-right"><section id="result" class="result-area" aria-label="问答结果">${resultMarkup()}</section></div>`:`<div class="ask-main">${questionCard(false)}<section id="result" class="result-area" aria-label="问答结果">${resultMarkup()}</section></div><div class="ask-sidebar">${sideNote()}${scenarioPanel()}</div>`}</div></div>`;
  }

  function citationButtons(sourceIds, allIds) {
    return sourceIds.map(id=>`<button class="citation-button" data-source="${id}" data-source-number="${allIds.indexOf(id)+1}" aria-label="查看引用 ${allIds.indexOf(id)+1}：${esc(sources[id]?.title || id)}">${allIds.indexOf(id)+1}</button>`).join('');
  }

  function sourceList(topic, sectionId = 'answer-sources', selectedIds = idsFor(topic)) {
    return `<section class="source-section" id="${sectionId}" tabindex="-1"><h3>沿着引用，查看来源 <small>${selectedIds.length} 条示例来源</small></h3>${selectedIds.map((id,index)=>{ const source=sources[id];return `<button class="source-row" data-source="${id}" data-source-number="${index+1}"><span class="citation-square">${String(index+1).padStart(2,'0')}</span><span><span class="source-name">${esc(source.title)}</span><span class="source-details">${esc([source.type,source.journal,source.year,`PMID ${id}`].filter(Boolean).join(' · '))}</span></span>${arrow}</button>`;}).join('')}</section>`;
  }

  function resultMarkup() {
    if(state.pending) return statusMarkup('loading');
    if(!state.result) return `<div class="empty-state"><div class="empty-glyph" aria-hidden="true"><i></i><i></i><i></i></div><h2>先有问题，再看证据。</h2><p>提交一个示例问题后，<br>在这里阅读回答、适用范围和原始来源。</p><div class="empty-flow"><span>一般问题</span><span aria-hidden="true">→</span><span>证据摘要</span><span aria-hidden="true">→</span><span>原始来源</span></div></div>`;
    if(state.result.status!=='answered') return statusMarkup(state.result.status);
    const result=state.result, topic=byId(result.topicId), pro=result.audience==='professional';
    // Public view gives two shorter original claims; professional view preserves all claim contexts.
    const claims=pro ? topic.claims : topic.id==='hypertension' ? [topic.claims[2],topic.claims[0]] : topic.claims.slice(0,2);
    const ids=unique(claims.flatMap(claim=>claim.sourceIds));
    return `${result.audience!==audience()?`<p class="same-result-note">当前保留的是${audienceName(result.audience)}示例。切换入口不会自动重新生成；可再次提交查看${audienceName(audience())}版式。</p>`:''}<article class="answer-card"><div class="answer-top"><span class="eyebrow">${pro?'EVIDENCE SUMMARY':'READ THE EVIDENCE'}</span><span class="pill green">来源摘录 · ${audienceName(result.audience)}示例</span></div><h2>${pro?'研究如何回答这个问题':'先看研究说了什么'}</h2><p class="answer-kicker">示例主题：${esc(topic.name)} · 固定内容，未执行实时检索</p><div class="answer-intro">${pro?'以下按研究陈述整理项目现有快照。PICO 条件仅用于演示交互，不改变本页证据内容。':'以下展示现有知识页摘录。它帮助你了解页面如何呈现证据，不是针对本次输入生成的回答。'}</div>${claims.map((claim,index)=>`<section class="answer-claim"><h3><span>${String(index+1).padStart(2,'0')}</span>${index===0?'研究发现与范围':pro?'补充证据与适用人群':'结合背景一起理解'}</h3><p>${esc(claim.text)} ${citationButtons(claim.sourceIds,ids)}</p>${pro?`<div class="claim-context"><b>适用人群</b> ${esc(claim.applicable)}<br><b>研究边界</b> ${esc(claim.exceptions)}</div>`:''}</section>`).join('')}<aside class="context-box"><h3>这些边界，也值得一起读</h3><p>${esc(topic.limitations)}</p></aside><div class="answer-meta"><span>知识页更新：${esc(topic.updatedAt)}</span><span>实时资料：未检索</span><span>证据确定性：未独立评定</span></div><div class="answer-actions"><button class="text-link" data-scroll-sources>查看 ${ids.length} 条引用来源 <span aria-hidden="true">↓</span></button><button class="text-link" data-open-feedback>这个示例哪里可以更清楚？ <span aria-hidden="true">↗</span></button></div></article><p class="result-note">当前为交互演示。原型制作没有重新开展临床评审，个体诊疗请咨询专业人员。</p>${sourceList(topic,'answer-sources',ids)}`;
  }

  function statusMarkup(status) {
    if(status==='loading') return `<div class="status-card"><div class="status-icon"><div class="spinner" aria-hidden="true"></div></div><span class="eyebrow" style="margin-top:18px">EXAMPLE IN PROGRESS</span><h2>正在整理示例证据</h2><p>先找到来源，再看看结论适用于谁。</p><div class="progress-track" aria-hidden="true"><div></div></div><div class="status-steps"><span>读取本地示例</span><span aria-hidden="true">→</span><span class="active">整理展示内容</span><span aria-hidden="true">→</span><span>显示引用</span></div><button class="button small ghost" data-reset>取消演示</button><p class="fine-print">这是加载状态演示，未发起网络请求。</p></div>`;
    const states={
      insufficient:{className:'warning',icon:'?',kicker:'MORE EVIDENCE IS NEEDED',title:'现有示例还不足以回答',body:'这个原型仅包含五个主题的固定示例。我们暂不把范围之外的内容拼成一个答案。',action:'选一个示例问题',note:'正式产品将依据检索结果判断证据是否充分；这里仅演示拒答页面。'},
      privacy:{className:'danger',icon:'◇',kicker:'KEEP PERSONAL DETAILS PRIVATE',title:'先去掉可识别个人的信息',body:'当前展示隐私拦截状态。请删除姓名、电话、病历号等信息，再改成一般知识问题。',action:'返回修改问题',note:'页面没有执行检索或外发。原型中的简单匹配不代表正式隐私检测能力。'},
      busy:{className:'warning',icon:'◷',kicker:'A MOMENT TO PAUSE',title:'服务繁忙，请稍后再试',body:'这是容量已满时的状态示例。你仍然可以先浏览主题库，阅读已有的知识与来源。',action:'重新体验示例',note:'本页没有真实排队，也没有发生模型调用或扣费。'}
    };
    const value=states[status]||states.insufficient;
    return `<div class="status-card ${value.className}"><div class="status-icon" aria-hidden="true">${value.icon}</div><span class="eyebrow" style="margin-top:19px">${value.kicker}</span><h2>${value.title}</h2><p>${value.body}</p><button class="button primary" data-reset>${value.action} <span aria-hidden="true">→</span></button> <a class="text-link" href="#/topics" style="margin:15px 0 0 13px">浏览主题库</a><p class="fine-print">${value.note}</p></div>`;
  }

  function topicsPage() {
    return `<div class="wrap topics-index">${pageHead('THE TOPIC LIBRARY','从一个主题，慢慢读懂。','五个示例主题，保留来源、研究对象和适用边界。内容来自项目现有知识页。')}<div class="topic-grid large">${topics.map(topic=>topicCard(topic,true)).join('')}</div><p class="fine-print" style="margin-top:23px">更新日期按各知识页记录展示，不表示本次原型制作完成了医学内容复核。</p></div>`;
  }

  function topicPage(id) {
    const topic=topics.find(item=>item.id===id);
    if(!topic) return notFound();
    const ids=idsFor(topic);
    return `<div class="wrap">${pageHead('TOPIC NOTE / '+topic.number,esc(topic.name),esc(topic.description),false,`<div class="breadcrumbs"><a href="#/">首页</a><span>/</span><a href="#/topics">主题库</a><span>/</span><span>${esc(topic.name)}</span></div>`)}<div class="article-layout"><div><article class="article-card"><span class="pill green" style="margin-bottom:21px">项目知识页 · 示例摘录</span><h2>把研究发现与边界放在一起</h2>${topic.claims.map(claim=>`<section class="topic-claim"><p>${esc(claim.text)} ${citationButtons(claim.sourceIds,ids)}</p><div class="claim-context"><b>适用人群</b> ${esc(claim.applicable)}<br><b>需要留意</b> ${esc(claim.exceptions)}</div></section>`).join('')}<aside class="context-box"><h3>主题局限</h3><p>${esc(topic.limitations)}</p></aside></article>${sourceList(topic,'topic-sources')}</div><aside class="side-note"><span class="eyebrow">ABOUT THIS NOTE</span><h3>一份可以回查的笔记</h3><p>知识页更新<br><b>${esc(topic.updatedAt)}</b></p><p style="margin-top:14px">审核状态<br>本次原型未重新开展内容评审</p><span class="pill">${ids.length} 条示例来源</span><button class="button primary" data-ask-topic="${topic.id}">体验这个主题 ${arrow}</button><p class="fine-print" style="margin-top:16px">医学内容用于展示信息结构，不作为个体诊疗建议。</p></aside></div></div>`;
  }

  const readingPages={
    methodology:{kicker:'METHOD & SOURCES',title:'让来源清楚，让边界可见。',intro:'我们希望每一段解释，都有一条可以继续阅读的路径。',body:`<section class="reading-block"><h2>这个原型如何工作</h2><p>你正在浏览可点击设计原型。输入、PICO 条件、加载和反馈都在当前浏览器中演示，不连接模型或检索服务，也不保存问答历史。</p><div class="method-flow"><div><span>01</span>选择示例主题</div><div><span>02</span>阅读知识页摘录</div><div><span>03</span>查看适用边界</div><div><span>04</span>回查来源</div></div></section><section class="reading-block"><h2>内容来自哪里</h2><p>示例来自项目现有的五个知识页及文献快照。来源保留已有题名、年份、研究类型和 PMID。元数据缺失时会如实说明；知识页日期是原有记录，不是本次审核日期。</p><p>点击来源卡片可以阅读本地摘录；“打开原始来源”会在新标签页访问对应的 PubMed 页面。</p></section><section class="reading-block"><h2>公众版与专业版有什么区别</h2><p>公众版集中呈现较少的原文陈述和主题局限；专业版展示更多研究条件、适用人群及来源信息。专业版入口不是医师身份认证，两版都用于一般知识学习与研究。</p><p>原型阶段保留已有文字，尚未对公众版示例开展新一轮通俗表达和临床审核。正式版本的通俗改写也需要经过引用与支持性检查。</p></section><section class="reading-block"><h2>引用并不等于结论已经被证明</h2><p>有来源，意味着可以继续核查。研究的质量、适用人群、结局和限制仍需判断。这个原型不会用“引用存在”来宣称医学正确率，也不会给未独立评定的证据贴上确定性等级。</p></section>`},
    privacy:{kicker:'PRIVACY, BY DESIGN',title:'理解健康，不必交出隐私。',intro:'当前原型的数据处理方式，尽量说清楚。',body:`<section class="reading-block"><h2>当前页面会处理什么</h2><p>输入框中的草稿、PICO 条件、反馈选择和页面状态只存在于当前页面内存中。刷新或关闭页面后清除；未使用 Cookie、浏览器本地存储或第三方分析脚本。</p></section><section class="reading-block"><h2>哪些内容会发出浏览器</h2><p>原型不发送题干、条件或反馈，不连接实时检索或模型。加载本地网页资源会访问当前预览服务器；点击文献的“打开原始来源”将访问相应外部网站，该网站有自己的隐私政策。</p></section><section class="reading-block"><h2>请使用一般知识问题</h2><p>不填写姓名、手机号、身份证号、病历号或完整病历。隐私拦截按钮用于查看页面设计；输入框的简单演示匹配不能证明已识别所有敏感信息。</p></section><section class="reading-block"><h2>正式上线时</h2><p>运营主体、实际处理的数据、保存期限、第三方服务及删除请求渠道，会根据最终实现另行明确。这页是原型说明，不作为尚未上线服务的完整隐私政策。</p></section>`},
    terms:{kicker:'USING THIS PROTOTYPE',title:'带着边界，阅读证据。',intro:'这是一份产品设计预览，欢迎沿着页面探索。',body:`<section class="reading-block"><h2>如何体验</h2><p>选择公众版或专业版，点选示例问题，提交后阅读固定示例。点击正文引用编号查看来源，使用“原型工具”切换加载、证据不足、隐私拦截和服务繁忙状态。</p></section><section class="reading-block"><h2>使用范围</h2><p>示例用于一般健康知识学习和产品交互展示，不提供个体诊断、处方、剂量、停药或换药建议。原型没有真实的账号、收藏、付费或文件上传功能。</p></section><section class="reading-block"><h2>资料的时间与状态</h2><p>页面内容来自现有项目快照，可能不包含最新研究；本次制作未重新开展医学评审。应结合原始来源及适用范围理解，不能把页面示例直接用于个人诊疗决策。</p></section>`},
    contact:{kicker:'FEEDBACK & CONTACT',title:'让难理解的地方，更清楚。',intro:'先体验反馈方式，再一起完善设计。',body:`<section class="reading-block"><h2>对原型留下反馈</h2><p>你可以体验三个反馈标签。选择会在当前页面显示确认，不会发送或保存。具体设计意见请直接在当前 Codex 对话中提出。</p><button class="button primary" data-open-feedback style="margin-top:20px">体验反馈 ${arrow}</button></section><section class="reading-block"><h2>正式站点的联系信息</h2><p>网站运营主体及实际投诉、反馈渠道将在正式发布前确定。本原型不展示虚构的联系地址、处理承诺或备案编号。</p></section>`}
  };

  function readingPage(key){ const page=readingPages[key];return `<div class="wrap reading-page">${pageHead(page.kicker,page.title,page.intro)}<article class="reading-card">${page.body}</article></div>`; }
  function notFound(){return `<div class="wrap reading-page">${pageHead('PAGE NOT FOUND','这一页暂时没有内容。','从首页或主题库，继续探索这份原型。')}<a class="button primary" href="#/">返回首页 ${arrow}</a></div>`;}

  function renderRoute(focus = true) {
    state.route=location.hash.slice(1).split('?')[0] || '/';
    if(!state.route.startsWith('/')) state.route='/';
    if(state.route==='/') main.innerHTML=home();
    else if(isAsk()) main.innerHTML=askPage();
    else if(state.route==='/topics') main.innerHTML=topicsPage();
    else if(state.route.startsWith('/topics/')) main.innerHTML=topicPage(state.route.slice('/topics/'.length));
    else if(readingPages[state.route.slice(1)]) main.innerHTML=readingPage(state.route.slice(1));
    else main.innerHTML=notFound();
    document.querySelectorAll('[data-nav]').forEach(link=>{if(state.route.startsWith('/'+link.dataset.nav))link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');});
    document.getElementById('main-nav').classList.remove('open');
    document.getElementById('menu-toggle').setAttribute('aria-expanded','false');
    document.getElementById('menu-toggle').setAttribute('aria-label','打开导航');
    const title=main.querySelector('h1')?.textContent || '循证知问';
    document.title=title+' · 循证知问原型';
    if(focus){main.focus({preventScroll:true});window.scrollTo({top:0,behavior:'instant'});announce(title);}
    main.querySelector('#pico-details')?.addEventListener('toggle',event=>{state.picoOpen=event.target.open;});
  }

  function refreshResult(shouldScroll = false) {
    const result=document.getElementById('result');
    if(!result)return;
    result.innerHTML=resultMarkup();
    if(shouldScroll)result.scrollIntoView({behavior:'smooth',block:'start'});
  }

  function clearPending(){clearTimeout(state.timer);state.pending=null;state.timer=null;}
  function setResult(status,topicId='hypertension') {clearPending();state.result={status,topicId,audience:audience()};refreshResult(true);announce(status==='answered'?'示例回答已显示，可点击引用查看来源':'已显示'+({privacy:'隐私拦截',busy:'服务繁忙',insufficient:'证据不足'}[status]||'演示')+'状态');}
  function exampleTopic(text){
    const normalize=value=>value.trim().replace(/[\s？?。]/g,'');
    const matched=topics.find(topic=>normalize(topic.question)===normalize(text));
    if(matched)return matched.id;
    return normalize(text)===normalize('关于早晨和晚间服用降压药，研究发现了什么？')?'hypertension':null;
  }

  function submitExample(){
    const question=document.getElementById('question');
    const error=document.getElementById('input-error');
    state.draft=question.value;
    if(!state.draft.trim()){error.textContent='先填写一个问题，或点选下方示例。';question.setAttribute('aria-invalid','true');question.focus();return;}
    error.textContent='';question.removeAttribute('aria-invalid');
    if(/(?:1[3-9]\d{9})|(?:姓名|病历号|身份证号)\s*[:：]\s*\S+/.test(state.draft)){setResult('privacy');return;}
    const topicId=exampleTopic(state.draft);
    if(!topicId){setResult('insufficient');return;}
    beginLoading(topicId,false);
  }

  function beginLoading(topicId,stay){
    clearPending();state.pending={topicId,audience:audience()};state.result=null;refreshResult(true);announce('正在演示整理示例证据');
    if(stay)return;
    const pending={...state.pending};
    state.timer=setTimeout(()=>{state.pending=null;state.result={status:'answered',topicId:pending.topicId,audience:pending.audience};refreshResult();announce('示例回答已显示。正文引用可打开来源详情。');},1100);
  }

  function openSource(id,number){
    const source=sources[id];if(!source)return;
    document.getElementById('source-content').innerHTML=`<div class="dialog-body"><form method="dialog"><button class="dialog-close" aria-label="关闭来源详情">×</button></form><span class="eyebrow">SOURCE NOTE / ${esc(number || '01')}</span><h2 id="source-title">${esc(source.title)}</h2><div class="source-attributes"><span class="pill green">${esc(source.type)}</span><span class="pill">${source.year?esc(source.year):'年份未记录'}</span><span class="pill">PMID ${esc(id)}</span></div><p class="fine-print">${esc(source.journal || '期刊信息未记录')}</p><h3 style="font-size:12px">项目现有摘录</h3><div class="source-excerpt">${esc(source.excerpt)}</div><p class="fine-print">本地快照用于交互演示，未在本次制作中重新核验。请在原始来源中查看完整方法、结果和限制。</p><a class="button primary" href="${esc(source.url)}" target="_blank" rel="noopener noreferrer">打开原始来源 ${arrow}</a></div>`;
    document.getElementById('source-dialog').showModal();
  }

  function openFeedback(){document.getElementById('feedback-status').textContent='';document.querySelectorAll('[data-feedback]').forEach(button=>{button.classList.remove('selected');button.setAttribute('aria-pressed','false');});document.getElementById('feedback-dialog').showModal();}

  document.addEventListener('click',event=>{
    const trigger=event.target.closest('button, a');if(!trigger)return;
    if(trigger.matches('[data-example]')){state.draft=byId(trigger.dataset.example).question;const question=document.getElementById('question');question.value=state.draft;question.removeAttribute('aria-invalid');document.getElementById('char-count').textContent=state.draft.length+' / 4000';document.getElementById('input-error').textContent='';question.focus();}
    if(trigger.matches('[data-ask-topic]')){state.draft=byId(trigger.dataset.askTopic).question;state.result=null;clearPending();location.hash='/ask';}
    if(trigger.matches('[data-source]'))openSource(trigger.dataset.source,trigger.dataset.sourceNumber);
    if(trigger.matches('[data-scroll-sources]')){const target=document.getElementById('answer-sources');target.scrollIntoView({behavior:'smooth',block:'start'});target.focus({preventScroll:true});}
    if(trigger.matches('[data-open-feedback]'))openFeedback();
    if(trigger.matches('[data-feedback]')){document.querySelectorAll('[data-feedback]').forEach(button=>{const selected=button===trigger;button.classList.toggle('selected',selected);button.setAttribute('aria-pressed',String(selected));});document.getElementById('feedback-status').textContent='已选择“'+trigger.dataset.feedback+'”。这是本地演示，未发送。';}
    if(trigger.matches('[data-scenario]')){const status=trigger.dataset.scenario;if(status==='loading')beginLoading('hypertension',true);else setResult(status);}
    if(trigger.matches('[data-reset]')){clearPending();state.result=null;refreshResult();document.getElementById('question')?.focus();announce('已重置示例，可以修改问题或选择示例。');}
  });
  document.addEventListener('input',event=>{if(event.target.id==='question'){state.draft=event.target.value;document.getElementById('char-count').textContent=state.draft.length+' / 4000';event.target.removeAttribute('aria-invalid');document.getElementById('input-error').textContent='';}if(event.target.dataset.pico)state.pico[event.target.dataset.pico]=event.target.value;});
  document.addEventListener('submit',event=>{if(event.target.id==='question-form'){event.preventDefault();submitExample();}});
  document.getElementById('menu-toggle').addEventListener('click',event=>{const button=event.currentTarget;const open=document.getElementById('main-nav').classList.toggle('open');button.setAttribute('aria-expanded',String(open));button.setAttribute('aria-label',open?'关闭导航':'打开导航');});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'){
    const nav=document.getElementById('main-nav'), menu=document.getElementById('menu-toggle');
    const restoreFocus=nav.classList.contains('open')&&nav.contains(document.activeElement)&&menu.offsetParent!==null;
    nav.classList.remove('open');menu.setAttribute('aria-expanded','false');menu.setAttribute('aria-label','打开导航');
    if(restoreFocus)menu.focus();
  }});
  for(const dialog of document.querySelectorAll('dialog'))dialog.addEventListener('click',event=>{if(event.target===dialog){const box=dialog.getBoundingClientRect();if(event.clientX<box.left||event.clientX>box.right||event.clientY<box.top||event.clientY>box.bottom)dialog.close();}});
  window.addEventListener('hashchange',()=>{if(location.hash==='#main'){main.focus();return;}renderRoute();});
  renderRoute(false);
})();
