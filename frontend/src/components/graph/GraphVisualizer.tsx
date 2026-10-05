"use client";

import dynamic from "next/dynamic";
import { useEffect, useState, useRef } from "react";
import { useTheme } from "next-themes";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Maximize2, Minimize2, ZoomIn, ZoomOut, RefreshCcw, X } from "lucide-react";

// Dynamically import ForceGraph2D with no SSR as it relies on window/canvas
const ForceGraph2D = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
});

/* Node kinds map to ecosystem roles, read from the CSS custom properties at
   paint time because the canvas cannot use utility classes. */
const NODE_COLOR_VAR: Record<string, string> = {
  Deputy: "--brand",
  Deputato: "--brand",
  GovernmentMember: "--brand-700",
  MembroGoverno: "--brand-700",
  ParliamentaryGroup: "--accent-violet",
  GruppoParlamentare: "--accent-violet",
  Committee: "--notice",
  Commissione: "--notice",
  ParliamentaryAct: "--accent-coral",
  AttoParlamentare: "--accent-coral",
  Speech: "--brand-300",
  Intervento: "--brand-300",
  Session: "--fg-secondary",
  Seduta: "--fg-secondary",
  Debate: "--vote-against",
  Dibattito: "--vote-against",
  Phase: "--vote-abstain",
  Fase: "--vote-abstain",
  Chunk: "--fg-muted",
};
const PAINT_VARS = ["--stage", "--line-control", "--fg", "--fg-faint", ...new Set(Object.values(NODE_COLOR_VAR))];

interface GraphVisualizerProps {
  data: any[];
}

export function GraphVisualizer({ data }: GraphVisualizerProps) {
  const [graphData, setGraphData] = useState<{ nodes: any[]; links: any[] }>({
    nodes: [],
    links: [],
  });
  const fgRef = useRef<any>(null);
  const { resolvedTheme } = useTheme();
  const [paint, setPaint] = useState<Record<string, string>>({});
  useEffect(() => {
    const cs = getComputedStyle(document.documentElement);
    setPaint(Object.fromEntries(PAINT_VARS.map((v) => [v, cs.getPropertyValue(v).trim()])));
  }, [resolvedTheme]);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [selectedNode, setSelectedNode] = useState<any>(null);

  useEffect(() => {
    if (!data || !Array.isArray(data) || data.length === 0) {
        setGraphData({ nodes: [], links: [] });
        return;
    }
    
    // Transform Cypher result array into nodes/links
    // We handle:
    // 1. Nodes returned directly (e.g. RETURN n)
    // 2. Relationships returned directly (e.g. RETURN r)
    // 3. Paths (not handled in simple implementation without metadata)
    // 4. Manual parsing of dicts

    const nodes = new Map();
    const links = new Map();

    const processItem = (item: any) => {
        if (!item) return;

        if (typeof item === 'object') {
            // If it has 'start', 'end', 'type' -> likely a relationship
            if ('start' in item && 'end' in item && 'type' in item) {
                 const linkId = item.id || `${item.start}-${item.type}-${item.end}`;
                 if (!links.has(linkId)) {
                     links.set(linkId, {
                        id: linkId,
                        source: item.start,
                        target: item.end,
                        type: item.type,
                        ...item
                     });
                 }
                if (!nodes.has(item.start)) nodes.set(item.start, { id: item.start, label: "Unknown", caption: "?", color: "--fg-faint", properties: {} });
                if (!nodes.has(item.end)) nodes.set(item.end, { id: item.end, label: "Unknown", caption: "?", color: "--fg-faint", properties: {} });
                 return;
            }

            // Neo4j node structure: { id, labels, properties }
            const id = item.id || item.elementId;
            if (id !== undefined) {
                if (!nodes.has(id)) {
                    // Get label from labels array
                    let label = "Node";
                    if (item.labels && Array.isArray(item.labels) && item.labels.length > 0) {
                        label = item.labels[0];
                    }

                    // Properties are nested in item.properties
                    const props = item.properties || item;

                    // Build caption based on node label type
                    let caption = "";
                    const firstName = props.first_name || props.nome;
                    const lastName = props.last_name || props.cognome;
                    const title = props.title || props.titolo;
                    const name = props.name;
                    const text = props.text || props.testo;
                    const number = props.number || props.numero;
                    const date = props.date || props.data;

                    // Label-specific caption logic
                    switch (label) {
                        case "Deputy":
                        case "Deputato":
                        case "GovernmentMember":
                        case "MembroGoverno":
                            caption = firstName && lastName ? `${firstName} ${lastName}` : firstName || lastName || "?";
                            break;
                        case "Session":
                        case "Seduta":
                            caption = number ? `Seduta ${number}` : (date ? `${date}` : "Session");
                            break;
                        case "Debate":
                        case "Dibattito":
                            caption = title ? (title.length > 30 ? title.substring(0, 30) + "..." : title) : "Debate";
                            break;
                        case "Phase":
                        case "Fase":
                            caption = title ? (title.length > 25 ? title.substring(0, 25) + "..." : title) : "Phase";
                            break;
                        case "Speech":
                        case "Intervento":
                            caption = text ? (text.length > 25 ? text.substring(0, 25) + "..." : text) : "Speech";
                            break;
                        case "Chunk":
                            caption = text ? (text.length > 20 ? text.substring(0, 20) + "..." : text) : "Chunk";
                            break;
                        case "ParliamentaryGroup":
                        case "GruppoParlamentare":
                            caption = name || props.acronym || props.sigla || "Group";
                            break;
                        case "Committee":
                        case "Commissione":
                            caption = name ? (name.length > 25 ? name.substring(0, 25) + "..." : name) : "Committee";
                            break;
                        case "ParliamentaryAct":
                        case "AttoParlamentare":
                            caption = title ? (title.length > 30 ? title.substring(0, 30) + "..." : title) : "Act";
                            break;
                        default:
                            // Generic fallback
                            if (firstName && lastName) caption = `${firstName} ${lastName}`;
                            else if (name) caption = name;
                            else if (title) caption = title.length > 25 ? title.substring(0, 25) + "..." : title;
                            else caption = String(id).split('/').pop()?.substring(0, 12) || "Node";
                    }

                    nodes.set(id, {
                        id: id,
                        label: label,
                        caption: caption,
                        val: 1,
                        color: getNodeColor(label),
                        properties: props
                    });
                }
            }
        }
    }

    data.forEach(row => {
        Object.values(row).forEach(val => {
             if (Array.isArray(val)) {
                 val.forEach(processItem);
             } else {
                 processItem(val);
             }
        });
    });
    
    setGraphData({
        nodes: Array.from(nodes.values()),
        links: Array.from(links.values())
    });

  }, [data]);

    const getNodeColor = (label: string) => NODE_COLOR_VAR[label] ?? "--fg-faint";

    const handleZoomIn = () => {
        fgRef.current?.zoom(fgRef.current.zoom() * 1.2, 400);
    };

    const handleZoomOut = () => {
        fgRef.current?.zoom(fgRef.current.zoom() / 1.2, 400);
    };
    
    const handleFitView = () => {
        fgRef.current?.zoomToFit(400, 20);
    };

    const handleNodeClick = (node: any) => {
      setSelectedNode(node);
      // Optional: Zoom to node
      // fgRef.current?.centerAt(node.x, node.y, 1000);
      // fgRef.current?.zoom(4, 1000);
    };

    const handleBackgroundClick = () => {
      setSelectedNode(null);
    };

  return (
    <Card className={`relative flex flex-col overflow-hidden ${isFullscreen ? "fixed inset-0 z-50 rounded-none w-screen h-screen" : "w-full h-full"}`}>
                <div className="absolute top-2 right-2 z-10 flex gap-1 rounded-full border border-line bg-surface/90 p-1 backdrop-blur-sm">
             <Button size="icon" variant="ghost" className="h-8 w-8" onClick={handleFitView} title="Fit View" aria-label="Fit View">
                <RefreshCcw className="h-4 w-4" />
            </Button>
            <Button size="icon" variant="ghost" className="h-8 w-8" onClick={handleZoomIn} title="Zoom In">
                <ZoomIn className="h-4 w-4" />
            </Button>
            <Button size="icon" variant="ghost" className="h-8 w-8" onClick={handleZoomOut} title="Zoom Out">
                <ZoomOut className="h-4 w-4" />
            </Button>
            <Button size="icon" variant="ghost" className="h-8 w-8" onClick={() => setIsFullscreen(!isFullscreen)} title="Fullscreen">
                {isFullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
            </Button>
        </div>

      <div className="flex-1 w-full h-full bg-stage relative">
          <ForceGraph2D
            ref={fgRef}
            width={isFullscreen ? window.innerWidth : undefined}
            graphData={graphData}
            nodeLabel="caption"
            nodeRelSize={6}
            linkColor={() => paint["--line-control"] || "gray"}
            linkDirectionalArrowLength={3.5}
            linkDirectionalArrowRelPos={1}
            linkLabel="type"

            // Custom node rendering with label
            nodeCanvasObject={(node: any, ctx, globalScale) => {
                const label = node.caption || '';
                const fontSize = 12 / globalScale;
                const nodeR = 6;

                // Draw node circle
                ctx.beginPath();
                ctx.arc(node.x, node.y, nodeR, 0, 2 * Math.PI);
                ctx.fillStyle = paint[node.color] || paint["--fg-faint"] || "gray";
                ctx.fill();

                // Draw border
                ctx.strokeStyle = paint["--stage"] || "white";
                ctx.lineWidth = 1 / globalScale;
                ctx.stroke();

                // Draw label below node
                if (globalScale > 0.5) {
                    ctx.font = `${fontSize}px Sans-Serif`;
                    ctx.textAlign = 'center';
                    ctx.textBaseline = 'top';
                    ctx.fillStyle = paint["--fg"] || "black";
                    ctx.fillText(label, node.x, node.y + nodeR + 2);
                }
            }}
            nodePointerAreaPaint={(node: any, color, ctx) => {
                ctx.beginPath();
                ctx.arc(node.x, node.y, 8, 0, 2 * Math.PI);
                ctx.fillStyle = color;
                ctx.fill();
            }}

            // Interaction
            cooldownTicks={100}
            onNodeClick={handleNodeClick}
            onBackgroundClick={handleBackgroundClick}
          />
          
          {/* Selected Node Details Panel */}
          {selectedNode && (
            <div className={`absolute top-0 left-0 h-full w-[300px] bg-bg/95 backdrop-blur-sm border-r border-line p-4 overflow-auto transition-transform duration-300 ${selectedNode ? 'translate-x-0' : '-translate-x-full'}`}>
                <div className="flex justify-between items-start mb-4">
                     <h3 className="text-lg font-semibold text-fg truncate flex-1" title={selectedNode.caption}>
                        {selectedNode.caption || "Node Details"}
                     </h3>
                     <Button variant="ghost" size="icon" className="h-8 w-8 -mr-2" onClick={() => setSelectedNode(null)} aria-label="Close">
                        <X className="h-4 w-4" />
                     </Button>
                </div>
                
                <div className="space-y-4 text-sm">
                    <div className="flex flex-col gap-1">
                        <div className="flex items-center gap-2">
                             <span className="bg-brand-soft text-brand-fg px-2 py-0.5 rounded-sm text-xs font-semibold">
                                {selectedNode.label}
                            </span>
                             <span className="text-xs text-fg-muted">ID</span>
                        </div>
                        <div className="font-mono text-xs bg-surface-muted p-1.5 rounded-sm break-all">
                            {selectedNode.id}
                        </div>
                    </div>

                    <div className="space-y-2">
                        <h4 className="label-mono">Properties</h4>
                        <div className="bg-surface-muted rounded-md p-2 space-y-3">
                            {Object.entries(selectedNode.properties || {}).map(([key, val]) => {
                                if (key === 'labels' || key === 'id' || key === 'elementId' || key === 'properties') return null;
                                const displayVal = typeof val === 'object' ? JSON.stringify(val, null, 2) : String(val ?? '');
                                if (!displayVal) return null;
                                return (
                                    <div key={key} className="flex flex-col gap-1 text-xs border-b last:border-0 border-line pb-2 last:pb-0">
                                        <span className="font-medium text-fg-muted">{key}</span>
                                        <div className="font-mono bg-surface p-1.5 rounded-sm text-fg-secondary break-all whitespace-pre-wrap max-h-[200px] overflow-auto">
                                            {displayVal}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                </div>
            </div>
          )}
      </div>
      
      {!graphData.nodes.length && (
           <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
               <span className="text-fg-muted bg-bg/80 px-3 py-1 rounded-sm">No graph data to visualize from this query</span>
           </div>
      )}
      
      {graphData.nodes.length > 0 && (
          <div className="tabular absolute bottom-2 left-2 z-10 font-mono text-caption text-fg-muted bg-bg/80 px-2 py-1 rounded-sm select-none">
              Nodes: {graphData.nodes.length} | Links: {graphData.links.length}
          </div>
      )}
    </Card>
  );
}
