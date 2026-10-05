"use client";

import React, { useState, useRef, useCallback, useEffect } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Plus, Minus, Info, RotateCcw } from "lucide-react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { useTranslations } from "next-intl";

export interface CompassData {
    meta: {
        query: string;
        explained_variance_ratio: number[];
        total_variance_explained?: number;
        dimensionality?: number;
        // "stance" (LLM stance scores on anchored poles) | "semantic"
        // (embedding projection on anchored poles) | "pca"
        axis_method?: string;
        is_stable: boolean;
        warnings?: string[];
    };
    axes: {
        x: AxisDef;
        y: AxisDef;
    };
    groups: Array<{
        group_id: string;
        position_x: number;
        position_y: number;
        dispersion: {
            center_x: number;
            center_y: number;
            radius_x: number;
            radius_y: number;
            rotation: number;
        };
        stats: Record<string, number>;
        core_evidence_ids: string[];
    }>;
    scatter_sample: Array<{
        x: number;
        y: number;
        group_id: string;
        text: string;
    }>;
}

interface AxisDef {
    index: number; 
    positive_pole_fragments: string[]; 
    negative_pole_fragments: string[];
    label?: string;
    description?: string;
    positive_side?: { 
        label: string; 
        explanation: string;
        keywords?: string[];
        fragments?: Array<{ text_preview: string }>;
    };
    negative_side?: { 
        label: string; 
        explanation: string;
        keywords?: string[];
        fragments?: Array<{ text_preview: string }>;
    };
}

interface CompassCardProps {
    data: CompassData;
    /** Stretch to fill the parent height (full-page usage) instead of the fixed card height. */
    fill?: boolean;
}

export function CompassCard({ data, fill = false }: CompassCardProps) {
  const t = useTranslations("CompassCard");
  const [zoom, setZoom] = useState(1);
  // Highlight all scatter points of the hovered group
  const [hoveredGroup, setHoveredGroup] = useState<string | null>(null);
  // Pan offset in percentage points (0,0 = centered)
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const dragRef = useRef<{ dragging: boolean; startX: number; startY: number; startPanX: number; startPanY: number } | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  if (!data?.meta || !data?.groups) return null;
  const dimensionality = data.meta.dimensionality ?? 2;
  const isStance = data.meta.axis_method === "stance";
  // Stance mode: the metric is coverage (share of interventions taking a
  // position), not variance: the two axis ratios overlap, so use the total.
  const signalPct = isStance
      ? Math.round((data.meta.total_variance_explained || 0) * 100)
      : Math.round(((data.meta.explained_variance_ratio?.[0] || 0) + (dimensionality === 2 ? (data.meta.explained_variance_ratio?.[1] || 0) : 0)) * 100);
  const lowStance = isStance && (data.meta.warnings || []).some(w => w.startsWith("LOW_STANCE_COVERAGE"));

  const resetView = () => { setZoom(1); setPan({ x: 0, y: 0 }); };

  // Drag handlers
  const onPointerDown = useCallback((e: React.PointerEvent) => {
    if ((e.target as HTMLElement).closest('button')) return;
    const el = containerRef.current;
    if (!el) return;
    el.setPointerCapture(e.pointerId);
    dragRef.current = { dragging: true, startX: e.clientX, startY: e.clientY, startPanX: pan.x, startPanY: pan.y };
  }, [pan]);

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    const d = dragRef.current;
    if (!d?.dragging) return;
    const el = containerRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    // Convert pixel delta to percentage of container
    const dx = ((e.clientX - d.startX) / rect.width) * 100;
    const dy = ((e.clientY - d.startY) / rect.height) * 100;
    setPan({ x: d.startPanX + dx, y: d.startPanY + dy });
  }, []);

  const onPointerUp = useCallback(() => {
    if (dragRef.current) dragRef.current.dragging = false;
  }, []);

  // Wheel zoom – registered with { passive: false } to allow preventDefault
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const handler = (e: WheelEvent) => {
      e.preventDefault();
      setZoom(z => {
        const delta = e.deltaY > 0 ? -0.15 : 0.15;
        return Math.min(6, Math.max(0.2, z + delta));
      });
    };
    el.addEventListener("wheel", handler, { passive: false });
    return () => el.removeEventListener("wheel", handler);
  }, []);

  // Group colors and abbreviations map
  const groupConfig: Record<string, { color: string; abbrev: string }> = {
      "FRATELLI D'ITALIA": { color: "#0066CC", abbrev: "FdI" },
      "PARTITO DEMOCRATICO": { color: "#E30613", abbrev: "PD" },
      "LEGA": { color: "#008C45", abbrev: "Lega" },
      "MOVIMENTO 5 STELLE": { color: "#FFCC00", abbrev: "M5S" },
      "FORZA ITALIA": { color: "#00AEEF", abbrev: "FI" },
      "AZIONE": { color: "#F5821F", abbrev: "Az" },
      "ITALIA VIVA": { color: "#EB008B", abbrev: "IV" },
      "ALLEANZA VERDI": { color: "#4CAF50", abbrev: "AVS" },
      "NOI MODERATI": { color: "#1E3A5F", abbrev: "NM" },
      "MISTO": { color: "#808080", abbrev: "Misto" },
      "GOVERNO": { color: "#4B0082", abbrev: "Gov" }
  };

  const getGroupColor = (groupId: string) => {
       const upperGroupId = groupId.toUpperCase();
       for (const [key, config] of Object.entries(groupConfig)) {
           if (upperGroupId.includes(key.toUpperCase())) return config.color;
       }
       return "#808080";
  };

  const getGroupAbbrev = (groupId: string) => {
       const upperGroupId = groupId.toUpperCase();
       for (const [key, config] of Object.entries(groupConfig)) {
           if (upperGroupId.includes(key.toUpperCase())) return config.abbrev;
       }
       // Fallback: first 3 letters
       return groupId.substring(0, 3);
  }

  // Scaling with pan offset
  const scale = (val: number, axis: 'x' | 'y') => {
      const unitPercent = 10 * zoom;
      const offset = val * unitPercent;
      return 50 + offset + (axis === 'x' ? pan.x : pan.y);
  };


  const getAxisLabel = (axis: AxisDef, side: 'pos' | 'neg') => {
      if (side === 'pos' && axis.positive_side?.label) return axis.positive_side.label;
      if (side === 'neg' && axis.negative_side?.label) return axis.negative_side.label;
      return side === 'pos' ? t("dimensionPos") : t("dimensionNeg");
  };

  // Two clamped lines instead of a single truncated one: the pole names are
  // the only key to reading the chart, cutting them makes it useless
  const AxisLabel = ({ axis, side, className, ...props }: { axis: AxisDef, side: 'pos'|'neg', className?: string, style?: React.CSSProperties }) => (
      <div className={cn("absolute max-w-[40%] text-center font-mono text-[9px] sm:text-[10px] uppercase tracking-[var(--tracking-label)] leading-tight text-fg-muted bg-surface-muted/85 rounded-xs px-1.5 py-0.5 z-10 line-clamp-2", className)} title={getAxisLabel(axis, side)} {...props}>
           {getAxisLabel(axis, side)}
      </div>
  );

  return (
    <div className={cn("w-full flex flex-col", fill && "h-full")}>
         {/* Chart area - fills available space */}
         <div
             ref={containerRef}
             onPointerDown={onPointerDown}
             onPointerMove={onPointerMove}
             onPointerUp={onPointerUp}
             onPointerCancel={onPointerUp}

             className={cn(
                 "relative w-full bg-surface-muted rounded-md overflow-hidden mx-auto select-none touch-none",
                 fill
                     ? "flex-1 min-h-[200px]"
                     : dimensionality === 1 ? "h-[200px]" : "h-[320px]",
                 "cursor-grab active:cursor-grabbing"
             )}
         >
              
              {dimensionality === 2 ? (
                <>
                  {/* 2D Grid Lines */}
                  <div className="absolute top-1/2 left-0 w-full h-[1px] bg-line-strong pointer-events-none" />
                  <div className="absolute top-0 left-1/2 w-[1px] h-full bg-line-strong pointer-events-none" />
                  
                  {/* 2D Labels: the x poles hug the edges with a tight width
                      cap so they never march into the central cluster */}
                  <AxisLabel axis={data.axes.y} side="pos" className="top-2 left-1/2 -translate-x-1/2 max-w-[72%]" />
                  <AxisLabel axis={data.axes.y} side="neg" className="bottom-2 left-1/2 -translate-x-1/2 max-w-[72%]" />
                  <AxisLabel axis={data.axes.x} side="pos" className="right-2 top-1/2 -translate-y-1/2 max-w-[24%] text-right" />
                  <AxisLabel axis={data.axes.x} side="neg" className="left-2 top-1/2 -translate-y-1/2 max-w-[24%] text-left" />
                </>
              ) : (
                <>
                   {/* 1D Grid Line */}
                   <div className="absolute top-1/2 left-0 w-full h-[1px] bg-line-strong pointer-events-none" />
                   
                   {/* 1D Labels */}
                   <AxisLabel axis={data.axes.x} side="pos" className="right-4 top-[10%]" />
                   <AxisLabel axis={data.axes.x} side="neg" className="left-4 top-[10%]" />
                </>
              )}

              {/* Scatter Points light up with the hovered group's centroid */}
              {data.scatter_sample.map((pt, i) => {
                  const isHighlighted = hoveredGroup !== null && pt.group_id === hoveredGroup;
                  const isDimmed = hoveredGroup !== null && pt.group_id !== hoveredGroup;
                  return (
                  <div
                    key={i}
                    className={`absolute rounded-full transition-opacity duration-150 ${
                        isHighlighted ? "w-2.5 h-2.5 opacity-90 z-10" : "w-1.5 h-1.5"
                    } ${isDimmed ? "opacity-[0.06]" : ""} ${hoveredGroup === null ? "opacity-20 hover:opacity-60" : ""}`}
                    style={{
                        left: `${scale(pt.x, 'x')}%`,
                        top: dimensionality === 1 ? '50%' : `${scale(-pt.y, 'y')}%`,
                        backgroundColor: getGroupColor(pt.group_id),
                        boxShadow: isHighlighted ? `0 0 0 2px color-mix(in srgb, ${getGroupColor(pt.group_id)} 30%, transparent)` : undefined,
                        transform: 'translate(-50%, -50%)'
                    }}
                  />
              )})}

              {/* Group Centroids with Labels: dot area tracks fragment count */}
               {data.groups.map((grp) => {
                   const cx = scale(grp.position_x, 'x');
                   const cy = dimensionality === 1 ? 50 : scale(-grp.position_y, 'y');
                   const color = getGroupColor(grp.group_id);
                   const abbrev = getGroupAbbrev(grp.group_id);
                   const maxFragments = Math.max(1, ...data.groups.map(g => g.stats?.n_fragments || 0));
                   const dotPx = 8 + 9 * Math.sqrt((grp.stats?.n_fragments || 1) / maxFragments);

                   const totalFragments = data.groups.reduce((s, g) => s + (g.stats?.n_fragments || 0), 0);
                   const sharePct = totalFragments > 0 ? Math.round(((grp.stats?.n_fragments || 0) / totalFragments) * 100) : 0;

                   return (
                   <TooltipProvider key={grp.group_id}>
                       <Tooltip>
                           <TooltipTrigger asChild>
                                <div
                                    className="absolute flex flex-col items-center cursor-pointer motion-safe:hover:scale-110 transition-transform duration-[var(--duration-fast)] z-20"
                                    style={{
                                        left: `${cx}%`,
                                        top: `${cy}%`,
                                        transform: 'translate(-50%, -50%)'
                                    }}
                                    onMouseEnter={() => setHoveredGroup(grp.group_id)}
                                    onMouseLeave={() => setHoveredGroup(null)}
                                >
                                    {/* Dot */}
                                    <div
                                        className="rounded-full border-2 border-surface shadow-float"
                                        style={{ backgroundColor: color, width: dotPx, height: dotPx }}
                                    />
                                    {/* Label */}
                                    <span
                                        className="text-[10px] font-semibold mt-0.5 px-1 rounded-xs bg-surface/85 whitespace-nowrap"
                                        style={{ color: color }}
                                    >
                                        {abbrev}
                                    </span>
                                </div>
                           </TooltipTrigger>
                           <TooltipContent side="top" className="p-0 overflow-hidden border-0 shadow-overlay">
                               <div className="px-3 py-2 flex items-center gap-2" style={{ backgroundColor: `color-mix(in srgb, ${color} 12%, transparent)` }}>
                                   <span className="inline-block h-2.5 w-2.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
                                   <span className="font-semibold text-[13px] leading-tight">{grp.group_id}</span>
                               </div>
                               <div className="px-3 py-2 space-y-1">
                                   <div className="flex items-baseline justify-between gap-6 text-xs">
                                       <span className="text-fg-muted">{t("fragments")}</span>
                                       <span className="font-medium tabular">{grp.stats.n_fragments} <span className="text-fg-muted font-normal">· {sharePct}%</span></span>
                                   </div>
                                   <div className="flex items-baseline justify-between gap-6 text-xs">
                                       <span className="text-fg-muted">{t("position")}</span>
                                       <span className="font-medium tabular">{grp.position_x.toFixed(2)}, {dimensionality === 1 ? '—' : grp.position_y.toFixed(2)}</span>
                                   </div>
                                   {typeof grp.stats?.n_x === "number" && (
                                       <div className="flex items-baseline justify-between gap-6 text-xs">
                                           <span className="text-fg-muted">{t("positionBasis")}</span>
                                           <span className="font-medium tabular">x: {grp.stats.n_x} · y: {grp.stats.n_y}</span>
                                       </div>
                                   )}
                               </div>
                           </TooltipContent>
                       </Tooltip>
                   </TooltipProvider>
               )})}
          </div>
          
          {/* Legend: hovering an entry highlights that group's points too */}
          <div className="flex flex-wrap gap-2 mt-2 justify-center shrink-0">
              {data.groups.map((grp) => (
                  <div
                      key={grp.group_id}
                      className={`flex items-center gap-1 text-xs cursor-default rounded-xs px-1 transition-opacity ${
                          hoveredGroup !== null && hoveredGroup !== grp.group_id ? "opacity-40" : ""
                      }`}
                      onMouseEnter={() => setHoveredGroup(grp.group_id)}
                      onMouseLeave={() => setHoveredGroup(null)}
                  >
                      <div
                          className="w-3 h-3 rounded-full"
                          style={{ backgroundColor: getGroupColor(grp.group_id) }}
                      />
                      <span className="text-fg-muted">{getGroupAbbrev(grp.group_id)}</span>
                  </div>
              ))}
          </div>

          <div className="flex justify-between items-center mt-1.5 px-2 shrink-0">
             {/* Varianza spiegata / segnale lungo gli assi ancorati */}
             <div className="flex items-center gap-1 text-xs text-fg-muted">
                 <span>{isStance ? t("stanceCoverage") : data.meta.axis_method === "semantic" ? t("signalCaptured") : t("explainedVariance")}: {signalPct}%</span>
                 <TooltipProvider>
                    <Tooltip>
                       <TooltipTrigger asChild>
                          <Info className="h-3 w-3 cursor-help" />
                       </TooltipTrigger>
                       <TooltipContent side="top" className="max-w-xs">
                          <div className="text-xs space-y-1">
                             <p><strong>{t("meaning")}</strong></p>
                             <p>• {isStance ? t("stanceLow") : t("lowVariance")}</p>
                             <p>• {isStance ? t("stanceHigh") : t("highVariance")}</p>
                             <p>• {data.meta.axis_method === "pca" ? "PC1" : t("axis1Short")}: {Math.round((data.meta.explained_variance_ratio?.[0] || 0) * 100)}% | {data.meta.axis_method === "pca" ? "PC2" : t("axis2Short")}: {dimensionality === 2 ? Math.round((data.meta.explained_variance_ratio?.[1] || 0) * 100) : 0}%</p>
                          </div>
                       </TooltipContent>
                    </Tooltip>
                 </TooltipProvider>
             </div>
             <div className="flex gap-1 items-center">
                 <Button variant="outline" size="icon" className="h-8 w-8 min-tap-none" onClick={() => setZoom(z => Math.max(0.2, z - 0.2))}>
                     <Minus className="h-3 w-3" />
                 </Button>
                 <span className="text-[10px] text-fg-muted w-8 text-center">{Math.round(zoom * 100)}%</span>
                 <Button variant="outline" size="icon" className="h-8 w-8 min-tap-none" onClick={() => setZoom(z => Math.min(6, z + 0.2))}>
                     <Plus className="h-3 w-3" />
                 </Button>
                 <Button variant="outline" size="icon" className="h-8 w-8 min-tap-none ml-1" onClick={resetView} title={t("resetView")}>
                     <RotateCcw className="h-3 w-3" />
                 </Button>
             </div>
          </div>

          {/* Weak signal: few interventions actually take a stance on these axes */}
          {lowStance && (
              <p className="mt-1.5 px-2 text-center text-[11px] leading-snug text-notice-fg shrink-0">
                  {t("weakStanceWarning")}
              </p>
          )}

          {/* Disclaimer: automated analysis, not a certified political placement */}
          <p className="mt-1.5 px-2 text-center text-[11px] leading-snug text-fg-muted shrink-0">
              {isStance ? t("stanceDisclaimer") : t("disclaimer")}{" "}
              <a
                href="/method"
                target="_blank"
                rel="noopener noreferrer"
                className="underline underline-offset-2 decoration-fg-faint hover:text-brand-fg transition-colors whitespace-nowrap"
              >
                  {t("methodLink")}
              </a>
          </p>
    </div>
  );
}
