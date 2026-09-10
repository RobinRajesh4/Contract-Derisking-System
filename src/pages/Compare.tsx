import {
  useEffect,
  useState,
} from "react";
import {
  useSearchParams,
} from "react-router-dom";
import {
  useMutation,
  useQuery,
} from "@tanstack/react-query";
import {
  AlertTriangle,
  CalendarDays,
  CheckCircle2,
  Clock,
  DollarSign,
  FileWarning,
  Gavel,
  GitCompare,
  Loader2,
  RefreshCw,
  Scale,
  ShieldAlert,
  ShieldCheck,
  Timer,
} from "lucide-react";

import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  compareAnalyses,
  CompareResult,
  ContractRiskStats,
  listAnalyses,
} from "@/services/analysis";
import { toast } from "@/hooks/use-toast";

interface ContractPanelProps {
  label: string;
  stats: ContractRiskStats;
}

function ContractPanel({
  label,
  stats,
}: ContractPanelProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="truncate text-lg">
          {label}
        </CardTitle>

        <CardDescription>
          {stats.total_clauses} clauses,{" "}
          {stats.classified_clauses} classified
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-5">
        <div>
          <div className="mb-2 flex items-center justify-between">
            <span className="text-sm text-muted-foreground">
              Normalized risk score
            </span>

            <span className="text-2xl font-bold">
              {stats.normalized_risk_score.toFixed(2)}
              <span className="text-sm font-normal text-muted-foreground">
                {" "}
                / 5
              </span>
            </span>
          </div>

          <Progress
            value={
              (stats.normalized_risk_score / 5) *
              100
            }
          />
        </div>

        <div className="grid grid-cols-3 gap-3 text-center">
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 dark:border-red-900 dark:bg-red-950/20">
            <p className="text-xl font-bold text-red-600">
              {stats.high_risk}
            </p>

            <p className="text-xs text-muted-foreground">
              High
            </p>

            <p className="mt-1 text-xs font-medium text-red-600">
              {stats.high_risk_percentage.toFixed(1)}%
            </p>
          </div>

          <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-3 dark:border-yellow-900 dark:bg-yellow-950/20">
            <p className="text-xl font-bold text-yellow-600">
              {stats.medium_risk}
            </p>

            <p className="text-xs text-muted-foreground">
              Medium
            </p>

            <p className="mt-1 text-xs font-medium text-yellow-600">
              {stats.medium_risk_percentage.toFixed(1)}%
            </p>
          </div>

          <div className="rounded-lg border border-green-200 bg-green-50 p-3 dark:border-green-900 dark:bg-green-950/20">
            <p className="text-xl font-bold text-green-600">
              {stats.low_risk}
            </p>

            <p className="text-xs text-muted-foreground">
              Low
            </p>

            <p className="mt-1 text-xs font-medium text-green-600">
              {stats.low_risk_percentage.toFixed(1)}%
            </p>
          </div>
        </div>

        {stats.unclassified_clauses > 0 && (
          <p className="text-xs text-muted-foreground">
            {stats.unclassified_clauses}{" "}
            unclassified clause
            {stats.unclassified_clauses !== 1
              ? "s"
              : ""}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function getTermIcon(
  termKey: string
) {
  if (termKey === "effective_date") {
    return (
      <CalendarDays className="h-4 w-4" />
    );
  }

  if (termKey === "contract_duration") {
    return (
      <Clock className="h-4 w-4" />
    );
  }

  if (termKey === "renewal_period") {
    return (
      <RefreshCw className="h-4 w-4" />
    );
  }

  if (termKey === "payment_period") {
    return (
      <DollarSign className="h-4 w-4" />
    );
  }

  if (termKey === "termination_notice") {
    return (
      <Timer className="h-4 w-4" />
    );
  }

  if (termKey === "liability_cap") {
    return (
      <ShieldAlert className="h-4 w-4" />
    );
  }

  if (
    termKey === "governing_law" ||
    termKey === "jurisdiction"
  ) {
    return (
      <Gavel className="h-4 w-4" />
    );
  }

  return (
    <FileWarning className="h-4 w-4" />
  );
}

export default function Compare() {
  const [searchParams] =
    useSearchParams();

  const { data } = useQuery({
    queryKey: ["analyses"],
    queryFn: () => listAnalyses(),
  });

  const analyses =
    (data as any[] | undefined) || [];

  const [idA, setIdA] =
    useState<string>(
      searchParams.get("a") || ""
    );

  const [idB, setIdB] =
    useState<string>(
      searchParams.get("b") || ""
    );

  const [result, setResult] =
    useState<CompareResult | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      compareAnalyses(idA, idB),

    onSuccess: (comparisonResult) => {
      setResult(comparisonResult);
    },

    onError: (error: any) => {
      toast({
        title: "Comparison failed",
        description:
          error?.message ||
          "Could not compare these contracts",
        variant: "destructive",
      });
    },
  });

  useEffect(() => {
    if (
      idA &&
      idB &&
      idA !== idB
    ) {
      mutation.mutate();
    }

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const nameFor = (
    analysisId: string
  ) => {
    const analysis = analyses.find(
      (item: any) =>
        item.analysis_id === analysisId
    );

    return (
      analysis?.filename ||
      `Analysis ${analysisId.slice(0, 8)}`
    );
  };

  const selectContractA = (
    value: string
  ) => {
    setIdA(value);
    setResult(null);
  };

  const selectContractB = (
    value: string
  ) => {
    setIdB(value);
    setResult(null);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">
          Compare Contracts
        </h1>

        <p className="text-muted-foreground">
          Compare normalized risk, key terms,
          clause distribution, and domain-level
          exposure
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <GitCompare className="h-5 w-5" />
            Select Contracts
          </CardTitle>

          <CardDescription>
            Select two previously analyzed
            contracts.
          </CardDescription>
        </CardHeader>

        <CardContent className="flex flex-col items-end gap-4 sm:flex-row">
          <div className="w-full flex-1">
            <label className="mb-1 block text-sm font-medium">
              Contract A
            </label>

            <Select
              value={idA}
              onValueChange={selectContractA}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select a contract" />
              </SelectTrigger>

              <SelectContent>
                {analyses.map(
                  (analysis: any) => (
                    <SelectItem
                      key={
                        analysis.analysis_id
                      }
                      value={
                        analysis.analysis_id
                      }
                      disabled={
                        analysis.analysis_id ===
                        idB
                      }
                    >
                      {analysis.filename ||
                        `Analysis ${analysis.analysis_id?.slice(
                          0,
                          8
                        )}`}
                    </SelectItem>
                  )
                )}
              </SelectContent>
            </Select>
          </div>

          <div className="w-full flex-1">
            <label className="mb-1 block text-sm font-medium">
              Contract B
            </label>

            <Select
              value={idB}
              onValueChange={selectContractB}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select a contract" />
              </SelectTrigger>

              <SelectContent>
                {analyses.map(
                  (analysis: any) => (
                    <SelectItem
                      key={
                        analysis.analysis_id
                      }
                      value={
                        analysis.analysis_id
                      }
                      disabled={
                        analysis.analysis_id ===
                        idA
                      }
                    >
                      {analysis.filename ||
                        `Analysis ${analysis.analysis_id?.slice(
                          0,
                          8
                        )}`}
                    </SelectItem>
                  )
                )}
              </SelectContent>
            </Select>
          </div>

          <Button
            onClick={() =>
              mutation.mutate()
            }
            disabled={
              !idA ||
              !idB ||
              idA === idB ||
              mutation.isPending
            }
            className="gap-2"
          >
            {mutation.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <GitCompare className="h-4 w-4" />
            )}

            Compare
          </Button>
        </CardContent>
      </Card>

      {idA && idB && idA === idB && (
        <p className="text-sm text-destructive">
          Select two different contracts.
        </p>
      )}

      {result && (
        <>
          <div className="grid gap-4 md:grid-cols-2">
            <ContractPanel
              label={nameFor(idA)}
              stats={result.contract_1}
            />

            <ContractPanel
              label={nameFor(idB)}
              stats={result.contract_2}
            />
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                {result.comparison.is_tie ? (
                  <Scale className="h-5 w-5" />
                ) : (
                  <ShieldCheck className="h-5 w-5" />
                )}

                Comparison Verdict
              </CardTitle>
            </CardHeader>

            <CardContent className="space-y-4">
              <div className="flex flex-wrap items-center gap-3">
                {result.comparison.is_tie ? (
                  <Badge variant="outline">
                    Equal risk result
                  </Badge>
                ) : (
                  <Badge variant="secondary">
                    Safer contract:{" "}
                    {nameFor(
                      result.comparison
                        .safer_contract as string
                    )}
                  </Badge>
                )}

                <span className="text-sm text-muted-foreground">
                  Normalized score difference:{" "}
                  {Math.abs(
                    result.comparison
                      .normalized_score_difference
                  ).toFixed(2)}
                </span>
              </div>

              <p className="text-sm font-medium">
                {result.comparison.verdict}
              </p>

              {result.comparison
                .verdict_reasons.length >
                0 && (
                <ul className="space-y-2 text-sm text-muted-foreground">
                  {result.comparison.verdict_reasons.map(
                    (reason, index) => (
                      <li
                        key={index}
                        className="flex items-start gap-2"
                      >
                        <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                        {reason}
                      </li>
                    )
                  )}
                </ul>
              )}

              <div className="grid gap-3 border-t pt-4 sm:grid-cols-3">
                <div>
                  <p className="text-xs text-muted-foreground">
                    Clause difference
                  </p>

                  <p className="font-semibold">
                    {
                      result.comparison
                        .clause_difference
                    }
                  </p>
                </div>

                <div>
                  <p className="text-xs text-muted-foreground">
                    High-risk count difference
                  </p>

                  <p className="font-semibold">
                    {
                      result.comparison
                        .high_risk_difference
                    }
                  </p>
                </div>

                <div>
                  <p className="text-xs text-muted-foreground">
                    High-risk rate difference
                  </p>

                  <p className="font-semibold">
                    {
                      result.comparison
                        .high_risk_rate_difference
                    }
                    %
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <FileWarning className="h-5 w-5" />
                Key Contract Terms
              </CardTitle>

              <CardDescription>
                Important values extracted from the
                analyzed contract clauses.
              </CardDescription>
            </CardHeader>

            <CardContent>
              {result.comparison.term_comparison
                .length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-left">
                        <th className="px-3 py-3 font-medium">
                          Term
                        </th>

                        <th className="px-3 py-3 font-medium">
                          {nameFor(idA)}
                        </th>

                        <th className="px-3 py-3 font-medium">
                          {nameFor(idB)}
                        </th>

                        <th className="px-3 py-3 font-medium">
                          Result
                        </th>
                      </tr>
                    </thead>

                    <tbody>
                      {result.comparison.term_comparison.map(
                        (term) => (
                          <tr
                            key={term.key}
                            className="border-b align-top last:border-0"
                          >
                            <td className="px-3 py-4">
                              <div className="flex items-center gap-2 font-medium">
                                {getTermIcon(
                                  term.key
                                )}

                                {term.label}
                              </div>
                            </td>

                            <td className="px-3 py-4">
                              {term.contract_1 ? (
                                <div className="space-y-1">
                                  <p className="font-medium">
                                    {
                                      term.contract_1
                                        .value
                                    }
                                  </p>

                                  {term.contract_1
                                    .clause_id !==
                                    undefined && (
                                    <p className="text-xs text-muted-foreground">
                                      Clause{" "}
                                      {
                                        term.contract_1
                                          .clause_id
                                      }
                                    </p>
                                  )}

                                  {term.contract_1
                                    .has_conflict && (
                                    <Badge variant="destructive">
                                      Conflicting values
                                    </Badge>
                                  )}
                                </div>
                              ) : (
                                <span className="text-muted-foreground">
                                  Not found
                                </span>
                              )}
                            </td>

                            <td className="px-3 py-4">
                              {term.contract_2 ? (
                                <div className="space-y-1">
                                  <p className="font-medium">
                                    {
                                      term.contract_2
                                        .value
                                    }
                                  </p>

                                  {term.contract_2
                                    .clause_id !==
                                    undefined && (
                                    <p className="text-xs text-muted-foreground">
                                      Clause{" "}
                                      {
                                        term.contract_2
                                          .clause_id
                                      }
                                    </p>
                                  )}

                                  {term.contract_2
                                    .has_conflict && (
                                    <Badge variant="destructive">
                                      Conflicting values
                                    </Badge>
                                  )}
                                </div>
                              ) : (
                                <span className="text-muted-foreground">
                                  Not found
                                </span>
                              )}
                            </td>

                            <td className="px-3 py-4">
                              {term.status ===
                                "same" && (
                                <Badge variant="secondary">
                                  Same
                                </Badge>
                              )}

                              {term.status ===
                                "different" && (
                                <Badge variant="destructive">
                                  Different
                                </Badge>
                              )}

                              {term.status ===
                                "only_contract_1" && (
                                <Badge variant="outline">
                                  Only in Contract A
                                </Badge>
                              )}

                              {term.status ===
                                "only_contract_2" && (
                                <Badge variant="outline">
                                  Only in Contract B
                                </Badge>
                              )}

                              {term.status ===
                                "missing_both" && (
                                <Badge variant="outline">
                                  Not detected
                                </Badge>
                              )}
                            </td>
                          </tr>
                        )
                      )}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="flex items-center justify-center gap-2 py-10 text-muted-foreground">
                  <AlertTriangle className="h-5 w-5" />
                  No structured contract terms were
                  detected.
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>
                Domain-Level Comparison
              </CardTitle>

              <CardDescription>
                Compare risk within each classified
                contract domain.
              </CardDescription>
            </CardHeader>

            <CardContent>
              {result.comparison
                .domain_comparison.length >
              0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b text-left">
                        <th className="px-3 py-3 font-medium">
                          Domain
                        </th>

                        <th className="px-3 py-3 font-medium">
                          {nameFor(idA)}
                        </th>

                        <th className="px-3 py-3 font-medium">
                          {nameFor(idB)}
                        </th>

                        <th className="px-3 py-3 font-medium">
                          Difference
                        </th>
                      </tr>
                    </thead>

                    <tbody>
                      {result.comparison.domain_comparison.map(
                        (domainResult) => (
                          <tr
                            key={
                              domainResult.domain
                            }
                            className="border-b last:border-0"
                          >
                            <td className="px-3 py-4 font-medium">
                              {
                                domainResult.domain
                              }
                            </td>

                            <td className="px-3 py-4">
                              <div className="space-y-1">
                                <p>
                                  Score:{" "}
                                  <strong>
                                    {domainResult.contract_1.normalized_risk_score.toFixed(
                                      2
                                    )}
                                  </strong>
                                </p>

                                <p className="text-xs text-muted-foreground">
                                  {
                                    domainResult
                                      .contract_1
                                      .high
                                  }{" "}
                                  high of{" "}
                                  {
                                    domainResult
                                      .contract_1
                                      .total
                                  }{" "}
                                  clauses
                                </p>
                              </div>
                            </td>

                            <td className="px-3 py-4">
                              <div className="space-y-1">
                                <p>
                                  Score:{" "}
                                  <strong>
                                    {domainResult.contract_2.normalized_risk_score.toFixed(
                                      2
                                    )}
                                  </strong>
                                </p>

                                <p className="text-xs text-muted-foreground">
                                  {
                                    domainResult
                                      .contract_2
                                      .high
                                  }{" "}
                                  high of{" "}
                                  {
                                    domainResult
                                      .contract_2
                                      .total
                                  }{" "}
                                  clauses
                                </p>
                              </div>
                            </td>

                            <td className="px-3 py-4">
                              <Badge
                                variant={
                                  domainResult.score_difference ===
                                  0
                                    ? "outline"
                                    : "secondary"
                                }
                              >
                                {domainResult.score_difference >
                                0
                                  ? "+"
                                  : ""}

                                {domainResult.score_difference.toFixed(
                                  2
                                )}
                              </Badge>
                            </td>
                          </tr>
                        )
                      )}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="flex items-center justify-center gap-2 py-10 text-muted-foreground">
                  <AlertTriangle className="h-5 w-5" />
                  No classified domain data is
                  available.
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}