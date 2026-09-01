import { useState } from "react";
import { ChevronRight, ChevronDown, Edit, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PolicyLabel } from "./LabelManager";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface LabelTreeProps {
  labels: PolicyLabel[];
  selectedLabelId: string | null;
  onSelectLabel: (labelId: string | null) => void;
  onDeleteLabel: (labelId: string) => void;
}

export function LabelTree({ labels, selectedLabelId, onSelectLabel, onDeleteLabel }: LabelTreeProps) {
  const [expandedLabels, setExpandedLabels] = useState<Set<string>>(new Set());

  const toggleExpand = (labelId: string) => {
    const newExpanded = new Set(expandedLabels);
    if (newExpanded.has(labelId)) {
      newExpanded.delete(labelId);
    } else {
      newExpanded.add(labelId);
    }
    setExpandedLabels(newExpanded);
  };

  const renderLabel = (label: PolicyLabel, depth: number = 0) => {
    const childLabels = labels.filter(l => l.parentLabelId === label.id);
    const hasChildren = childLabels.length > 0;
    const isExpanded = expandedLabels.has(label.id);
    const isSelected = selectedLabelId === label.id;

    return (
      <div key={label.id}>
        <ContextMenu>
          <ContextMenuTrigger>
            <div
              className={`flex items-center gap-2 py-2 px-3 rounded-md cursor-pointer transition-colors hover:bg-accent ${
                isSelected ? "bg-accent" : ""
              }`}
              style={{ paddingLeft: `${depth * 16 + 12}px` }}
              onClick={() => onSelectLabel(isSelected ? null : label.id)}
            >
              {hasChildren && (
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleExpand(label.id);
                  }}
                  className="p-0 hover:bg-transparent"
                >
                  {isExpanded ? (
                    <ChevronDown className="h-4 w-4" />
                  ) : (
                    <ChevronRight className="h-4 w-4" />
                  )}
                </button>
              )}
              {!hasChildren && <div className="w-4" />}
              <div
                className="h-3 w-3 rounded-full flex-shrink-0"
                style={{ backgroundColor: label.color }}
              />
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className="text-sm flex-1 break-words leading-tight">
                      {label.name}
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p>{label.name}</p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
              <span className="text-xs text-muted-foreground flex-shrink-0">
                {label.policyIds.length}
              </span>
            </div>
          </ContextMenuTrigger>
          <ContextMenuContent>
            <ContextMenuItem
              onClick={() => onDeleteLabel(label.id)}
              className="text-destructive"
            >
              <Trash2 className="mr-2 h-4 w-4" />
              Delete Label
            </ContextMenuItem>
          </ContextMenuContent>
        </ContextMenu>

        {hasChildren && isExpanded && (
          <div className="animate-accordion-down">
            {childLabels.map(child => renderLabel(child, depth + 1))}
          </div>
        )}
      </div>
    );
  };

  const topLevelLabels = labels.filter(l => l.parentLabelId === null);

  return (
    <div className="space-y-1">
      {topLevelLabels.length === 0 ? (
        <p className="text-sm text-muted-foreground px-3 py-2">
          No labels yet. Create one to get started.
        </p>
      ) : (
        topLevelLabels.map(label => renderLabel(label))
      )}
    </div>
  );
}
