"""Only cited claims carry generated factual content; auxiliary copy is owned here."""
from dataclasses import replace

EXTRACTIVE_LIMITATIONS = (
    "当前为离线可审计模式：回答直接摘取经核对的知识页或文献摘要，不进行超出证据的推断。",
    "内容仅供学习与研究，不构成诊疗建议；个体决策需由临床专业人员结合完整病史与检查完成。",
)


def sanitize_generated_metadata(answer):
    # The generation schema has no claim-citation mapping on these fields.
    # Do not label arbitrary model text as a supported limitation or next step.
    allowed = set(EXTRACTIVE_LIMITATIONS if answer.generator == "extractive" else EXTRACTIVE_LIMITATIONS[1:])
    limitations = [text for text in answer.limitations if text in allowed]
    if not limitations and not answer.refused:
        limitations = [EXTRACTIVE_LIMITATIONS[1]]
    return replace(answer,
                   reason="生成器判断当前证据不足，未形成可核验的回答。" if answer.refused else "",
                   refusal_code="GENERATOR_REFUSAL" if answer.refused else "",
                   found=[], missing=[], next_steps=[], limitations=limitations)
