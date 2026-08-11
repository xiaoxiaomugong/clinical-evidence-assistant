from __future__ import annotations

import html
import sys
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import streamlit as st

from config import settings
from evidence_assistant.pipeline import EvidencePipeline


st.set_page_config(
    page_title="循证知问 · Clinical Evidence",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root {
        --ink: #102a2e;
        --muted: #61777a;
        --teal: #0b7b75;
        --teal-dark: #075d59;
        --mint: #e9f6f2;
        --paper: #f7faf8;
        --line: #dce9e5;
        --amber: #9b6613;
    }
    .stApp { background: linear-gradient(180deg, #f3faf7 0, #ffffff 320px); color: var(--ink); }
    .block-container { max-width: 1180px; padding-top: 4.25rem; padding-bottom: 4rem; }
    [data-testid="stSidebar"] { background: #102e31; }
    [data-testid="stSidebar"] * { color: #edf8f5; }
    [data-testid="stSidebar"] .stRadio label,
    [data-testid="stSidebar"] .stCheckbox label { color: #edf8f5 !important; }
    .brand-kicker { color: var(--teal); font-weight: 800; letter-spacing: .12em; font-size: .78rem; }
    .hero-title { color: var(--ink); font-size: clamp(2.25rem, 5vw, 4.4rem); line-height: 1.02; margin: .35rem 0 .9rem; letter-spacing: -.045em; }
    .hero-copy { color: var(--muted); font-size: 1.08rem; max-width: 760px; line-height: 1.75; }
    .scope-strip { margin: 1.5rem 0 1.8rem; padding: .75rem 1rem; border: 1px solid var(--line); border-radius: 14px; background: rgba(255,255,255,.72); color: var(--muted); font-size: .9rem; }
    .status-good, .status-warn, .status-stop { display: inline-flex; align-items: center; border-radius: 99px; padding: .33rem .68rem; font-size: .8rem; font-weight: 750; }
    .status-good { color: #08645f; background: #dcf4ed; }
    .status-warn { color: #8b5d14; background: #fff2d6; }
    .status-stop { color: #a13d3d; background: #fde8e6; }
    .answer-panel { border: 1px solid var(--line); border-radius: 20px; padding: 1.35rem 1.45rem; background: rgba(255,255,255,.92); box-shadow: 0 14px 45px rgba(19,73,69,.07); margin-bottom: 1rem; }
    .answer-panel h3 { margin: 0 0 .4rem; color: var(--ink); }
    .answer-meta { color: var(--muted); font-size: .82rem; }
    .disclaimer { border-left: 3px solid #d7a13e; color: #6f572b; background: #fffaf0; padding: .75rem 1rem; border-radius: 0 10px 10px 0; font-size: .88rem; }
    .mini-label { color: var(--teal); font-size: .74rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
    div[data-testid="stMetric"] { background: #fff; border: 1px solid var(--line); padding: .7rem 1rem; border-radius: 14px; }
    [data-testid="stSidebar"] div[data-testid="stMetric"] { background: rgba(255,255,255,.08); border-color: rgba(255,255,255,.14); }
    [data-testid="stSidebar"] div[data-testid="stMetric"] * { color: #f0fbf8 !important; }
    div[data-testid="stExpander"] { background: rgba(255,255,255,.86); border-color: var(--line); border-radius: 14px; }
    .evidence-level { display: inline-block; padding: .2rem .5rem; border-radius: 6px; background: var(--mint); color: var(--teal-dark); font-size: .75rem; font-weight: 800; }
    .sidebar-brand { font-size: 1.2rem; font-weight: 850; margin: .4rem 0 1.5rem; }
    .sidebar-note { color: #b8cfcc !important; font-size: .82rem; line-height: 1.6; }
    .stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] button { background: var(--teal) !important; border-color: var(--teal) !important; color: #fff !important; border-radius: 10px; font-weight: 750; }
    .stButton > button { border-radius: 10px; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_pipeline() -> EvidencePipeline:
    return EvidencePipeline(settings)


def set_example(question: str) -> None:
    st.session_state["question"] = question


def render_answer(result) -> None:
    if result.degraded:
        reasons = "；".join(result.degradation_reasons) or "可选模型后端不可用"
        st.warning(
            f"本次已安全降级：检索={result.retrieval_backend}，"
            f"重排={result.rerank_backend}。{reasons}"
        )
    if result.answer.refused:
        st.markdown('<span class="status-stop">证据不足 · 已安全拒答</span>', unsafe_allow_html=True)
        st.error(result.answer.reason)
        if result.answer.found:
            st.markdown("**已找到什么**")
            for item in result.answer.found:
                st.caption(f"— {item}")
        if result.answer.missing:
            st.markdown("**还缺什么**")
            for item in result.answer.missing:
                st.caption(f"— {item}")
        if result.answer.next_steps:
            st.markdown("**下一步可查什么**")
            for item in result.answer.next_steps:
                st.caption(f"— {item}")
        if result.answer.refusal_code:
            st.caption(f"拒答原因码：{result.answer.refusal_code}")
        if result.entries:
            st.caption("系统保留了检索轨迹供调试，但不会把低可靠度候选包装成临床结论。")
        return

    valid = result.citation_check and result.citation_check.valid
    sanitized = result.answer.removed_paragraph_count > 0 or (
        result.citation_check and result.citation_check.removed_citation_count > 0
    )
    if valid:
        badge = '<span class="status-good">✓ 引用校验通过</span>'
    elif result.citation_check and result.citation_check.output_valid:
        badge = '<span class="status-warn">✓ 风险陈述已净化</span>'
    else:
        badge = '<span class="status-warn">△ 部分证据需复核</span>'
    st.markdown(badge, unsafe_allow_html=True)
    st.markdown(
        f"""<div class="answer-panel">
        <h3>证据摘要</h3>
        <div class="answer-meta">生成方式：{html.escape(result.answer.generator)} · 检索：{html.escape(result.retrieval_backend)} · 重排：{html.escape(result.rerank_backend)} · {result.elapsed_ms} ms · 语料 {settings.corpus_version}</div>
        </div>""",
        unsafe_allow_html=True,
    )
    entry_map = {entry.citation_number: entry for entry in result.entries}
    for paragraph in result.answer.paragraphs:
        links = []
        for citation_id in paragraph.citation_ids:
            entry = entry_map.get(citation_id)
            if entry and entry.url:
                links.append(f"[[{citation_id}]]({entry.url})")
            else:
                links.append(f"**[{citation_id}]**")
        st.markdown(f"{paragraph.text} {' '.join(links)}")
        st.caption(f"陈述类型：{paragraph.claim_type} · 确定性：{paragraph.certainty}")
    if sanitized:
        st.caption(
            f"输出净化：已删除 {result.answer.removed_paragraph_count} 条无支持陈述和 "
            f"{result.citation_check.removed_citation_count if result.citation_check else 0} 个不可用引用。"
        )
    if result.answer.limitations:
        st.markdown("**局限与边界**")
        for limitation in result.answer.limitations:
            st.caption(f"— {limitation}")


def render_evidence(result) -> None:
    st.markdown("### 可追溯证据")
    st.caption("正文编号对应条目；同一文档的多个 claim/chunk 聚合在一张卡片中。证据等级来自结构化元数据。")
    grouped = defaultdict(list)
    for entry in result.entries:
        grouped[entry.doc_id].append(entry)

    for group in grouped.values():
        numbers = ", ".join(f"[{entry.citation_number}]" for entry in group)
        first = group[0]
        clean_title = first.title.split("｜", 1)[0]
        clean_title = clean_title.split(" · PDF 第", 1)[0].split(" · PubMed 摘要兜底", 1)[0]
        levels = " / ".join(dict.fromkeys(entry.evidence_level for entry in group))
        label = f"{numbers}  {clean_title}  ·  {levels}"
        with st.expander(label):
            metadata = [first.source]
            if first.journal:
                metadata.append(first.journal)
            if first.year:
                metadata.append(str(first.year))
            if first.status:
                metadata.append(f"状态：{first.status}")
            st.markdown(f'<span class="evidence-level">{html.escape(levels)}</span>', unsafe_allow_html=True)
            st.caption(" · ".join(metadata))
            for entry in group:
                st.markdown(
                    f"**[{entry.citation_number}] · {entry.evidence_level} · "
                    f"角色 {entry.evidence_role} · 相关分 {entry.score:.2f}**"
                )
                st.write(entry.text)
            if first.url:
                st.link_button("打开原始来源 ↗", first.url)


pipeline = get_pipeline()

with st.sidebar:
    st.markdown('<div class="sidebar-brand">✦ 循证知问</div>', unsafe_allow_html=True)
    mode_label = st.radio(
        "检索策略",
        ["混合模式", "知识页优先", "RAG 优先"],
        help="混合模式优先使用稳定的知识页/本地快照，相关性不足时再调用实时 API。",
    )
    live_apis = st.toggle(
        "启用实时 API",
        value=settings.enable_live_apis,
        help="访问 PubMed、Europe PMC 和 ClinicalTrials.gov；网络不可用时自动降级。",
    )
    if live_apis:
        st.caption("实时源：PubMed · Europe PMC · ClinicalTrials.gov API v2")
        st.caption("仅发送去标识化后的检索词；检测到疑似 PHI 时会在外部调用前阻断。")
        st.markdown(
            "[NCBI 免责声明与版权](https://www.ncbi.nlm.nih.gov/About/disclaimer.html)",
            help="PubMed 数据由 NCBI E-utilities 提供。",
        )
    st.divider()
    st.markdown("**语料状态**")
    col_a, col_b = st.columns(2)
    col_a.metric("知识页", pipeline.knowledge.page_count)
    col_b.metric("文献快照", pipeline.local_corpus.size)
    pdf_stats = pipeline.pdf_corpus.stats()
    st.metric(
        "PDF 本地库",
        pdf_stats["documents"],
        f"{pdf_stats['full_text']} 篇全文可检索" if pdf_stats["documents"] else "尚未建立索引",
    )
    if pipeline.supabase_corpus:
        st.caption("☁ Supabase 云端证据库已启用；不可用时自动回退本地语料。")
    elif pipeline.supabase_configuration_error:
        st.caption(f"☁ Supabase 配置未生效：{pipeline.supabase_configuration_error}")
    st.markdown(
        '<p class="sidebar-note">覆盖：心脑血管病、血脂、高血压、糖尿病。默认不保存问题，不应输入可识别患者信息。</p>',
        unsafe_allow_html=True,
    )
    st.divider()
    st.markdown("**演示问题**")
    examples = [
        "降压药应早上服用还是睡前服用？",
        "2 型糖尿病合并肥胖，GLP-1 与 SGLT2 如何选择？",
        "高血脂患者服用他汀，肌肉副作用风险有多大？",
        "宠物犬的高血压应该如何用药？",
    ]
    for index, example in enumerate(examples):
        st.button(example, key=f"example_{index}", on_click=set_example, args=(example,), use_container_width=True)

st.markdown('<div class="brand-kicker">CLINICAL EVIDENCE, GROUNDED</div>', unsafe_allow_html=True)
st.markdown('<h1 class="hero-title">先看证据，再谈答案。</h1>', unsafe_allow_html=True)
st.markdown(
    '<p class="hero-copy">面向临床学习与科研的循证问答原型。双路检索、统一重排、证据等级和三道引用校验，让每个结论都能回到原始来源。</p>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="scope-strip">仅供教学与研究，不构成诊断或治疗建议　·　请勿输入姓名、病历号等隐私信息　·　证据不足时系统会明确拒答　·　紧急情况请立即联系当地急救或医疗机构</div>',
    unsafe_allow_html=True,
)

with st.form("question_form"):
    question = st.text_area(
        "输入临床问题",
        key="question",
        height=110,
        placeholder="例如：40 岁男性、无心血管病史、LDL-C 4.2 mmol/L，是否应启动他汀治疗？",
        label_visibility="collapsed",
    )
    submitted = st.form_submit_button("检索可信证据", type="primary", use_container_width=True)

if submitted:
    if not question.strip():
        st.warning("请先输入一个临床问题。")
    else:
        with st.spinner("正在改写问题、检索与核对引用…"):
            result = pipeline.run(question.strip(), mode=mode_label, enable_live_apis=live_apis)
        st.session_state["last_result"] = result

result = st.session_state.get("last_result")
if result:
    st.divider()
    left, right = st.columns([1.55, 1], gap="large")
    with left:
        render_answer(result)
    with right:
        metric_a, metric_b, metric_c = st.columns(3)
        metric_a.metric("候选", len(result.entries))
        checked_count = len(result.citation_check.checked) if result.citation_check else 0
        metric_b.metric("已校验", checked_count)
        metric_c.metric("实时源", "已用" if result.used_live_api else "离线")
    if result.entries:
        render_evidence(result)
    with st.expander("查看检索与校验轨迹"):
        for step, message in enumerate(result.trace, start=1):
            st.markdown(f"`{step:02d}` {message}")
        if result.query_spec:
            st.json({
                "domains": result.query_spec.domains,
                "pico": result.query_spec.pico,
                "api_queries": result.query_spec.api_queries,
                "local_terms": result.query_spec.local_terms,
                "expected_evidence_types": result.query_spec.expected_evidence_types,
                "time_from": result.query_spec.time_from,
                "time_to": result.query_spec.time_to,
                "needs_latest": result.query_spec.needs_latest,
                "personalized_treatment": result.query_spec.personalized_treatment,
                "contains_phi": result.query_spec.contains_phi,
                "retrieval_backend": result.retrieval_backend,
                "rerank_backend": result.rerank_backend,
                "degraded": result.degraded,
                "degradation_reasons": result.degradation_reasons,
            })
