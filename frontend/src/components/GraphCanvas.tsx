import cytoscape from "cytoscape";
import { useEffect, useMemo, useRef } from "react";
import type { KnowledgeEdge, KnowledgeNode } from "../lib/api";

type Props = {
  nodes: KnowledgeNode[];
  edges: KnowledgeEdge[];
  query: string;
  layoutMode: GraphLayoutMode;
  rootLabel: string;
  selectedNodeId?: string;
  onSelect: (node: KnowledgeNode) => void;
};

export type GraphLayoutMode = "chapter-map" | "force";

const sourceBorderColors = ["#1e40af", "#047857", "#b45309", "#be123c", "#6d28d9", "#0f766e", "#334155"];
const relationColors: Record<string, string> = {
  prerequisite: "#dc2626",
  parallel: "#64748b",
  contains: "#2563eb",
  applies_to: "#059669"
};

export function GraphCanvas({ nodes, edges, query, layoutMode, rootLabel, selectedNodeId, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const onSelectRef = useRef(onSelect);
  const nodeMap = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);
  const textbookIds = useMemo(() => Array.from(new Set(nodes.map((node) => node.textbook_id))), [nodes]);
  const maxFrequency = useMemo(() => Math.max(1, ...nodes.map((node) => node.frequency || 1)), [nodes]);
  const sourceLegends = useMemo(() => buildSourceLegends(nodes, textbookIds), [nodes, textbookIds]);

  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  useEffect(() => {
    if (!containerRef.current) {
      return;
    }
    const elements =
      layoutMode === "chapter-map"
        ? buildChapterMapElements(nodes, edges, nodeMap, textbookIds, maxFrequency, query, rootLabel)
        : buildForceElements(nodes, edges, nodeMap, textbookIds, maxFrequency, query);
    const cy = cytoscape({
      container: containerRef.current,
      elements,
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            color: "#172033",
            "font-size": 11,
            "text-outline-color": "#ffffff",
            "text-outline-width": 2,
            "text-wrap": "wrap",
            "text-max-width": "120px",
            "border-width": 2,
            "border-color": "#ffffff"
          }
        },
        {
          selector: ".knowledge-node",
          style: {
            "background-color": "data(fillColor)",
            "border-color": "data(sourceColor)",
            width: "data(size)",
            height: "data(size)"
          }
        },
        {
          selector: ".root-node",
          style: {
            "background-color": "#102a56",
            color: "#ffffff",
            "text-outline-color": "#102a56",
            shape: "round-rectangle",
            width: 150,
            height: 58,
            "font-size": 13
          }
        },
        {
          selector: ".chapter-node",
          style: {
            "background-color": "#e0f2fe",
            "border-color": "#0284c7",
            shape: "round-rectangle",
            width: 150,
            height: 46,
            "font-size": 11
          }
        },
        {
          selector: ".dimmed",
          style: { opacity: 0.18 }
        },
        {
          selector: "edge",
          style: {
            width: 1.4,
            "line-color": "#93a4b8",
            "target-arrow-color": "#93a4b8",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            "font-size": 9,
            color: "#64748b"
          }
        },
        {
          selector: ".tree-edge",
          style: {
            width: 1.2,
            "line-color": "#cbd5e1",
            "target-arrow-shape": "none",
            "curve-style": "straight"
          }
        },
        {
          selector: ".concept-edge",
          style: {
            label: "data(label)",
            "line-color": "data(color)",
            "target-arrow-color": "data(color)",
            "line-style": "solid",
            opacity: 0.72
          }
        },
        {
          selector: ".selected",
          style: {
            "border-color": "#f59e0b",
            "border-width": 5
          }
        }
      ],
      layout:
        layoutMode === "chapter-map"
          ? { name: "preset", animate: false, fit: true, padding: 48 }
          : { name: "cose", animate: false, idealEdgeLength: 120, nodeRepulsion: 7500 }
    });
    cy.on("tap", "node", (event) => {
      const node = nodeMap.get(event.target.id());
      if (node) {
        onSelectRef.current(node);
      }
    });
    cy.ready(() => cy.fit(undefined, 48));
    cyRef.current = cy;
    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [nodes, edges, nodeMap, query, layoutMode, rootLabel, textbookIds, maxFrequency]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) {
      return;
    }
    cy.nodes().removeClass("selected");
    if (selectedNodeId) {
      cy.getElementById(selectedNodeId).addClass("selected");
    }
  }, [selectedNodeId]);

  if (nodes.length === 0) {
    return <div className="empty-state">上传教材并构建图谱后，这里会显示可交互知识网络。</div>;
  }
  return (
    <div className="graph-frame">
      <div ref={containerRef} className="graph-canvas" aria-label="知识图谱画布" />
      <GraphLegend sourceLegends={sourceLegends} />
    </div>
  );
}

function buildForceElements(
  nodes: KnowledgeNode[],
  edges: KnowledgeEdge[],
  nodeMap: Map<string, KnowledgeNode>,
  textbookIds: string[],
  maxFrequency: number,
  query: string
): cytoscape.ElementDefinition[] {
  return [
    ...nodes.map((node) => ({
      data: knowledgeNodeData(node, textbookIds, maxFrequency),
      classes: classNames("knowledge-node", isDimmed(node, query) && "dimmed")
    })),
    ...edges
      .filter((edge) => nodeMap.has(edge.source) && nodeMap.has(edge.target))
      .map((edge) => conceptEdgeElement(edge))
  ];
}

function buildChapterMapElements(
  nodes: KnowledgeNode[],
  edges: KnowledgeEdge[],
  nodeMap: Map<string, KnowledgeNode>,
  textbookIds: string[],
  maxFrequency: number,
  query: string,
  rootLabel: string
): cytoscape.ElementDefinition[] {
  const groups = groupByChapter(nodes);
  const positionedGroups = positionChapterGroups(groups);
  const elements: cytoscape.ElementDefinition[] = [
    {
      data: { id: "view-root", label: compactLabel(rootLabel.replace(/^单本图谱：/, ""), 34) },
      position: { x: 0, y: 0 },
      classes: "root-node"
    }
  ];

  for (const group of positionedGroups) {
    const chapterId = `view-chapter-${group.id}`;
    elements.push({
      data: { id: chapterId, label: compactLabel(group.title, 24) },
      position: { x: group.x, y: group.y },
      classes: "chapter-node"
    });
    elements.push({
      data: { id: `tree-root-${group.id}`, source: "view-root", target: chapterId },
      classes: "tree-edge"
    });
    group.nodes.forEach((node, index) => {
      const rowCount = Math.min(4, group.nodes.length);
      const row = index % rowCount;
      const column = Math.floor(index / rowCount);
      elements.push({
        data: knowledgeNodeData(node, textbookIds, maxFrequency),
        position: {
          x: group.x + group.side * (220 + column * 150),
          y: group.y + (row - (rowCount - 1) / 2) * 58
        },
        classes: classNames("knowledge-node", isDimmed(node, query) && "dimmed")
      });
      elements.push({
        data: { id: `tree-${group.id}-${node.id}`, source: chapterId, target: node.id },
        classes: "tree-edge"
      });
    });
  }

  elements.push(...edges.filter((edge) => nodeMap.has(edge.source) && nodeMap.has(edge.target)).map((edge) => conceptEdgeElement(edge)));
  return elements;
}

function knowledgeNodeData(node: KnowledgeNode, textbookIds: string[], maxFrequency: number) {
  const frequency = node.frequency || 1;
  const sourceIndex = Math.max(textbookIds.indexOf(node.textbook_id), 0);
  return {
    id: node.id,
    label: compactLabel(node.name, 18),
    frequency,
    fillColor: frequencyFillColor(frequency, maxFrequency),
    sourceColor: sourceBorderColors[sourceIndex % sourceBorderColors.length],
    size: frequencySize(frequency, maxFrequency)
  };
}

function conceptEdgeElement(edge: KnowledgeEdge): cytoscape.ElementDefinition {
  return {
    data: {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: relationLabel(edge.relation_type),
      color: relationColors[edge.relation_type] || "#64748b"
    },
    classes: "concept-edge"
  };
}

function groupByChapter(nodes: KnowledgeNode[]) {
  const groups = new Map<string, { id: string; title: string; position: number; nodes: KnowledgeNode[] }>();
  for (const node of nodes) {
    const id = node.chapter_id || "unknown";
    const existing = groups.get(id);
    if (existing) {
      existing.nodes.push(node);
      continue;
    }
    groups.set(id, {
      id,
      title: node.chapter_title || "未识别章节",
      position: node.chapter_position ?? Number.MAX_SAFE_INTEGER,
      nodes: [node]
    });
  }
  return Array.from(groups.values()).sort((left, right) => left.position - right.position || left.title.localeCompare(right.title, "zh-Hans-CN"));
}

function positionChapterGroups(groups: Array<{ id: string; title: string; position: number; nodes: KnowledgeNode[] }>) {
  const right = groups.filter((_, index) => index % 2 === 0);
  const left = groups.filter((_, index) => index % 2 === 1);
  return [...positionSide(right, 1), ...positionSide(left, -1)];
}

function positionSide(groups: Array<{ id: string; title: string; position: number; nodes: KnowledgeNode[] }>, side: 1 | -1) {
  const heights = groups.map((group) => Math.max(150, Math.ceil(group.nodes.length / 2) * 72));
  const totalHeight = heights.reduce((sum, height) => sum + height + 34, 0) - 34;
  let cursor = -totalHeight / 2;
  return groups.map((group, index) => {
    const height = heights[index];
    const y = cursor + height / 2;
    cursor += height + 34;
    return { ...group, side, x: side * 210, y };
  });
}

function relationLabel(relationType: string) {
  return {
    prerequisite: "前置",
    parallel: "并列",
    contains: "包含",
    applies_to: "应用"
  }[relationType] || relationType;
}

function isDimmed(node: KnowledgeNode, query: string) {
  return Boolean(query.trim()) && !node.name.includes(query) && !node.definition.includes(query);
}

function compactLabel(label: string, maxLength: number) {
  return label.length > maxLength ? `${label.slice(0, maxLength - 1)}…` : label;
}

function classNames(...items: Array<string | false>) {
  return items.filter(Boolean).join(" ");
}

function frequencySize(frequency: number, maxFrequency: number) {
  if (maxFrequency <= 1) {
    return 34;
  }
  const ratio = (frequency - 1) / (maxFrequency - 1);
  return Math.round(34 + ratio * 42);
}

function frequencyFillColor(frequency: number, maxFrequency: number) {
  if (maxFrequency <= 1) {
    return "#bfdbfe";
  }
  const ratio = Math.max(0, Math.min(1, (frequency - 1) / (maxFrequency - 1)));
  const start = [191, 219, 254];
  const end = [30, 64, 175];
  const channel = (index: number) => Math.round(start[index] + (end[index] - start[index]) * ratio);
  return `rgb(${channel(0)}, ${channel(1)}, ${channel(2)})`;
}

function buildSourceLegends(nodes: KnowledgeNode[], textbookIds: string[]) {
  return textbookIds.slice(0, 7).map((textbookId, index) => {
    const node = nodes.find((item) => item.textbook_id === textbookId);
    return {
      id: textbookId,
      title: compactLabel(node?.textbook_title || textbookId, 18),
      color: sourceBorderColors[index % sourceBorderColors.length]
    };
  });
}

function GraphLegend({ sourceLegends }: { sourceLegends: Array<{ id: string; title: string; color: string }> }) {
  return (
    <aside className="graph-legend" aria-label="图谱图例">
      <div className="legend-row">
        <span className="legend-frequency light" />
        <span className="legend-frequency dark" />
        <span>频次：浅→深 / 小→大</span>
      </div>
      {sourceLegends.length > 0 && (
        <div className="legend-sources">
          <span>来源边框</span>
          {sourceLegends.map((source) => (
            <span key={source.id} className="legend-source">
              <i style={{ borderColor: source.color }} />
              {source.title}
            </span>
          ))}
        </div>
      )}
    </aside>
  );
}
