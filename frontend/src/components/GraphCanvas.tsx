import cytoscape from "cytoscape";
import { useEffect, useMemo, useRef } from "react";
import type { KnowledgeEdge, KnowledgeNode } from "../lib/api";

type Props = {
  nodes: KnowledgeNode[];
  edges: KnowledgeEdge[];
  query: string;
  selectedNodeId?: string;
  onSelect: (node: KnowledgeNode) => void;
};

const colors = ["#1e40af", "#047857", "#b45309", "#be123c", "#6d28d9", "#0f766e", "#334155"];

export function GraphCanvas({ nodes, edges, query, selectedNodeId, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const nodeMap = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);

  useEffect(() => {
    if (!containerRef.current) {
      return;
    }
    const textbooks = Array.from(new Set(nodes.map((node) => node.textbook_id)));
    const elements: cytoscape.ElementDefinition[] = [
      ...nodes.map((node) => ({
        data: {
          id: node.id,
          label: node.name,
          frequency: node.frequency || 1,
          color: colors[Math.max(textbooks.indexOf(node.textbook_id), 0) % colors.length],
          dimmed: query && !node.name.includes(query) && !node.definition.includes(query)
        }
      })),
      ...edges
        .filter((edge) => nodeMap.has(edge.source) && nodeMap.has(edge.target))
        .map((edge) => ({
          data: {
            id: edge.id,
            source: edge.source,
            target: edge.target,
            label: edge.relation_type
          }
        }))
    ];
    const cy = cytoscape({
      container: containerRef.current,
      elements,
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "background-color": "data(color)",
            color: "#172033",
            "font-size": 11,
            "text-outline-color": "#ffffff",
            "text-outline-width": 2,
            width: "mapData(frequency, 1, 8, 30, 76)",
            height: "mapData(frequency, 1, 8, 30, 76)",
            "border-width": 2,
            "border-color": "#ffffff"
          }
        },
        {
          selector: "node[dimmed]",
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
            label: "data(label)",
            "font-size": 9,
            color: "#64748b"
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
      layout: { name: "cose", animate: false, idealEdgeLength: 120, nodeRepulsion: 7500 }
    });
    cy.on("tap", "node", (event) => {
      const node = nodeMap.get(event.target.id());
      if (node) {
        onSelect(node);
      }
    });
    cyRef.current = cy;
    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [nodes, edges, nodeMap, onSelect, query]);

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
  return <div ref={containerRef} className="graph-canvas" aria-label="知识图谱画布" />;
}
