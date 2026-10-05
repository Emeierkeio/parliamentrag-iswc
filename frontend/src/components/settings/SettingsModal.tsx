"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Settings, RefreshCw, Save, AlertCircle, Info } from "lucide-react";
import { getConfig, reloadConfig, updateConfig } from "@/lib/api";
import type { SystemConfig, ConfigUpdate } from "@/lib/api";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";

import {
  RetrievalEditor,
  AuthorityEditor,
  GenerationEditor,
  QueryRewritingEditor,
  weightsSumValid,
} from "./GraphicalEditors";

interface SettingsModalProps {
  open: boolean;
  onClose: () => void;
}

type SettingsTab = "retrieval" | "authority" | "generation" | "rewriting";

export function SettingsModal({ open, onClose }: SettingsModalProps) {
  const t = useTranslations("Settings");
  // One section at a time: the four editors stacked were a wall of fields
  const [activeTab, setActiveTab] = useState<SettingsTab>("retrieval");
  const [configData, setConfigData] = useState<SystemConfig | null>(null);
  const [originalData, setOriginalData] = useState<SystemConfig | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const hasUnsavedChanges =
    configData !== null &&
    originalData !== null &&
    JSON.stringify(configData) !== JSON.stringify(originalData);

  const weightsValid =
    configData === null ||
    (weightsSumValid(configData.retrieval.merger_weights) &&
      weightsSumValid(configData.authority.weights));

  const loadConfig = async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getConfig();
      setConfigData(data);
      setOriginalData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("loadError"));
    } finally {
      setIsLoading(false);
    }
  };

  const handleReload = async () => {
    setIsLoading(true);
    setError(null);
    setSuccess(false);
    try {
      const data = await reloadConfig();
      setConfigData(data);
      setOriginalData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("reloadError"));
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (open) {
      loadConfig();
      setSuccess(false);
    }
  }, [open]);

  const handleSave = async () => {
    if (!configData) return;
    setIsLoading(true);
    setError(null);
    setSuccess(false);
    try {
      const payload: ConfigUpdate = {
        retrieval: configData.retrieval,
        authority: configData.authority,
        generation: configData.generation,
        query_rewriting: configData.query_rewriting,
      };
      const updated = await updateConfig(payload);
      setConfigData(updated);
      setOriginalData(updated);
      setSuccess(true);
      setTimeout(() => setSuccess(false), 3000);
    } catch (err) {
      setError(err instanceof Error ? err.message : t("saveError"));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      {/* Full screen on phones; the desktop dialog stays a centered panel.
          Auto-focus lands on the close X and paints its focus ring as a
          stray box — prevented, focus stays on the dialog itself. */}
      <DialogContent
        onOpenAutoFocus={(e) => e.preventDefault()}
        className="max-w-none w-dvw h-dvh rounded-none border-0 sm:max-w-4xl sm:w-auto sm:h-[85vh] sm:rounded-lg sm:border flex flex-col p-4 sm:p-6 gap-3 sm:gap-4">
        <DialogHeader className="shrink-0">
          <DialogTitle className="serif-display flex items-center gap-2 text-lg font-semibold tracking-tight">
            <Settings className="h-5 w-5 text-primary" />
            {t("title")}
            {hasUnsavedChanges && (
              <Badge variant="outline" className="text-xs font-normal text-notice-fg border-notice/40 bg-notice-soft ml-1">
                {t("unsavedChanges")}
              </Badge>
            )}
          </DialogTitle>
          <DialogDescription className="flex items-start gap-1.5 text-left">
            <Info className="h-3.5 w-3.5 shrink-0 mt-0.5" />
            {t("description")}
          </DialogDescription>
        </DialogHeader>

        <div className="flex-1 overflow-hidden flex flex-col gap-3 min-h-0">
          {error && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>{t("error")}</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          {success && (
            <Alert className="bg-brand-soft text-brand-fg border-brand/30">
              <Save className="h-4 w-4" />
              <AlertTitle>{t("saved")}</AlertTitle>
              <AlertDescription>{t("savedMessage")}</AlertDescription>
            </Alert>
          )}

          {/* Section tabs — the tab names the section, so the card headers
              inside are hidden and each tab opens straight on its fields */}
          <div className="flex rounded-full border border-line p-0.5 bg-surface-muted shrink-0">
            {(
              [
                ["retrieval", t("tabRetrieval")],
                ["authority", t("tabAuthority")],
                ["generation", t("tabGeneration")],
                ["rewriting", t("tabRewriting")],
              ] as const
            ).map(([key, label]) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                aria-pressed={activeTab === key}
                className={
                  activeTab === key
                    ? "flex-1 px-2 py-1.5 rounded-full text-xs font-medium bg-brand text-on-brand"
                    : "flex-1 px-2 py-1.5 rounded-full text-xs font-medium text-fg-muted hover:text-fg transition-all"
                }
              >
                {label}
              </button>
            ))}
          </div>

          <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain [&_[data-slot=card]]:border-0 [&_[data-slot=card]]:shadow-none [&_[data-slot=card]]:bg-transparent [&_[data-slot=card]]:px-0 [&_[data-slot=card]]:py-2 [&_[data-slot=card-header]]:hidden [&_[data-slot=card-content]]:px-1">
            {configData ? (
              <div className="pb-4">
                {activeTab === "retrieval" && (
                  <RetrievalEditor
                    data={configData.retrieval}
                    onChange={(retrieval) => setConfigData({ ...configData, retrieval })}
                  />
                )}
                {activeTab === "authority" && (
                  <AuthorityEditor
                    data={configData.authority}
                    onChange={(authority) => setConfigData({ ...configData, authority })}
                  />
                )}
                {activeTab === "generation" && (
                  <GenerationEditor
                    data={configData.generation}
                    baselineModels={originalData?.generation.models}
                    onChange={(generation) => setConfigData({ ...configData, generation })}
                  />
                )}
                {activeTab === "rewriting" && (
                  <QueryRewritingEditor
                    data={configData.query_rewriting}
                    baselineModel={originalData?.query_rewriting.model}
                    onChange={(query_rewriting) => setConfigData({ ...configData, query_rewriting })}
                  />
                )}
              </div>
            ) : (
              <div className="flex items-center justify-center h-full">
                <RefreshCw className="h-8 w-8 animate-spin text-muted-foreground" />
              </div>
            )}
          </div>
        </div>

        <DialogFooter className="shrink-0 flex-row flex-wrap items-center gap-2">
          <div className="flex-1 flex items-center gap-3 justify-start min-w-0">
            <Button variant="outline" size="sm" onClick={handleReload} disabled={isLoading}>
              <RefreshCw className={`h-4 w-4 sm:mr-2 ${isLoading ? "animate-spin" : ""}`} />
              <span className="hidden sm:inline">{t("reloadYaml")}</span>
            </Button>
            {!weightsValid && (
              <span className="hidden sm:inline text-xs text-destructive truncate">
                {t("weightsInvalid")}
              </span>
            )}
          </div>
          <Button variant="outline" onClick={onClose} disabled={isLoading}>
            {t("cancel")}
          </Button>
          <Button
            onClick={handleSave}
            disabled={isLoading || !hasUnsavedChanges || !weightsValid}
            className={hasUnsavedChanges && weightsValid ? "" : "opacity-50"}
          >
            {isLoading ? (
              <>
                <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
                {t("saving")}
              </>
            ) : (
              <>
                <Save className="h-4 w-4 mr-2" />
                {t("saveChanges")}
              </>
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
