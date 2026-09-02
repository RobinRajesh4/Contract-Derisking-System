import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Search, X } from "lucide-react";

export interface AnalysisFilterState {
  search: string;
  riskLevel: string; // "all" | "high" | "medium" | "low"
  domain: string; // "all" | domain name
  dateRange: string; // "all" | "7d" | "30d" | "90d"
}

export const DEFAULT_FILTERS: AnalysisFilterState = {
  search: "",
  riskLevel: "all",
  domain: "all",
  dateRange: "all",
};

interface AnalysisFiltersProps {
  filters: AnalysisFilterState;
  onChange: (filters: AnalysisFilterState) => void;
  domains: string[];
}

export function AnalysisFilters({
  filters,
  onChange,
  domains,
}: AnalysisFiltersProps) {
  const update = (patch: Partial<AnalysisFilterState>) =>
    onChange({ ...filters, ...patch });

  const hasActiveFilters =
    filters.search !== "" ||
    filters.riskLevel !== "all" ||
    filters.domain !== "all" ||
    filters.dateRange !== "all";

  return (
    <div className="flex flex-col sm:flex-row gap-3 flex-wrap">
      <div className="relative flex-1 min-w-[200px]">
        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search by filename..."
          value={filters.search}
          onChange={(e) =>
            update({ search: e.target.value })
          }
          className="pl-9"
        />
      </div>

      <Select
        value={filters.riskLevel}
        onValueChange={(v) =>
          update({ riskLevel: v })
        }
      >
        <SelectTrigger className="w-full sm:w-[160px]">
          <SelectValue placeholder="Risk level" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">
            All Risk Levels
          </SelectItem>
          <SelectItem value="high">
            High Risk
          </SelectItem>
          <SelectItem value="medium">
            Medium Risk
          </SelectItem>
          <SelectItem value="low">
            Low Risk
          </SelectItem>
        </SelectContent>
      </Select>

      <Select
        value={filters.domain}
        onValueChange={(v) =>
          update({ domain: v })
        }
      >
        <SelectTrigger className="w-full sm:w-[160px]">
          <SelectValue placeholder="Domain" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">
            All Domains
          </SelectItem>
          {domains.map((d) => (
            <SelectItem key={d} value={d}>
              {d}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Select
        value={filters.dateRange}
        onValueChange={(v) =>
          update({ dateRange: v })
        }
      >
        <SelectTrigger className="w-full sm:w-[160px]">
          <SelectValue placeholder="Date range" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">
            All Time
          </SelectItem>
          <SelectItem value="7d">
            Last 7 Days
          </SelectItem>
          <SelectItem value="30d">
            Last 30 Days
          </SelectItem>
          <SelectItem value="90d">
            Last 90 Days
          </SelectItem>
        </SelectContent>
      </Select>

      {hasActiveFilters && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() =>
            onChange(DEFAULT_FILTERS)
          }
          className="gap-1"
        >
          <X className="h-4 w-4" />
          Clear
        </Button>
      )}
    </div>
  );
}

/** Shared filtering logic so Analyses list and Insights dashboard behave identically. */
export function applyAnalysisFilters(
  analyses: any[],
  filters: AnalysisFilterState
): any[] {
  const now = Date.now();

  const rangeMs: Record<string, number> = {
    "7d": 7 * 24 * 60 * 60 * 1000,
    "30d": 30 * 24 * 60 * 60 * 1000,
    "90d": 90 * 24 * 60 * 60 * 1000,
  };

  return analyses.filter((a: any) => {
    const name = (
      a.filename ||
      a.analysis_id ||
      ""
    ).toLowerCase();

    if (
      filters.search &&
      !name.includes(
        filters.search.toLowerCase()
      )
    ) {
      return false;
    }

    const results =
      a.results || a.clauses || [];

    if (filters.riskLevel !== "all") {
      const hasRisk = results.some(
        (r: any) =>
          (
            r.classification?.risk_level ||
            ""
          ).toLowerCase() ===
          filters.riskLevel
      );

      if (!hasRisk) return false;
    }

    if (filters.domain !== "all") {
      const hasDomain = results.some(
        (r: any) =>
          (
            r.classification?.domain ||
            "Other"
          ) === filters.domain
      );

      if (!hasDomain) return false;
    }

    if (filters.dateRange !== "all") {
      const dateStr =
        a.created_at || a.updated_at;

      if (!dateStr) return false;

      const age =
        now - new Date(dateStr).getTime();

      if (
        age > rangeMs[filters.dateRange]
      ) {
        return false;
      }
    }

    return true;
  });
}

/** Collects the distinct domain names present across a set of analyses, for populating the filter dropdown. */
export function collectDomains(
  analyses: any[]
): string[] {
  const set = new Set<string>();

  analyses.forEach((a: any) => {
    const results =
      a.results || a.clauses || [];

    results.forEach((r: any) => {
      set.add(
        r.classification?.domain ||
          "Other"
      );
    });
  });

  return Array.from(set).sort();
}