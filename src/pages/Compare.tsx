import { useEffect, useState } from "react";
import {
  useSearchParams,
} from "react-router-dom";
import {
  useQuery,
  useMutation,
} from "@tanstack/react-query";
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
import {
  GitCompare,
  Loader2,
  ShieldCheck,
} from "lucide-react";
import {
  listAnalyses,
  compareAnalyses,
  CompareResult,
} from "@/services/analysis";
import { toast } from "@/hooks/use-toast";

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

    onSuccess: (data) =>
      setResult(data),

    onError: (err: any) =>
      toast({
        title: "Comparison failed",
        description:
          err?.message ||
          "Could not compare these contracts",
        variant: "destructive",
      }),
  });

  useEffect(() => {
    if (idA && idB && !result) {
      mutation.mutate();
    }

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const nameFor = (id: string) => {
    const a = analyses.find(
      (x: any) => x.analysis_id === id
    );

    return (
      a?.filename ||
      `Analysis ${id.slice(0, 8)}`
    );
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">
          Compare Contracts
        </h1>
        <p className="text-muted-foreground">
          Compare risk profiles between
          two analyzed contracts
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <GitCompare className="h-5 w-5" />
            Select Contracts
          </CardTitle>
        </CardHeader>

        <CardContent className="flex flex-col sm:flex-row gap-4 items-end">
          <div className="flex-1 w-full">
            <label className="text-sm font-medium mb-1 block">
              Contract A
            </label>

            <Select
              value={idA}
              onValueChange={setIdA}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select a contract" />
              </SelectTrigger>

              <SelectContent>
                {analyses.map((a: any) => (
                  <SelectItem
                    key={a.analysis_id}
                    value={a.analysis_id}
                  >
                    {a.filename ||
                      `Analysis ${a.analysis_id?.slice(
                        0,
                        8
                      )}`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex-1 w-full">
            <label className="text-sm font-medium mb-1 block">
              Contract B
            </label>

            <Select
              value={idB}
              onValueChange={setIdB}
            >
              <SelectTrigger>
                <SelectValue placeholder="Select a contract" />
              </SelectTrigger>

              <SelectContent>
                {analyses.map((a: any) => (
                  <SelectItem
                    key={a.analysis_id}
                    value={a.analysis_id}
                  >
                    {a.filename ||
                      `Analysis ${a.analysis_id?.slice(
                        0,
                        8
                      )}`}
                  </SelectItem>
                ))}
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
        <p className="text-sm text-muted-foreground">
          Select two different contracts
          to compare.
        </p>
      )}

      {result && (
        <div className="grid gap-4 md:grid-cols-2">
          {[
            {
              label: nameFor(idA),
              stats: result.contract_1,
            },
            {
              label: nameFor(idB),
              stats: result.contract_2,
            },
          ].map(
            ({ label, stats }, i) => (
              <Card key={i}>
                <CardHeader>
                  <CardTitle className="text-lg truncate">
                    {label}
                  </CardTitle>
                  <CardDescription>
                    {stats.total_clauses}{" "}
                    clauses analyzed
                  </CardDescription>
                </CardHeader>

                <CardContent className="grid grid-cols-3 gap-2 text-center">
                  <div>
                    <p className="text-xl font-bold text-red-600">
                      {stats.high_risk}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      High
                    </p>
                  </div>

                  <div>
                    <p className="text-xl font-bold text-yellow-600">
                      {stats.medium_risk}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Medium
                    </p>
                  </div>

                  <div>
                    <p className="text-xl font-bold text-green-600">
                      {stats.low_risk}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Low
                    </p>
                  </div>
                </CardContent>
              </Card>
            )
          )}

          <Card className="md:col-span-2">
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <ShieldCheck className="h-5 w-5" />
                Verdict
              </CardTitle>
            </CardHeader>

            <CardContent className="space-y-2">
              <p className="text-sm">
                Clause count difference:{" "}
                <span className="font-medium">
                  {
                    result.comparison
                      .clause_difference
                  }
                </span>
              </p>

              <p className="text-sm">
                High-risk clause difference:{" "}
                <span className="font-medium">
                  {
                    result.comparison
                      .risk_difference
                  }
                </span>
              </p>

              <div className="pt-2">
                <Badge
                  variant="secondary"
                  className="text-sm"
                >
                  Safer contract:{" "}
                  {nameFor(
                    result.comparison
                      .safer_contract
                  )}
                </Badge>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}