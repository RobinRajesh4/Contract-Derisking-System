import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { RiskBadge } from "@/components/RiskBadge";
import {
  FileText,
  Calendar,
  Scan,
} from "lucide-react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { listAnalyses } from "@/services/analysis";
import {
  useState,
  useMemo,
} from "react";
import {
  AnalysisFilters,
  DEFAULT_FILTERS,
  applyAnalysisFilters,
  collectDomains,
} from "@/components/AnalysisFilters";

export default function Analyses() {
  const {
    data,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["analyses"],
    queryFn: () => listAnalyses(),
  });

  const [filters, setFilters] =
    useState(DEFAULT_FILTERS);

  const allAnalyses =
    (data as any[] | undefined) || [];

  const domains = useMemo(
    () => collectDomains(allAnalyses),
    [allAnalyses]
  );

  // Filter and search analyses
  // using shared logic with Insights page.
  const analyses = useMemo(
    () =>
      applyAnalysisFilters(
        allAnalyses,
        filters
      ),
    [allAnalyses, filters]
  );

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">
          Contract Analyses
        </h1>

        <p className="text-muted-foreground">
          View and manage completed contract
          risk analyses
        </p>
      </div>

      {/* Search and Filter Controls */}
      <AnalysisFilters
        filters={filters}
        onChange={setFilters}
        domains={domains}
      />

      {isLoading ? (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            Loading analyses...
          </CardContent>
        </Card>
      ) : isError ? (
        <Card>
          <CardContent className="py-12 text-center text-destructive">
            Failed to load analyses
          </CardContent>
        </Card>
      ) : analyses.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <FileText className="h-12 w-12 text-muted-foreground mb-4" />

            <h3 className="text-lg font-semibold mb-2">
              No analyses yet
            </h3>

            <p className="text-sm text-muted-foreground text-center max-w-sm">
              Upload a contract to get started
              with automated risk analysis
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4">
          {analyses.map((a: any) => {
            const name =
              a.filename ||
              `Analysis ${a.analysis_id?.slice(
                0,
                8
              )}`;

            const dateStr =
              a.updated_at ||
              a.created_at ||
              new Date().toISOString();

            const results =
              a.results ||
              a.clauses ||
              [];

            const highRiskCount =
              results.filter(
                (r: any) =>
                  (
                    r.classification
                      ?.risk_level || ""
                  ).toLowerCase() === "high"
              ).length;

            const overall:
              | "high"
              | "medium"
              | "low" =
              highRiskCount > 0
                ? "high"
                : results.length > 0
                  ? "medium"
                  : "low";

            return (
              <Link
                to={`/analyses/${a.analysis_id}`}
                key={a.analysis_id}
                className="block"
              >
                <Card className="hover:shadow-md transition-shadow cursor-pointer">
                  <CardHeader>
                    <div className="flex items-start justify-between">
                      <div className="space-y-1 flex-1">
                        <CardTitle className="flex items-center gap-2">
                          <FileText className="h-5 w-5" />
                          {name}
                        </CardTitle>

                        <CardDescription className="flex items-center gap-2">
                          <Calendar className="h-4 w-4" />
                          Updated on{" "}
                          {new Date(
                            dateStr
                          ).toLocaleDateString()}
                        </CardDescription>
                      </div>

                      <RiskBadge
                        level={overall}
                      />
                    </div>
                  </CardHeader>

                  <CardContent>
                    <div className="flex gap-4 text-sm flex-wrap">
                      <div>
                        <span className="text-muted-foreground">
                          Clauses Analyzed:
                        </span>

                        <span className="ml-2 font-medium">
                          {results.length}
                        </span>
                      </div>

                      <div>
                        <span className="text-muted-foreground">
                          High Risk Found:
                        </span>

                        <Badge
                          variant="destructive"
                          className="ml-2"
                        >
                          {highRiskCount}
                        </Badge>
                      </div>

                      {a.ocr_info?.used && (
                        <div className="flex items-center gap-1">
                          <Scan className="h-4 w-4 text-purple-600" />

                          <span className="text-xs text-purple-600 font-medium">
                            OCR Extracted
                          </span>
                        </div>
                      )}
                    </div>
                  </CardContent>
                </Card>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}