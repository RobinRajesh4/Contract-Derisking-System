import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import {
  FileText,
  TrendingUp,
  GitCompare,
  Sparkles,
} from "lucide-react";
import { listAnalyses } from "@/services/analysis";
import {
  AnalysisFilters,
  AnalysisFilterState,
  DEFAULT_FILTERS,
  applyAnalysisFilters,
  collectDomains,
} from "@/components/AnalysisFilters";

export default function Insights() {
  const { data, isLoading } = useQuery({
    queryKey: ["analyses"],
    queryFn: () => listAnalyses(),
  });

  const [filters, setFilters] =
    useState<AnalysisFilterState>(
      DEFAULT_FILTERS
    );

  const allAnalyses =
    (data as any[] | undefined) || [];

  const domains = useMemo(
    () => collectDomains(allAnalyses),
    [allAnalyses]
  );

  const filtered = useMemo(
    () =>
      applyAnalysisFilters(
        allAnalyses,
        filters
      ),
    [allAnalyses, filters]
  );

  const trendData = useMemo(() => {
    const byDay: Record<
      string,
      {
        date: string;
        contracts: number;
        highRisk: number;
        totalClauses: number;
      }
    > = {};

    filtered.forEach((a: any) => {
      const dateStr =
        a.created_at || a.updated_at;

      if (!dateStr) return;

      const day = new Date(dateStr)
        .toISOString()
        .slice(0, 10);

      const results =
        a.results || a.clauses || [];

      const highRisk = results.filter(
        (r: any) =>
          (
            r.classification?.risk_level ||
            ""
          ).toLowerCase() === "high"
      ).length;

      if (!byDay[day]) {
        byDay[day] = {
          date: day,
          contracts: 0,
          highRisk: 0,
          totalClauses: 0,
        };
      }

      byDay[day].contracts += 1;
      byDay[day].highRisk += highRisk;
      byDay[day].totalClauses +=
        results.length;
    });

    return Object.values(byDay).sort(
      (a, b) =>
        a.date.localeCompare(b.date)
    );
  }, [filtered]);

  const stats = useMemo(() => {
    let totalClauses = 0;
    let high = 0;
    let medium = 0;
    let low = 0;

    filtered.forEach((a: any) => {
      const results =
        a.results || a.clauses || [];

      totalClauses += results.length;

      results.forEach((r: any) => {
        const risk = (
          r.classification?.risk_level ||
          ""
        ).toLowerCase();

        if (risk === "high") high++;
        else if (risk === "medium")
          medium++;
        else if (risk === "low") low++;
      });
    });

    return {
      totalClauses,
      high,
      medium,
      low,
      contracts: filtered.length,
    };
  }, [filtered]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">
          Insights
        </h1>
        <p className="text-muted-foreground">
          Trends, filters, and quick
          actions across your contract
          portfolio
        </p>
      </div>

      <AnalysisFilters
        filters={filters}
        onChange={setFilters}
        domains={domains}
      />

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">
              Matching Contracts
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {isLoading
                ? "..."
                : stats.contracts}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">
              Total Clauses
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">
              {isLoading
                ? "..."
                : stats.totalClauses}
            </div>
          </CardContent>
        </Card>

        <Card
          className={
            stats.high > 0
              ? "border-red-500 border-2"
              : ""
          }
        >
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">
              High Risk Clauses
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-red-600">
              {isLoading
                ? "..."
                : stats.high}
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium">
              Low Risk Clauses
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-green-600">
              {isLoading
                ? "..."
                : stats.low}
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingUp className="h-5 w-5" />
            Risk Trend Over Time
          </CardTitle>
          <CardDescription>
            Contracts uploaded and
            high-risk clauses found, by
            day (based on current filters)
          </CardDescription>
        </CardHeader>

        <CardContent>
          {trendData.length > 0 ? (
            <ResponsiveContainer
              width="100%"
              height={300}
            >
              <LineChart data={trendData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Line
                  type="monotone"
                  dataKey="contracts"
                  name="Contracts Uploaded"
                  stroke="#8b5cf6"
                  strokeWidth={2}
                />
                <Line
                  type="monotone"
                  dataKey="highRisk"
                  name="High Risk Clauses"
                  stroke="#ef4444"
                  strokeWidth={2}
                />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[300px] flex items-center justify-center text-muted-foreground">
              <p>
                No data matches the current
                filters.
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>
            Matching Contracts
          </CardTitle>
          <CardDescription>
            {filtered.length} contract
            {filtered.length !== 1
              ? "s"
              : ""}{" "}
            match your filters — jump to
            detail, generate a summary, or
            compare
          </CardDescription>
        </CardHeader>

        <CardContent>
          {filtered.length > 0 ? (
            <div className="space-y-3">
              {filtered.map((a: any) => {
                const results =
                  a.results ||
                  a.clauses ||
                  [];

                const highRisk =
                  results.filter(
                    (r: any) =>
                      (
                        r.classification
                          ?.risk_level ||
                        ""
                      ).toLowerCase() ===
                      "high"
                  ).length;

                const dateStr =
                  a.updated_at ||
                  a.created_at;

                return (
                  <div
                    key={a.analysis_id}
                    className="flex items-center justify-between p-3 rounded-lg border hover:bg-accent transition-colors"
                  >
                    <Link
                      to={`/analyses/${a.analysis_id}`}
                      className="flex items-center gap-3 flex-1 min-w-0"
                    >
                      <FileText className="h-5 w-5 text-muted-foreground shrink-0" />
                      <div className="min-w-0">
                        <p className="font-medium truncate">
                          {a.filename ||
                            `Analysis ${a.analysis_id?.slice(
                              0,
                              8
                            )}`}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          {dateStr
                            ? new Date(
                                dateStr
                              ).toLocaleDateString()
                            : "Unknown date"}{" "}
                          • {results.length}{" "}
                          clauses
                        </p>
                      </div>
                    </Link>

                    <div className="flex items-center gap-2 shrink-0">
                      <Badge
                        variant={
                          highRisk > 0
                            ? "destructive"
                            : "secondary"
                        }
                      >
                        {highRisk > 0
                          ? `${highRisk} High Risk`
                          : "Low Risk"}
                      </Badge>

                      <Button
                        asChild
                        variant="outline"
                        size="sm"
                      >
                        <Link
                          to={`/analyses/${a.analysis_id}`}
                        >
                          <Sparkles className="h-3.5 w-3.5" />
                          Summary
                        </Link>
                      </Button>

                      <Button
                        asChild
                        variant="outline"
                        size="sm"
                      >
                        <Link
                          to={`/compare?a=${a.analysis_id}`}
                        >
                          <GitCompare className="h-3.5 w-3.5" />
                          Compare
                        </Link>
                      </Button>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="text-center py-8 text-muted-foreground">
              <FileText className="h-12 w-12 mx-auto mb-2 opacity-50" />
              <p>
                No contracts match the
                current filters.
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}