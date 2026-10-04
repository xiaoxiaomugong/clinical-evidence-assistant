// Static snapshots from this project’s knowledge pages and local corpus; this is not a new clinical review or live retrieval.
window.PROTOTYPE_CONTENT = {
  "topics": [
    {
      "id": "hypertension",
      "name": "高血压",
      "number": "01",
      "description": "成人高血压管理需要确认诊断、评估合并症与总体风险，并在生活方式干预基础上个体化选择药物。",
      "question": "高血压的药物治疗和服药时间有哪些现有证据？",
      "updatedAt": "2026-08-11",
      "claims": [
        {
          "text": "WHO 指南面向已准确诊断且接受生活方式干预建议的非妊娠成人，给出了启动药物治疗的血压阈值、治疗目标和随访间隔；长期方案应结合血压控制、耐受性和总体心血管风险复评。",
          "applicable": "已确诊的非妊娠成人高血压患者",
          "exceptions": "妊娠期、继发性高血压或高血压急症需使用专门路径",
          "sourceIds": [
            "34775787"
          ]
        },
        {
          "text": "WHO 指南讨论了单药、双药和单片复方方案；常用起始药物类别包括噻嗪/噻嗪样利尿剂、ACEI/ARB 与长效二氢吡啶类 CCB，具体选择需结合禁忌证、合并症、可及性与患者偏好。",
          "applicable": "需要启动药物治疗的普通成人",
          "exceptions": "ACEI/ARB 不用于妊娠；具体药物须由临床人员结合肾功能、电解质等决定",
          "sourceIds": [
            "34495610"
          ]
        },
        {
          "text": "TIME 随机试验中，常用降压药晚间服用与早晨服用在主要心血管结局上没有显著差异；多数患者可选择更便于坚持且能减少不良反应的服药时间。",
          "applicable": "正在服用至少一种常规降压药的成人高血压患者",
          "exceptions": "利尿剂、夜间低血压风险或特殊医嘱可能影响时间选择",
          "sourceIds": [
            "36240838"
          ]
        }
      ],
      "limitations": "未覆盖妊娠、高血压急症和全部合并症；不能替代个体化处方。"
    },
    {
      "id": "lipids",
      "name": "血脂管理",
      "number": "02",
      "description": "降脂治疗以总体动脉粥样硬化性心血管风险为基础，高危人群通常以他汀为核心并按反应复评。",
      "question": "血脂管理中的风险评估、他汀治疗和肌肉症状有哪些现有证据？",
      "updatedAt": "2026-08-11",
      "claims": [
        {
          "text": "胆固醇管理指南强调先评估 ASCVD 风险、危险增强因素与患者偏好，再共同决定他汀强度；LDL-C 显著升高或已存在 ASCVD 的人群通常属于药物治疗优先级较高者。",
          "applicable": "成人原发或继发预防场景",
          "exceptions": "妊娠、严重肝病及特殊遗传性血脂异常需要专门评估",
          "sourceIds": [
            "31132793"
          ]
        },
        {
          "text": "大规模双盲随机试验个体数据荟萃分析显示，他汀导致的肌痛或无力绝对增量较小，主要集中在治疗第一年；多数服药期间报告的肌肉症状并非由他汀本身造成。",
          "applicable": "考虑或正在接受他汀治疗的成人",
          "exceptions": "出现明显无力、深色尿或肌酸激酶显著升高等情况需及时就医评估",
          "sourceIds": [
            "36049498"
          ]
        },
        {
          "text": "生活方式干预是所有风险层级的基础，但是否加用药物不能只看一次血脂结果；应结合 LDL-C 水平、年龄、既往心血管病、糖尿病、血压、吸烟和家族史等因素。",
          "applicable": "需要进行血脂管理的成人",
          "exceptions": "极高 LDL-C 或明确 ASCVD 时不应以生活方式试验延误必要的药物评估",
          "sourceIds": [
            "31132793"
          ]
        }
      ],
      "limitations": "风险阈值随地区指南而异；未实现个体化风险计算器。"
    },
    {
      "id": "diabetes",
      "name": "糖尿病",
      "number": "03",
      "description": "2 型糖尿病药物选择不只看血糖，还需同时考虑体重、ASCVD、心衰、慢性肾病、低血糖风险和可负担性。",
      "question": "2 型糖尿病药物选择应考虑哪些临床因素？",
      "updatedAt": "2026-08-11",
      "claims": [
        {
          "text": "ADA 2025 标准建议以患者为中心选择降糖药，将血糖目标与体重管理、心血管和肾脏共病、低血糖风险、不良反应、费用及患者偏好一并纳入。",
          "applicable": "成人 2 型糖尿病",
          "exceptions": "1 型糖尿病、妊娠糖尿病和高血糖急症不适用此常规路径",
          "sourceIds": [
            "39651989"
          ]
        },
        {
          "text": "GLP-1 受体激动剂与 SGLT2 抑制剂并非简单的二选一：前者通常更侧重显著减重与动脉粥样硬化性心血管风险，后者在心衰和慢性肾病场景具有重要位置；部分患者可考虑联合。",
          "applicable": "需要升级治疗、尤其合并肥胖或心肾高风险的成人 2 型糖尿病",
          "exceptions": "需结合 eGFR、胃肠道耐受、泌尿生殖道感染风险、费用和具体禁忌证",
          "sourceIds": [
            "39651989"
          ]
        },
        {
          "text": "当存在明显高血糖症状、分解代谢表现或血糖非常高时，应及时评估胰岛素；达到稳定后仍可根据个体情况简化或调整方案。",
          "applicable": "高血糖明显的成人 2 型糖尿病",
          "exceptions": "具体启动阈值和剂量必须由临床人员结合检查结果确定",
          "sourceIds": [
            "39651989"
          ]
        }
      ],
      "limitations": "知识页没有涵盖全部药物、剂量和医保差异。"
    },
    {
      "id": "stroke",
      "name": "卒中二级预防",
      "number": "04",
      "description": "卒中二级预防首先需要明确病因；非心源性缺血性卒中通常以抗血小板治疗为基础，房颤等心源性机制则常需抗凝评估。",
      "question": "缺血性卒中或 TIA 后的二级预防用药有哪些现有证据？",
      "updatedAt": "2026-08-11",
      "claims": [
        {
          "text": "AHA/ASA 指南强调二级预防应按卒中或 TIA 的病因分层，并同时管理血压、血脂、糖尿病、吸烟和生活方式等可干预风险。",
          "applicable": "既往卒中或 TIA 患者的长期二级预防",
          "exceptions": "急性期再灌注、出血性卒中及特殊血管病变需单独处理",
          "sourceIds": [
            "34024117"
          ]
        },
        {
          "text": "阿司匹林或氯吡格雷均可用于部分非心源性缺血性卒中的单药二级预防；选择应考虑既往事件、出血风险、耐受性、相互作用和费用，不能仅凭总体试验结果判定所有患者都优先用同一种。",
          "applicable": "适合抗血小板治疗的非心源性缺血性卒中或 TIA",
          "exceptions": "房颤等心源性卒中通常需要抗凝评估；长期双联抗血小板并不适用于大多数患者",
          "sourceIds": [
            "34024117"
          ]
        },
        {
          "text": "CAPRIE 随机试验在合并近期缺血性卒中、近期心肌梗死或外周动脉病的总体动脉粥样硬化人群中观察到氯吡格雷相对阿司匹林的小幅总体获益；该结果不能直接等同于每一位卒中患者都应首选氯吡格雷。",
          "applicable": "有症状的动脉粥样硬化性血管病人群",
          "exceptions": "并非专门只纳入卒中患者；个体选择仍需结合指南与出血风险",
          "sourceIds": [
            "8918275"
          ]
        }
      ],
      "limitations": "不覆盖卒中急性期治疗，且不应据此自行更换抗血栓药。"
    },
    {
      "id": "lifestyle",
      "name": "生活方式",
      "number": "05",
      "description": "健康饮食是血压、血脂、糖代谢和总体心血管风险管理的共同基础，但不能机械替代必要的药物治疗。",
      "question": "饮食模式和钠摄入与心血管风险有哪些现有证据？",
      "updatedAt": "2026-08-11",
      "claims": [
        {
          "text": "PREDIMED 重新发表的随机试验支持：在心血管高风险但基线无心血管病的成人中，强化地中海饮食相较对照饮食建议可降低主要心血管事件风险。",
          "applicable": "心血管高风险成人的一级预防场景",
          "exceptions": "研究在西班牙完成，饮食实施方式与人群背景会影响外推",
          "sourceIds": [
            "29897866"
          ]
        },
        {
          "text": "CORDIOPREV 随机试验在已确诊冠心病人群中比较地中海饮食与低脂饮食，为地中海饮食用于心血管二级预防提供了长期临床结局证据。",
          "applicable": "已确诊冠心病的成人",
          "exceptions": "单中心研究，且结构化营养随访强度可能高于常规环境",
          "sourceIds": [
            "35525255"
          ]
        },
        {
          "text": "INTERMAP 多国人群研究观察到 24 小时尿钠排泄与血压呈直接关系；限钠通常是高血压生活方式管理的一部分，但个体目标还需结合膳食结构、肾功能和用药。",
          "applicable": "一般成人与高血压风险人群",
          "exceptions": "该证据主要为观察性关联，不能单独证明所有个体的因果效应大小",
          "sourceIds": [
            "29507099"
          ]
        }
      ],
      "limitations": "饮食研究难以完全盲法；个体目标需结合总能量、钾摄入、肾功能与文化饮食习惯。"
    }
  ],
  "sources": {
    "34775787": {
      "id": "34775787",
      "title": "Hypertension Pharmacological Treatment in Adults: A World Health Organization Guideline Executive Summary",
      "journal": "Hypertension",
      "year": 2022,
      "type": "指南",
      "url": "https://pubmed.ncbi.nlm.nih.gov/34775787/",
      "excerpt": "WHO 为非妊娠成人高血压提供药物治疗指导，涵盖启动治疗的血压阈值、治疗目标、随访、单药或双药治疗、单片复方及标准化治疗路径。推荐建立在系统证据综述、获益风险、患者价值、资源与可行性的综合判断上。"
    },
    "34495610": {
      "id": "34495610",
      "title": "WHO Guideline for the pharmacological treatment of hypertension in adults",
      "journal": "",
      "year": null,
      "type": "指南",
      "url": "https://pubmed.ncbi.nlm.nih.gov/34495610/",
      "excerpt": "WHO 指南讨论了单药、双药和单片复方方案；常用起始药物类别包括噻嗪/噻嗪样利尿剂、ACEI/ARB 与长效二氢吡啶类 CCB，具体选择需结合禁忌证、合并症、可及性与患者偏好。"
    },
    "36240838": {
      "id": "36240838",
      "title": "Cardiovascular outcomes with evening versus morning dosing of antihypertensives (TIME study)",
      "journal": "Lancet",
      "year": 2022,
      "type": "随机试验",
      "url": "https://pubmed.ncbi.nlm.nih.gov/36240838/",
      "excerpt": "TIME 是包含 21,104 名成人高血压患者的随机试验。晚间与早晨服用常规降压药在血管死亡或非致死性心肌梗死/卒中复合结局上无显著差异；研究者认为患者可选择方便且不良反应更少的服药时间。"
    },
    "31132793": {
      "id": "31132793",
      "title": "2018 Cholesterol Clinical Practice Guidelines: Synopsis",
      "journal": "Annals of Internal Medicine",
      "year": 2019,
      "type": "指南",
      "url": "https://pubmed.ncbi.nlm.nih.gov/31132793/",
      "excerpt": "AHA/ACC 多学会胆固醇指南概要强调 ASCVD 风险评估、危险增强因素、医患共同决策、生活方式基础干预及按风险选择他汀强度。严重 LDL-C 升高和既往 ASCVD 是药物降脂评估的重要高风险场景。"
    },
    "36049498": {
      "id": "36049498",
      "title": "Effect of statin therapy on muscle symptoms: individual participant data meta-analysis",
      "journal": "Lancet",
      "year": 2022,
      "type": "荟萃分析",
      "url": "https://pubmed.ncbi.nlm.nih.gov/36049498/",
      "excerpt": "对大型随机双盲试验的个体参与者数据分析发现，他汀相较安慰剂仅小幅增加肌痛或无力，主要见于治疗第一年；绝大多数用药期间报告的肌肉症状并非由他汀造成，心血管获益通常大于这一小幅风险。"
    },
    "39651989": {
      "id": "39651989",
      "title": "Pharmacologic Approaches to Glycemic Treatment: Standards of Care in Diabetes—2025",
      "journal": "Diabetes Care",
      "year": 2025,
      "type": "指南",
      "url": "https://pubmed.ncbi.nlm.nih.gov/39651989/",
      "excerpt": "ADA 2025 药物治疗标准提供以患者为中心的 2 型糖尿病方案选择框架，综合血糖和体重目标、ASCVD、心衰、慢性肾病、低血糖风险、不良反应、费用与患者偏好，并讨论 GLP-1 RA、SGLT2i 和胰岛素的适用场景。"
    },
    "34024117": {
      "id": "34024117",
      "title": "2021 Guideline for the Prevention of Stroke in Patients With Stroke and TIA",
      "journal": "Stroke",
      "year": 2021,
      "type": "指南",
      "url": "https://pubmed.ncbi.nlm.nih.gov/34024117/",
      "excerpt": "AHA/ASA 指南覆盖缺血性卒中或 TIA 后的病因分型、抗栓治疗、血压与血脂管理、生活方式及其他风险因素控制。非心源性卒中的抗血小板选择与房颤等心源性卒中的抗凝路径需要区分。"
    },
    "8918275": {
      "id": "8918275",
      "title": "CAPRIE: clopidogrel versus aspirin in patients at risk of ischaemic events",
      "journal": "Lancet",
      "year": 1996,
      "type": "随机试验",
      "url": "https://pubmed.ncbi.nlm.nih.gov/8918275/",
      "excerpt": "CAPRIE 随机双盲试验纳入近期缺血性卒中、近期心肌梗死或有症状外周动脉病患者。氯吡格雷相较阿司匹林对缺血性卒中、心肌梗死或血管性死亡复合结局显示小幅相对获益，但结果来自混合动脉粥样硬化人群。"
    },
    "29897866": {
      "id": "29897866",
      "title": "Primary Prevention of Cardiovascular Disease with a Mediterranean Diet: republication",
      "journal": "New England Journal of Medicine",
      "year": 2018,
      "type": "随机试验",
      "url": "https://pubmed.ncbi.nlm.nih.gov/29897866/",
      "excerpt": "PREDIMED 重新分析并重新发表的随机试验在心血管高风险成人中比较强化地中海饮食与对照饮食建议，为地中海饮食降低主要心血管事件风险提供临床结局证据。"
    },
    "35525255": {
      "id": "35525255",
      "title": "CORDIOPREV: Mediterranean versus low-fat diet for secondary prevention",
      "journal": "Lancet",
      "year": 2022,
      "type": "随机试验",
      "url": "https://pubmed.ncbi.nlm.nih.gov/35525255/",
      "excerpt": "CORDIOPREV 是冠心病患者的长期随机试验，比较地中海饮食与低脂饮食对主要心血管事件的影响，为饮食模式用于心血管二级预防提供直接临床结局证据。"
    },
    "29507099": {
      "id": "29507099",
      "title": "Relation of Dietary Sodium to Blood Pressure: INTERMAP Study",
      "journal": "Hypertension",
      "year": 2018,
      "type": "其他研究",
      "url": "https://pubmed.ncbi.nlm.nih.gov/29507099/",
      "excerpt": "INTERMAP 多国观察研究使用 24 小时尿钠评估摄入，发现钠排泄和钠钾比与血压呈直接关系；这一关联在控制多种营养与非饮食因素后仍存在，但观察性设计不能单独确定个体因果效应。"
    }
  }
};
