"use client";

import { useState } from "react";
import { Check, ChevronsUpDown, X, Users, Shield } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

const GROUPS: { value: string; label: string; shortLabel: string }[] = [
  { value: "FRATELLI D'ITALIA", label: "Fratelli d'Italia", shortLabel: "FdI" },
  { value: "LEGA - SALVINI PREMIER", label: "Lega - Salvini Premier", shortLabel: "Lega" },
  { value: "FORZA ITALIA - BERLUSCONI PRESIDENTE - PPE", label: "Forza Italia - Berlusconi Presidente - PPE", shortLabel: "FI" },
  { value: "NOI MODERATI (NOI CON L'ITALIA, CORAGGIO ITALIA, UDC E ITALIA AL CENTRO)-MAIE-CENTRO POPOLARE", label: "Noi Moderati - MAIE - Centro Popolare", shortLabel: "NM" },
  { value: "PARTITO DEMOCRATICO - ITALIA DEMOCRATICA E PROGRESSISTA", label: "Partito Democratico - Italia Democratica e Progressista", shortLabel: "PD" },
  { value: "MOVIMENTO 5 STELLE", label: "Movimento 5 Stelle", shortLabel: "M5S" },
  { value: "AZIONE-POPOLARI EUROPEISTI RIFORMATORI-RENEW EUROPE", label: "Azione - Popolari Europeisti Riformatori - Renew Europe", shortLabel: "Azione" },
  { value: "ITALIA VIVA-CASA RIFORMISTA (IV-CR)", label: "Italia Viva - Casa Riformista", shortLabel: "IV" },
  { value: "ALLEANZA VERDI E SINISTRA", label: "Alleanza Verdi e Sinistra", shortLabel: "AVS" },
  { value: "MISTO", label: "Misto", shortLabel: "Misto" },
];

const MAGGIORANZA_VALUES = [
  "FRATELLI D'ITALIA",
  "LEGA - SALVINI PREMIER",
  "FORZA ITALIA - BERLUSCONI PRESIDENTE - PPE",
  "NOI MODERATI (NOI CON L'ITALIA, CORAGGIO ITALIA, UDC E ITALIA AL CENTRO)-MAIE-CENTRO POPOLARE",
];

const OPPOSIZIONE_VALUES = [
  "PARTITO DEMOCRATICO - ITALIA DEMOCRATICA E PROGRESSISTA",
  "MOVIMENTO 5 STELLE",
  "ALLEANZA VERDI E SINISTRA",
  "AZIONE-POPOLARI EUROPEISTI RIFORMATORI-RENEW EUROPE",
  "ITALIA VIVA-CASA RIFORMISTA (IV-CR)",
];

interface GroupSelectorProps {
  selectedGroups: string[];
  onSelect: (groups: string[]) => void;
}

export function GroupSelector({ selectedGroups, onSelect }: GroupSelectorProps) {
  const [open, setOpen] = useState(false);

  const toggleGroup = (value: string) => {
    if (selectedGroups.includes(value)) {
      onSelect(selectedGroups.filter((g) => g !== value));
    } else {
      onSelect([...selectedGroups, value]);
    }
  };

  const toggleCoalition = (coalitionValues: string[]) => {
    const allSelected = coalitionValues.every((v) => selectedGroups.includes(v));
    if (allSelected) {
      onSelect(selectedGroups.filter((g) => !coalitionValues.includes(g)));
    } else {
      const newGroups = new Set([...selectedGroups, ...coalitionValues]);
      onSelect(Array.from(newGroups));
    }
  };

  const removeGroup = (value: string) => {
    onSelect(selectedGroups.filter((g) => g !== value));
  };

  const clearAll = () => {
    onSelect([]);
  };

  const isMaggioranzaFull = MAGGIORANZA_VALUES.every((v) => selectedGroups.includes(v));
  const isMaggioranzaPartial = !isMaggioranzaFull && MAGGIORANZA_VALUES.some((v) => selectedGroups.includes(v));
  const isOpposizioneFull = OPPOSIZIONE_VALUES.every((v) => selectedGroups.includes(v));
  const isOpposizionePartial = !isOpposizioneFull && OPPOSIZIONE_VALUES.some((v) => selectedGroups.includes(v));

  const getLabel = (value: string) => GROUPS.find((g) => g.value === value)?.shortLabel ?? value;

  return (
    <div className="space-y-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            aria-expanded={open}
            className="w-full justify-between font-normal text-left h-10"
          >
            {selectedGroups.length > 0 ? (
              <span className="truncate text-sm">
                {selectedGroups.length} grupp{selectedGroups.length === 1 ? "o" : "i"} selezionat{selectedGroups.length === 1 ? "o" : "i"}
              </span>
            ) : (
              <span className="text-fg-muted">Seleziona gruppi...</span>
            )}
            <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0" align="start">
          <Command>
            <CommandInput placeholder="Cerca gruppo..." />
            <CommandList>
              <CommandEmpty>Nessun gruppo trovato.</CommandEmpty>

              {/* Coalitions */}
              <CommandGroup heading="Coalizioni">
                <CommandItem
                  value="maggioranza-coalition"
                  onSelect={() => toggleCoalition(MAGGIORANZA_VALUES)}
                  className="gap-2"
                >
                  <div className={cn(
                    "flex h-4 w-4 items-center justify-center rounded-xs border border-line-control",
                    isMaggioranzaFull ? "border-brand bg-brand text-on-brand" : "opacity-50 [&_svg]:invisible"
                  )}>
                    {isMaggioranzaFull && <Check className="h-3 w-3" />}
                    {isMaggioranzaPartial && <div className="h-2 w-2 bg-brand rounded-[2px]" />}
                  </div>
                  <Shield className="h-4 w-4 text-fg-muted" aria-hidden />
                  <span className="font-medium">Maggioranza</span>
                  <span className="ml-auto text-xs text-fg-muted">4 gruppi</span>
                </CommandItem>
                <CommandItem
                  value="opposizione-coalition"
                  onSelect={() => toggleCoalition(OPPOSIZIONE_VALUES)}
                  className="gap-2"
                >
                  <div className={cn(
                    "flex h-4 w-4 items-center justify-center rounded-xs border border-line-control",
                    isOpposizioneFull ? "border-brand bg-brand text-on-brand" : "opacity-50 [&_svg]:invisible"
                  )}>
                    {isOpposizioneFull && <Check className="h-3 w-3" />}
                    {isOpposizionePartial && <div className="h-2 w-2 bg-brand rounded-[2px]" />}
                  </div>
                  <Users className="h-4 w-4 text-fg-muted" aria-hidden />
                  <span className="font-medium">Opposizione</span>
                  <span className="ml-auto text-xs text-fg-muted">5 gruppi</span>
                </CommandItem>
              </CommandGroup>

              <CommandSeparator />

              {/* Individual groups */}
              <CommandGroup heading="Gruppi parlamentari">
                {GROUPS.map((group) => {
                  const isSelected = selectedGroups.includes(group.value);
                  return (
                    <CommandItem
                      key={group.value}
                      value={group.value}
                      onSelect={() => toggleGroup(group.value)}
                      className="gap-2"
                    >
                      <div className={cn(
                        "flex h-4 w-4 items-center justify-center rounded-xs border border-line-control",
                        isSelected ? "border-brand bg-brand text-on-brand" : "opacity-50 [&_svg]:invisible"
                      )}>
                        <Check className="h-3 w-3" />
                      </div>
                      {group.label}
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>

      {/* Selected groups chips */}
      {selectedGroups.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selectedGroups.map((value) => (
            <Badge
              key={value}
              variant="secondary"
              className="rounded-full pl-2.5 pr-1.5 py-0.5 gap-1 text-xs font-normal cursor-pointer hover:bg-surface-sunken transition-colors"
              onClick={() => removeGroup(value)}
            >
              {getLabel(value)}
              <X className="h-3 w-3 text-fg-muted hover:text-fg" />
            </Badge>
          ))}
          {selectedGroups.length > 1 && (
            <button
              onClick={clearAll}
              className="min-h-6 rounded-full px-2 text-xs text-fg-muted hover:text-fg hover:bg-surface-muted transition-colors"
            >
              Rimuovi tutti
            </button>
          )}
        </div>
      )}
    </div>
  );
}
