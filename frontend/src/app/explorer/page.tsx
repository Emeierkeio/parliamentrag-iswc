"use client";

import { useState, useEffect } from "react";
import {
    Search,
    Play,
    Table as TableIcon,
    Code,
    RefreshCcw,
    Layers,
    ArrowRightLeft,
    Share2,
    Network,
    ShieldCheck,
    PanelLeftClose,
    PanelLeft,
} from "lucide-react";
import { AppBar } from "@/components/shell/AppBar";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { getGraphSchema, getGraphStats, executeCypherQuery, isWriteQuery } from "@/lib/graph-api";
import { GraphVisualizer } from "@/components/graph/GraphVisualizer";

export default function ExplorerPage() {

    const [schema, setSchema] = useState<any>(null);
    const [stats, setStats] = useState<any>(null);
    const [query, setQuery] = useState("MATCH (n:Deputy) RETURN n.first_name, n.last_name LIMIT 10");
    const [results, setResults] = useState<any[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [history, setHistory] = useState<string[]>([]);
    const [schemaOpen, setSchemaOpen] = useState(true);

    useEffect(() => {
        loadSchema();
    }, []);

    const loadSchema = async () => {
        try {
            const [s, st] = await Promise.all([getGraphSchema(), getGraphStats()]);
            setSchema(s);
            setStats(st);
        } catch (err) {
            console.error(err);
        }
    };

    const runQuery = async () => {
        setIsLoading(true);
        setError(null);
        try {
            const data = await executeCypherQuery(query);
            setResults(data);
            if (!history.includes(query)) {
                setHistory(prev => [query, ...prev].slice(0, 10));
            }
        } catch (err) {
            setError(err instanceof Error ? err.message : "Errore query");
            setResults([]);
        } finally {
            setIsLoading(false);
        }
    };

    const handleSchemaClick = (text: string, type: 'label' | 'rel') => {
        if (type === 'label') {
            setQuery(`MATCH (n:${text}) RETURN n LIMIT 25`);
        } else {
            setQuery(`MATCH ()-[r:${text}]->() RETURN r LIMIT 25`);
        }
    };

    return (
        <div className="flex h-dvh flex-col overflow-hidden bg-bg pb-[env(safe-area-inset-bottom)]">
            <AppBar />

            <main className="flex-1 min-h-0 flex flex-col overflow-hidden">
                <div className="container-page shrink-0 flex items-center gap-3 py-4">
                    <h1 className="serif-display text-2xl text-fg whitespace-nowrap">Graph Explorer</h1>

                    {stats && (
                        <div className="tabular hidden sm:flex items-center gap-2 text-xs text-fg-muted">
                            <span>{stats.total_nodes?.toLocaleString()} nodi</span>
                            <span>·</span>
                            <span>{stats.total_relationships?.toLocaleString()} relazioni</span>
                        </div>
                    )}

                    <div className="flex items-center gap-1.5 ml-auto">
                        <Badge variant="secondary" className="gap-1 text-xs">
                            <ShieldCheck className="h-3 w-3" />
                            <span className="hidden sm:inline">Read-only</span>
                        </Badge>
                        <Button size="sm" variant="ghost" onClick={loadSchema} className="h-8">
                            <RefreshCcw className="h-4 w-4 md:mr-1.5" />
                            <span className="hidden md:inline text-xs">Aggiorna</span>
                        </Button>
                        <Button size="sm" onClick={runQuery} disabled={isLoading || isWriteQuery(query)} className="h-8">
                            <Play className="h-4 w-4 md:mr-1.5 fill-current" />
                            <span className="hidden sm:inline text-xs">Esegui</span>
                        </Button>
                    </div>
                </div>

                {/* Content area: Schema panel + Query/Results */}
                <div className="container-page flex-1 min-h-0 pb-4">
                    <div className="relative flex h-full overflow-hidden rounded-lg border border-line">
                        {/* Schema Panel (collapsible) */}
                        <div className={`hidden md:flex flex-col border-r border-line bg-surface-muted transition-all duration-300 ${schemaOpen ? 'w-[260px]' : 'w-0 overflow-hidden'}`}>
                            <div className="flex items-center justify-between px-4 py-3 border-b border-line shrink-0">
                                <span className="label-mono">Schema</span>
                                <Button variant="ghost" size="icon" onClick={() => setSchemaOpen(false)} className="h-7 w-7">
                                    <PanelLeftClose className="h-3.5 w-3.5" />
                                </Button>
                            </div>
                            <ScrollArea className="flex-1">
                                <div className="p-4 space-y-5">
                                    {/* Labels */}
                                    <div>
                                        <h3 className="text-sm font-semibold text-fg mb-2.5 flex items-center gap-1.5">
                                            <Layers className="h-3.5 w-3.5 text-fg-muted" aria-hidden />
                                            Labels
                                        </h3>
                                        <div className="flex flex-wrap gap-1.5">
                                            {schema?.labels?.map((label: string) => (
                                                <Badge
                                                    key={label}
                                                    variant="outline"
                                                    className="cursor-pointer text-xs hover:bg-brand-soft hover:text-brand-fg transition-colors"
                                                    onClick={() => handleSchemaClick(label, 'label')}
                                                >
                                                    {label}
                                                </Badge>
                                            ))}
                                        </div>
                                    </div>

                                    <Separator />

                                    {/* Relationships */}
                                    <div>
                                        <h3 className="text-sm font-semibold text-fg mb-2.5 flex items-center gap-1.5">
                                            <ArrowRightLeft className="h-3.5 w-3.5 text-fg-muted" aria-hidden />
                                            Relationships
                                        </h3>
                                        <div className="flex flex-col gap-0.5">
                                            {schema?.relationship_types?.map((rel: string) => (
                                                <button
                                                    key={rel}
                                                    className="text-xs text-left text-fg-secondary px-2 py-1.5 rounded-md hover:bg-surface-sunken hover:text-fg transition-colors truncate font-mono"
                                                    onClick={() => handleSchemaClick(rel, 'rel')}
                                                >
                                                    :{rel}
                                                </button>
                                            ))}
                                        </div>
                                    </div>
                                </div>
                            </ScrollArea>
                        </div>

                        {/* Main query + results area */}
                        <div className="flex-1 flex flex-col min-w-0">
                            {/* Schema toggle when collapsed */}
                            {!schemaOpen && (
                                <div className="hidden md:block">
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        onClick={() => setSchemaOpen(true)}
                                        className="absolute z-10 mt-2 ml-2 h-8 w-8 bg-surface border border-line shadow-float"
                                    >
                                        <PanelLeft className="h-3.5 w-3.5" />
                                    </Button>
                                </div>
                            )}

                            {/* Query Editor */}
                            <div className="h-[100px] md:h-[160px] border-b border-line relative bg-surface-muted shrink-0 overflow-hidden">
                                <Textarea
                                    value={query}
                                    onChange={(e) => setQuery(e.target.value)}
                                    onKeyDown={(e) => {
                                        if (e.key === 'Enter' && e.shiftKey) {
                                            e.preventDefault();
                                            if (!isWriteQuery(query)) runQuery();
                                        }
                                    }}
                                    className="w-full h-full font-mono text-sm p-3 md:p-4 resize-none border-0 focus-visible:ring-0 bg-transparent overflow-y-auto"
                                    placeholder="Inserisci una query Cypher..."
                                />
                                <div className="absolute bottom-2 right-2 font-mono text-[10px] text-fg-muted bg-bg/80 px-2 py-0.5 rounded-xs hidden sm:block">
                                    Shift+Enter per eseguire
                                </div>
                            </div>

                            {/* Write query warning */}
                            {isWriteQuery(query) && (
                                <div className="px-3 md:px-4 py-2 border-b border-line shrink-0">
                                    <Alert variant="destructive" className="py-2">
                                        <ShieldCheck className="h-4 w-4" />
                                        <AlertDescription className="text-xs">
                                            Le operazioni di scrittura non sono consentite. Il Graph Explorer è in modalità sola lettura.
                                        </AlertDescription>
                                    </Alert>
                                </div>
                            )}

                            {/* Results */}
                            <div className="flex-1 flex flex-col min-h-0 bg-bg">
                                {error ? (
                                    <div className="p-4">
                                        <Alert variant="destructive">
                                            <AlertTitle>Errore Query</AlertTitle>
                                            <AlertDescription className="font-mono text-xs mt-2">
                                                {error}
                                            </AlertDescription>
                                        </Alert>
                                    </div>
                                ) : (
                                    <Tabs defaultValue="table" className="flex-1 flex flex-col">
                                        <div className="px-3 md:px-4 border-b border-line flex items-center justify-between shrink-0">
                                            <TabsList className="my-2">
                                                <TabsTrigger value="table" className="text-xs md:text-sm gap-1 md:gap-1.5">
                                                    <TableIcon className="h-4 w-4" />
                                                    <span className="hidden sm:inline">Tabella</span>
                                                </TabsTrigger>
                                                <TabsTrigger value="graph" className="text-xs md:text-sm gap-1 md:gap-1.5">
                                                    <Share2 className="h-4 w-4" />
                                                    <span className="hidden sm:inline">Grafo</span>
                                                </TabsTrigger>
                                                <TabsTrigger value="json" className="text-xs md:text-sm gap-1 md:gap-1.5">
                                                    <Code className="h-4 w-4" />
                                                    <span className="hidden sm:inline">JSON</span>
                                                </TabsTrigger>
                                            </TabsList>
                                            <span className="tabular text-xs text-fg-muted">
                                                {results.length} risultati
                                            </span>
                                        </div>

                                        <TabsContent value="table" className="flex-1 min-h-0 p-0 m-0">
                                            <ScrollArea className="h-full">
                                                <div className="p-3 md:p-4">
                                                    {results.length > 0 ? (
                                                        <div className="rounded-md border border-line overflow-x-auto">
                                                            <table className="w-full text-sm">
                                                                <thead className="bg-surface-muted text-left">
                                                                    <tr>
                                                                        {Object.keys(results[0]).map(key => (
                                                                            <th key={key} className="p-2 md:p-3 font-medium text-fg-muted whitespace-nowrap border-b border-line text-xs md:text-sm">
                                                                                {key}
                                                                            </th>
                                                                        ))}
                                                                    </tr>
                                                                </thead>
                                                                <tbody>
                                                                    {results.map((row, i) => (
                                                                        <tr key={i} className="border-b border-line last:border-0 hover:bg-surface-muted">
                                                                            {Object.values(row).map((val: any, j) => (
                                                                                <td key={j} className="p-2 md:p-3 max-w-[200px] md:max-w-[300px] truncate border-r last:border-0 border-line text-xs md:text-sm">
                                                                                    {typeof val === 'object' ? JSON.stringify(val) : String(val)}
                                                                                </td>
                                                                            ))}
                                                                        </tr>
                                                                    ))}
                                                                </tbody>
                                                            </table>
                                                        </div>
                                                    ) : (
                                                        <div className="flex flex-col items-center justify-center py-20 text-fg-muted">
                                                            <Search className="h-10 w-10 mb-4 text-fg-faint" aria-hidden />
                                                            <p className="text-sm">Nessun risultato</p>
                                                        </div>
                                                    )}
                                                </div>
                                            </ScrollArea>
                                        </TabsContent>

                                        <TabsContent value="graph" className="flex-1 min-h-0 p-0 m-0 overflow-hidden">
                                            <GraphVisualizer data={results} />
                                        </TabsContent>

                                        <TabsContent value="json" className="flex-1 min-h-0 p-0 m-0">
                                            <ScrollArea className="h-full">
                                                <pre className="p-3 md:p-4 text-xs font-mono">
                                                    {JSON.stringify(results, null, 2)}
                                                </pre>
                                            </ScrollArea>
                                        </TabsContent>
                                    </Tabs>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            </main>
        </div>
    );
}
