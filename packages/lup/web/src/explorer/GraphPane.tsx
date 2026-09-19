// The log as a graph: every shown node, every edge between them, laid out by
// force, a tap opening the node. Cytoscape owns the canvas; React owns the
// container and hands the elements over whenever the graph it holds changes.
import { useEffect, useRef } from "react";
import { useNavigate } from "@tanstack/react-router";
import cytoscape from "cytoscape";
import type { GraphView } from "../generated/views";
import { grouped } from "./narrow";

/**
 * The graph as cytoscape draws it. A grouping edge kind nests each source
 * inside its target as a compound node — messages inside their thread — and
 * is not drawn as a line, since the nesting already shows it.
 */
export function elements(graph: GraphView, group: string): cytoscape.ElementDefinition[] {
  const parents = grouped(graph, group);
  return [
    ...graph.nodes.map((node) => {
      const parent = parents.get(node.id);
      return {
        data: {
          id: node.id,
          label: node.slug !== "" ? node.slug : node.title,
          kind: node.kind,
          standing: node.standing,
          sound: node.sound ? "yes" : "no",
          ...(parent !== undefined ? { parent } : {}),
        },
      };
    }),
    ...graph.edges
      .filter((edge) => !(edge.kind === group && parents.get(edge.source) === edge.target))
      .map((edge) => ({
        data: {
          id: `${edge.source}->${edge.target}:${edge.kind}`,
          source: edge.source,
          target: edge.target,
          kind: edge.kind,
        },
      })),
  ];
}

export function GraphPane({ graph, group = "" }: { graph: GraphView; group?: string }) {
  const container = useRef<HTMLDivElement | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (container.current === null) return;
    const cy = cytoscape({
      container: container.current,
      elements: elements(graph, group),
      style: [
        {
          selector: ":parent",
          style: {
            "background-opacity": 0.08,
            "border-width": 1,
            "border-color": "#a0aec0",
            "text-valign": "top",
            "text-halign": "center",
            "font-size": "11px",
            padding: "12px",
          },
        },
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
  }, [graph, group, navigate]);

  return <div ref={container} className="graph" />;
}
