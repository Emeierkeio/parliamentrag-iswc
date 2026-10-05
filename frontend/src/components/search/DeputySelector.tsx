"use client";

import { useState, useEffect, useRef } from "react";
import { Search, User, X, Loader2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { config } from "@/config";

export interface Deputy {
  id: string;
  first_name: string;
  last_name: string;
  group?: string;
  imgUrl?: string;
}

interface DeputySelectorProps {
  selectedDeputies: Deputy[];
  onSelect: (deputies: Deputy[]) => void;
}

export function DeputySelector({ selectedDeputies, onSelect }: DeputySelectorProps) {
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState<Deputy[]>([]);
  const [loading, setLoading] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const wrapperRef = useRef<HTMLDivElement>(null);

  // Debounce logic
  useEffect(() => {
    const timer = setTimeout(async () => {
      if (query.length < 2) {
        setSuggestions([]);
        return;
      }

      setLoading(true);
      try {
        const res = await fetch(`${config.api.baseUrl}/search/deputies?q=${encodeURIComponent(query)}`);
        if (res.ok) {
            const data = await res.json();
            setSuggestions(data);
            setIsOpen(true);
        }
      } catch (err) {
        console.error("Error fetching deputies:", err);
      } finally {
        setLoading(false);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [query]);

  // Click outside to close
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const toggleDeputy = (deputy: Deputy) => {
    const isSelected = selectedDeputies.some((d) => d.id === deputy.id);
    if (isSelected) {
      onSelect(selectedDeputies.filter((d) => d.id !== deputy.id));
    } else {
      onSelect([...selectedDeputies, deputy]);
    }
    setQuery("");
    setIsOpen(false);
  };

  const removeDeputy = (id: string) => {
    onSelect(selectedDeputies.filter((d) => d.id !== id));
  };

  return (
    <div className="space-y-2">
      {/* Selected deputies badges */}
      {selectedDeputies.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selectedDeputies.map((deputy) => (
            <div
              key={deputy.id}
              className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-brand-soft text-brand-fg text-xs font-medium"
            >
              <div className="h-4 w-4 rounded-full bg-brand-soft-strong flex items-center justify-center overflow-hidden shrink-0">
                {deputy.imgUrl ? (
                  <img src={deputy.imgUrl} alt="Foto" className="h-full w-full object-cover" />
                ) : (
                  <User className="h-2.5 w-2.5 text-brand-fg" />
                )}
              </div>
              <span className="truncate max-w-[120px]">
                {deputy.first_name} {deputy.last_name}
              </span>
              <button
                onClick={() => removeDeputy(deputy.id)}
                className="ml-0.5 text-fg-muted hover:text-fg transition-colors"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Search input */}
      <div className="relative w-full" ref={wrapperRef}>
        <div className="relative">
          <Search className="absolute left-3 top-2.5 h-4 w-4 text-fg-muted" />
          <Input
            placeholder="Cerca deputato..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-9"
            onFocus={() => {
              if (suggestions.length > 0) setIsOpen(true);
            }}
          />
          {loading && (
            <Loader2 className="absolute right-3 top-2.5 h-4 w-4 animate-spin text-fg-muted" />
          )}
        </div>

        {isOpen && suggestions.length > 0 && (
          <Card className="absolute top-full mt-1 w-full z-50 max-h-60 gap-0 overflow-y-auto rounded-md py-0 shadow-overlay border-line bg-surface">
            <ul className="py-1">
              {suggestions.map((deputy) => {
                const isSelected = selectedDeputies.some((d) => d.id === deputy.id);
                return (
                  <li
                    key={deputy.id}
                    className={cn(
                      "px-3 py-2 hover:bg-surface-muted hover:text-fg cursor-pointer flex items-center gap-3 transition-colors",
                      isSelected && "bg-brand-soft"
                    )}
                    onClick={() => toggleDeputy(deputy)}
                  >
                    <div className="h-8 w-8 rounded-full bg-surface-muted flex items-center justify-center shrink-0">
                      <User className="h-4 w-4 text-fg-muted" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium text-fg">
                        {deputy.first_name} {deputy.last_name}
                      </p>
                      <p className="text-xs text-fg-muted truncate">
                        {deputy.group}
                      </p>
                    </div>
                    {isSelected && (
                      <div className="h-4 w-4 rounded-full bg-brand flex items-center justify-center shrink-0">
                        <X className="h-2.5 w-2.5 text-on-brand" />
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          </Card>
        )}
      </div>
    </div>
  );
}
