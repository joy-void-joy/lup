// The log as a graph: every shown node, every edge between them, laid out by
// force, a tap opening the node. Cytoscape owns the canvas; React owns the
// container and hands the elements over whenever the graph it holds changes.
import { useEffect, useRef } from "react";
import { useNavigate } from "@tanstack/react-router";
import cytoscape from "cytoscape";
import type { GraphView } from "../generated/views";

function elements(graph: GraphView): cytoscape.ElementDefinition[] {
  return [
    ...graph.nodes.map((node) => ({
      data: {
        id: node.id,
        label: node.slug !== "" ? node.slug : node.title,
        kind: node.kind,
        standing: node.standing,
        sound: node.sound ? "yes" : "no",
      },
    })),
    ...graph.edges.map((edge) => ({
      data: {
        id: `${edge.source}->${edge.target}:${edge.kind}`,
        source: edge.source,
        target: edge.target,
        kind: edge.kind,
      },
    })),
  ];
}

export function GraphPane({ graph }: { graph: GraphView }) {
  const container = useRef<HTMLDivElement | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (container.current === null) return;
    const cy = cytoscape({
      container: container.current,
      elements: elements(graph),
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "font-size": "10px",
            "text-valign": "bottom",
            "text-margin-y": 4,
            "background-color": "#2b6cb0",
            width: 18,
            height: 18,
          },
        },
        { selector: "node[sound = 'no']", style: { "background-color": "#c53030" } },
        {
          selector: "edge",
          style: {
            label: "data(kind)",
            "font-size": "8px",
            "curve-style": "bezier",
            "target-arrow-shape": "triangle",
            "line-color": "#a0aec0",
            "target-arrow-color": "#a0aec0",
            width: 1.5,
          },
        },
      ],
      layout: { name: "cose", animate: false },
    });
    cy.on("tap", "node", (event) => {
      void navigate({ to: "/node/$id", params: { id: String(event.target.id()) } });
    });
    return () => {
      cy.destroy();
    };
  }, [graph, navigate]);

  return <div ref={container} className="graph" />;
}
