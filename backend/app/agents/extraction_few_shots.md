示例 1（概念与定义）：

输入片段：
教材章节：第七章 酸碱平衡紊乱
起始页：213
正文：
人体血浆的酸碱度在范围很窄的弱碱性环境内变动，用动脉血 pH 表示是 7.35 ~ 7.45，平均值为 7.40。机体自动调节酸碱物质的含量和比例，以维持体液 pH 相对稳定的过程称为酸碱平衡。

期望 JSON：
{
  "nodes": [
    {
      "name": "酸碱平衡",
      "definition": "机体自动调节酸碱物质的含量和比例，以维持体液 pH 相对稳定的过程。",
      "category": "核心概念",
      "page": 213,
      "source_excerpt": "机体自动调节酸碱物质的含量和比例，以维持体液 pH 相对稳定的过程称为酸碱平衡。"
    },
    {
      "name": "体液 pH",
      "definition": "反映体液酸碱度的指标，正常动脉血 pH 范围约为 7.35 ~ 7.45。",
      "category": "相关概念",
      "page": 213,
      "source_excerpt": "人体血浆的酸碱度在范围很窄的弱碱性环境内变动，用动脉血 pH 表示是 7.35 ~ 7.45。"
    }
  ],
  "edges": [
    {
      "source_name": "体液 pH",
      "target_name": "酸碱平衡",
      "relation_type": "prerequisite",
      "description": "理解酸碱平衡需要先理解体液 pH 这一指标。"
    }
  ]
}

示例 2（关系抽取）：

输入片段：
教材章节：第三节 传染病的流行过程及影响因素
起始页：81
正文：
传染病的流行过程就是传染病在人群中发生、发展和转归的过程。流行过程的发生需要三个基本条件，包括传染源、传播途径和人群易感性。这三个环节必须同时存在，若切断任何一个环节，流行即告终止。

期望 JSON：
{
  "nodes": [
    {
      "name": "传染病流行过程",
      "definition": "传染病在人群中发生、发展和转归的过程。",
      "category": "核心概念",
      "page": 81,
      "source_excerpt": "传染病的流行过程就是传染病在人群中发生、发展和转归的过程。"
    },
    {
      "name": "传染源",
      "definition": "流行过程发生的基本条件之一。",
      "category": "相关概念",
      "page": 81,
      "source_excerpt": "流行过程的发生需要三个基本条件，包括传染源、传播途径和人群易感性。"
    },
    {
      "name": "传播途径",
      "definition": "流行过程发生的基本条件之一。",
      "category": "相关概念",
      "page": 81,
      "source_excerpt": "流行过程的发生需要三个基本条件，包括传染源、传播途径和人群易感性。"
    },
    {
      "name": "人群易感性",
      "definition": "流行过程发生的基本条件之一。",
      "category": "相关概念",
      "page": 81,
      "source_excerpt": "流行过程的发生需要三个基本条件，包括传染源、传播途径和人群易感性。"
    }
  ],
  "edges": [
    {
      "source_name": "传染病流行过程",
      "target_name": "传染源",
      "relation_type": "contains",
      "description": "传染源是传染病流行过程成立的基本环节之一。"
    },
    {
      "source_name": "传染病流行过程",
      "target_name": "传播途径",
      "relation_type": "contains",
      "description": "传播途径是传染病流行过程成立的基本环节之一。"
    },
    {
      "source_name": "传染病流行过程",
      "target_name": "人群易感性",
      "relation_type": "contains",
      "description": "人群易感性是传染病流行过程成立的基本环节之一。"
    }
  ]
}
