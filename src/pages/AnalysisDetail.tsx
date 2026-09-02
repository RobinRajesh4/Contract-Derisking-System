import { useParams } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import {
  getAnalysis,
  getSummary,
  ContractSummary,
} from "@/services/analysis";
import { apiFetch } from "@/services/api";
import { useState } from "react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  Alert,
  AlertDescription,
} from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import {
  uiPolicies,
  uiLabels,
} from "@/policy/policyLibrary";
import {
  FileText,
  AlertTriangle,
  CheckCircle2,
  Clock,
  HardDrive,
  Shield,
  Scale,
  DollarSign,
  Lock,
  Info,
  Download,
  Lightbulb,
  Loader2,
  Scan,
  FileImage,
  Sparkles,
  ListChecks,
  Flag,
  ThumbsUp,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "@/hooks/use-toast";

export default function AnalysisDetail() {
  const { id } = useParams<{ id: string }>();

  const {
    data,
    isLoading,
    isError,
    error,
  } = useQuery({
    queryKey: ["analysis", id],
    queryFn: () =>
      getAnalysis(id as string),
    enabled: !!id,
  });

  const [
    recommendations,
    setRecommendations,
  ] = useState<Record<number, string>>({});

  const [
    loadingRec,
    setLoadingRec,
  ] = useState<Record<number, boolean>>({});

  const [summary, setSummary] =
    useState<ContractSummary | null>(null);

  const summaryMutation = useMutation({
    mutationFn: () =>
      getSummary(id as string),

    onSuccess: (data) => {
      setSummary(data);

      toast({
        title: "Summary generated",
        description:
          "AI executive summary is ready.",
      });
    },

    onError: (err: any) => {
      toast({
        title: "Error",
        description:
          err?.message ||
          "Failed to generate summary.",
        variant: "destructive",
      });
    },
  });

  const recommendMutation = useMutation({
    mutationFn: async (payload: {
      text: string;
      risk_level: string;
      reasons: string[];
      clauseId: number;
    }) => {
      const result = await apiFetch<{
        recommendation: string | null;
      }>("/recommend", {
        method: "POST",
        headers: {
          "Content-Type":
            "application/json",
        },
        body: JSON.stringify({
          text: payload.text,
          risk_level:
            payload.risk_level,
          reasons: payload.reasons,
        }),
      });

      return {
        ...result,
        clauseId: payload.clauseId,
      };
    },

    onSuccess: (data) => {
      if (data.recommendation) {
        setRecommendations((prev) => ({
          ...prev,
          [data.clauseId]:
            data.recommendation!,
        }));

        toast({
          title:
            "Recommendation generated",
          description:
            "Alternative wording has been suggested.",
        });
      } else {
        toast({
          title: "No recommendation",
          description:
            "Could not generate a recommendation for this clause.",
          variant: "destructive",
        });
      }

      setLoadingRec((prev) => ({
        ...prev,
        [data.clauseId]: false,
      }));
    },

    onError: () => {
      toast({
        title: "Error",
        description:
          "Failed to generate recommendation.",
        variant: "destructive",
      });
    },
  });

  if (!id) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-destructive">
          Missing analysis id
        </CardContent>
      </Card>
    );
  }

  if (isLoading) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-muted-foreground">
          Loading analysis...
        </CardContent>
      </Card>
    );
  }

  if (isError) {
    return (
      <Card>
        <CardContent className="py-12 text-center text-destructive">
          {(error as any)?.message ||
            "Failed to load analysis"}
        </CardContent>
      </Card>
    );
  }

  const a: any = data || {};

  const results: any[] =
    a.results || a.clauses || [];

  const highRiskCount =
    results.filter(
      (r) =>
        (
          r.classification
            ?.risk_level || ""
        ).toLowerCase() === "high"
    ).length;

  const mediumRiskCount =
    results.filter(
      (r) =>
        (
          r.classification
            ?.risk_level || ""
        ).toLowerCase() === "medium"
    ).length;

  const lowRiskCount =
    results.filter(
      (r) =>
        (
          r.classification
            ?.risk_level || ""
        ).toLowerCase() === "low"
    ).length;

  const createdAt = a.created_at
    ? new Date(a.created_at)
    : null;

  const fileSizeBytes =
    typeof a.file_size === "number" &&
    a.file_size >= 0
      ? a.file_size
      : null;

  const formatSize = (
    bytes: number | null
  ) => {
    if (bytes === null) return null;

    const mb =
      bytes / 1024 / 1024;

    if (mb >= 0.01) {
      return `${mb.toFixed(2)} MB`;
    }

    const kb = bytes / 1024;

    if (kb >= 1) {
      return `${kb.toFixed(0)} KB`;
    }

    return `${bytes} B`;
  };

  const policyNameMap: Record<
    string,
    string
  > = Object.fromEntries(
    uiPolicies.map((p) => [
      p.id,
      p.name,
    ])
  );

  const policyRiskLevelMap: Record<
    string,
    "high" | "medium" | "low"
  > = Object.fromEntries(
    uiPolicies.map((p) => [
      p.id,
      p.riskLevel,
    ])
  );

  const weightForLevel = (
    lvl: "high" | "medium" | "low"
  ): number =>
    lvl === "high"
      ? 5
      : lvl === "medium"
        ? 3
        : 1;

  // Map policy id to the first label color that references it; fallback color if none
  const policyColorMap: Record<
    string,
    string
  > = (() => {
    const map: Record<
      string,
      string
    > = {};

    uiLabels.forEach((l) => {
      l.policyIds.forEach((pid) => {
        if (!map[pid]) {
          map[pid] = l.color;
        }
      });
    });

    return map;
  })();

  const getRiskBadge = (
    risk: string
  ) => {
    const riskLower = (
      risk || ""
    ).toLowerCase();

    if (riskLower === "high") {
      return (
        <Badge
          variant="destructive"
          className="gap-1"
        >
          <AlertTriangle className="h-3 w-3" />
          High
        </Badge>
      );
    }

    if (riskLower === "medium") {
      return (
        <Badge
          variant="default"
          className="gap-1 bg-yellow-500 hover:bg-yellow-600"
        >
          <AlertTriangle className="h-3 w-3" />
          Medium
        </Badge>
      );
    }

    if (riskLower === "low") {
      return (
        <Badge
          variant="secondary"
          className="gap-1"
        >
          <CheckCircle2 className="h-3 w-3" />
          Low
        </Badge>
      );
    }

    return (
      <Badge variant="outline">
        {risk}
      </Badge>
    );
  };

  const getDomainIcon = (
    domain: string
  ) => {
    const domainLower = (
      domain || ""
    ).toLowerCase();

    if (
      domainLower.includes(
        "operational"
      )
    ) {
      return (
        <Shield className="h-4 w-4" />
      );
    }

    if (
      domainLower.includes(
        "financial"
      )
    ) {
      return (
        <DollarSign className="h-4 w-4" />
      );
    }

    if (
      domainLower.includes(
        "confidential"
      )
    ) {
      return (
        <Lock className="h-4 w-4" />
      );
    }

    if (
      domainLower.includes("other")
    ) {
      return (
        <Info className="h-4 w-4" />
      );
    }

    return (
      <Scale className="h-4 w-4" />
    );
  };

  const generateProperTitle = (
    clause: any,
    index: number
  ): string => {
    // If there's already a proper title, use it
    if (
      clause.title &&
      clause.title.length > 50
    ) {
      return clause.title;
    }

    const text = (
      clause.text || ""
    ).toLowerCase();

    const domain = (
      clause.classification?.domain ||
      clause.metadata?.domain ||
      ""
    ).toLowerCase();

    // Detect common clause patterns and generate appropriate titles
    if (
      text.includes(
        "service provider"
      ) ||
      text.includes(
        "provider agrees"
      ) ||
      text.includes(
        "provider shall"
      )
    ) {
      if (
        text.includes("consulting")
      ) {
        return "Service Provider Obligations";
      }

      if (text.includes("scope")) {
        return "Scope of Services";
      }

      return "Provider Responsibilities";
    }

    if (
      text.includes("payment") ||
      text.includes("pay") ||
      text.includes("fee")
    ) {
      if (
        text.includes("schedule")
      ) {
        return "Payment Schedule";
      }

      if (
        text.includes(
          "client shall"
        ) ||
        text.includes(
          "client will"
        )
      ) {
        return "Payment Terms";
      }

      if (
        text.includes("invoice")
      ) {
        return "Invoicing and Payment";
      }

      return "Payment Obligations";
    }

    if (
      text.includes("confidential")
    ) {
      if (
        text.includes("disclose")
      ) {
        return "Confidentiality and Disclosure";
      }

      if (
        text.includes(
          "both parties"
        )
      ) {
        return "Mutual Confidentiality";
      }

      return "Confidentiality Obligations";
    }

    if (
      text.includes("liability") ||
      text.includes("liable")
    ) {
      if (
        text.includes(
          "not liable"
        ) ||
        text.includes(
          "not responsible"
        )
      ) {
        return "Limitation of Liability";
      }

      return "Liability Provisions";
    }

    if (
      text.includes(
        "governing law"
      ) ||
      text.includes(
        "jurisdiction"
      )
    ) {
      return "Governing Law and Jurisdiction";
    }

    if (
      text.includes("termination") ||
      text.includes("terminate")
    ) {
      return "Termination Conditions";
    }

    if (
      text.includes(
        "intellectual property"
      ) ||
      text.includes("copyright")
    ) {
      return "Intellectual Property Rights";
    }

    if (
      text.includes("warranty") ||
      text.includes("guarantee")
    ) {
      return "Warranties and Guarantees";
    }

    if (
      text.includes("dispute") ||
      text.includes("arbitration")
    ) {
      return "Dispute Resolution";
    }

    // Domain-based fallback titles
    if (
      domain.includes("operational")
    ) {
      return `Operational Clause ${index + 1}`;
    }

    if (
      domain.includes("financial")
    ) {
      return `Financial Clause ${index + 1}`;
    }

    if (
      domain.includes(
        "confidential"
      )
    ) {
      return `Confidentiality Clause ${index + 1}`;
    }

    // Default fallback
    return `Clause ${index + 1}`;
  };

  const exportAsJSON = () => {
    const exportData = {
      analysis_id: a.analysis_id,
      filename: a.filename,
      created_at: a.created_at,
      updated_at: a.updated_at,
      file_size: a.file_size,
      total_clauses: results.length,
      risk_summary: {
        high: highRiskCount,
        medium: mediumRiskCount,
        low: lowRiskCount,
      },
      policy_summary:
        a.policy_summary,
      clauses: results,
    };

    const blob = new Blob(
      [
        JSON.stringify(
          exportData,
          null,
          2
        ),
      ],
      {
        type: "application/json",
      }
    );

    const url =
      URL.createObjectURL(blob);

    const link =
      document.createElement("a");

    link.href = url;
    link.download = `analysis-${a.filename || a.analysis_id}.json`;

    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    URL.revokeObjectURL(url);
  };

  const exportAsCSV = () => {
    const csvRows = [
      [
        "Clause ID",
        "Title",
        "Domain",
        "Risk Level",
        "Reasons",
        "Text",
      ].join(","),

      ...results.map(
        (c: any, idx: number) => {
          const title =
            generateProperTitle(
              c,
              idx
            ).replace(/,/g, ";");

          const domain = (
            c.classification
              ?.domain || "Unknown"
          ).replace(/,/g, ";");

          const risk = (
            c.classification
              ?.risk_level ||
            "Unknown"
          ).replace(/,/g, ";");

          const reasons = (
            c.classification
              ?.reasons || []
          )
            .join("; ")
            .replace(/,/g, ";");

          const text = (
            c.text || ""
          )
            .replace(/,/g, ";")
            .replace(/\n/g, " ");

          return [
            c.id,
            `"${title}"`,
            domain,
            risk,
            `"${reasons}"`,
            `"${text}"`,
          ].join(",");
        }
      ),
    ];

    const blob = new Blob(
      [csvRows.join("\n")],
      {
        type: "text/csv",
      }
    );

    const url =
      URL.createObjectURL(blob);

    const link =
      document.createElement("a");

    link.href = url;
    link.download = `analysis-${a.filename || a.analysis_id}.csv`;

    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="space-y-2">
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <FileText className="h-8 w-8 text-primary" />

            <div>
              <h1 className="text-3xl font-bold tracking-tight">
                Contract Analysis
              </h1>

              <p className="text-muted-foreground mt-1">
                {a.filename ||
                  a.analysis_id}
              </p>
            </div>
          </div>

          <div className="flex gap-2">
            <Button
              onClick={exportAsJSON}
              variant="outline"
              size="sm"
              className="gap-2"
            >
              <Download className="h-4 w-4" />
              Export JSON
            </Button>

            <Button
              onClick={exportAsCSV}
              variant="outline"
              size="sm"
              className="gap-2"
            >
              <Download className="h-4 w-4" />
              Export CSV
            </Button>
          </div>
        </div>
      </div>

      {/* Summary Card */}
      <Card className="border-2">
        <CardHeader className="pb-3">
          <CardTitle className="text-xl">
            Analysis Summary
          </CardTitle>

          <CardDescription>
            Comprehensive risk
            assessment of{" "}
            {results.length}{" "}
            {results.length === 1
              ? "clause"
              : "clauses"}
          </CardDescription>
        </CardHeader>

        <CardContent className="space-y-4">
          {/* Risk Overview */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="flex items-center gap-3 p-3 rounded-lg bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-900">
              <AlertTriangle className="h-8 w-8 text-red-600" />

              <div>
                <p className="text-2xl font-bold text-red-600">
                  {highRiskCount}
                </p>
                <p className="text-sm text-muted-foreground">
                  High Risk
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3 p-3 rounded-lg bg-yellow-50 dark:bg-yellow-950/20 border border-yellow-200 dark:border-yellow-900">
              <AlertTriangle className="h-8 w-8 text-yellow-600" />

              <div>
                <p className="text-2xl font-bold text-yellow-600">
                  {mediumRiskCount}
                </p>
                <p className="text-sm text-muted-foreground">
                  Medium Risk
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3 p-3 rounded-lg bg-green-50 dark:bg-green-950/20 border border-green-200 dark:border-green-900">
              <CheckCircle2 className="h-8 w-8 text-green-600" />

              <div>
                <p className="text-2xl font-bold text-green-600">
                  {lowRiskCount}
                </p>
                <p className="text-sm text-muted-foreground">
                  Low Risk
                </p>
              </div>
            </div>
          </div>

          <Separator />

          {/* Document Details */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="flex items-center gap-2 text-sm">
              <FileText className="h-4 w-4 text-muted-foreground" />
              <span className="text-muted-foreground">
                File:
              </span>
              <span className="font-medium">
                {a.filename ||
                  a.analysis_id}
              </span>
            </div>

            {createdAt && (
              <div className="flex items-center gap-2 text-sm">
                <Clock className="h-4 w-4 text-muted-foreground" />
                <span className="text-muted-foreground">
                  Submitted:
                </span>
                <span className="font-medium">
                  {createdAt.toLocaleString()}
                </span>
              </div>
            )}

            {fileSizeBytes !== null && (
              <div className="flex items-center gap-2 text-sm">
                <HardDrive className="h-4 w-4 text-muted-foreground" />
                <span className="text-muted-foreground">
                  File size:
                </span>
                <span className="font-medium">
                  {formatSize(
                    fileSizeBytes
                  )}
                </span>
              </div>
            )}

            {a.ocr_info &&
              a.ocr_info.used && (
                <div className="flex items-center gap-2 text-sm">
                  <Scan className="h-4 w-4 text-purple-500" />
                  <span className="text-muted-foreground">
                    Extraction:
                  </span>
                  <Badge
                    variant="outline"
                    className="gap-1 border-purple-500 text-purple-700"
                  >
                    <FileImage className="h-3 w-3" />
                    {a.ocr_info.method}
                  </Badge>
                </div>
              )}

            {a.ocr_info &&
              a.ocr_info.used && (
                <div className="flex items-center gap-2 text-sm">
                  <Info className="h-4 w-4 text-muted-foreground" />
                  <span className="text-muted-foreground">
                    OCR Pages:
                  </span>
                  <span className="font-medium">
                    {a.ocr_info.pages}{" "}
                    page(s),{" "}
                    {
                      a.ocr_info
                        .characters
                    }{" "}
                    characters
                  </span>
                </div>
              )}
          </div>

          {/* Policy Summary */}
          {a.policy_summary && (
            <>
              <Separator />

              <div className="space-y-2">
                <h3 className="font-semibold flex items-center gap-2">
                  <Shield className="h-4 w-4" />
                  Policy Compliance
                </h3>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div className="flex items-center gap-2 text-sm">
                    <span className="text-muted-foreground">
                      Total Policy Score:
                    </span>

                    <span className="font-bold text-lg">
                      {
                        a.policy_summary
                          .total_policy_score
                      }
                    </span>
                  </div>

                  <div className="flex items-center gap-2 text-sm">
                    <span className="text-muted-foreground">
                      Above Threshold:
                    </span>

                    <Badge
                      variant={
                        a.policy_summary
                          .is_above_threshold
                          ? "destructive"
                          : "secondary"
                      }
                      className="gap-1"
                    >
                      {a.policy_summary
                        .is_above_threshold ? (
                        <>
                          <AlertTriangle className="h-3 w-3" />
                          Yes
                        </>
                      ) : (
                        <>
                          <CheckCircle2 className="h-3 w-3" />
                          No
                        </>
                      )}
                    </Badge>
                  </div>
                </div>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* AI Executive Summary */}
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <Sparkles className="h-5 w-5" />
              AI Executive Summary
            </CardTitle>

            <Button
              size="sm"
              variant={
                summary
                  ? "outline"
                  : "default"
              }
              onClick={() =>
                summaryMutation.mutate()
              }
              disabled={
                summaryMutation.isPending
              }
            >
              {summaryMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Sparkles className="h-4 w-4" />
              )}

              {summary
                ? "Regenerate"
                : "Generate Summary"}
            </Button>
          </div>

          <CardDescription>
            AI-generated overview of
            obligations, major risks, and
            recommendations for this
            contract
          </CardDescription>
        </CardHeader>

        {summary && (
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between gap-4 flex-wrap">
              {summary.executive_summary && (
                <p className="text-sm leading-relaxed flex-1 min-w-[200px]">
                  {
                    summary.executive_summary
                  }
                </p>
              )}

              {summary.overall_sentiment && (
                <Badge
                  variant={
                    summary.overall_sentiment ===
                    "Favorable"
                      ? "secondary"
                      : summary.overall_sentiment ===
                          "Unfavorable"
                        ? "destructive"
                        : "outline"
                  }
                  className="shrink-0"
                >
                  {
                    summary.overall_sentiment
                  }
                </Badge>
              )}
            </div>

            <div className="grid gap-4 md:grid-cols-3">
              {summary.key_obligations &&
                summary.key_obligations
                  .length > 0 && (
                  <div className="space-y-2">
                    <h4 className="text-sm font-semibold flex items-center gap-1">
                      <ListChecks className="h-4 w-4" />
                      Key Obligations
                    </h4>

                    <ul className="text-sm text-muted-foreground list-disc list-inside space-y-1">
                      {summary.key_obligations.map(
                        (item, i) => (
                          <li key={i}>
                            {item}
                          </li>
                        )
                      )}
                    </ul>
                  </div>
                )}

              {summary.major_risks &&
                summary.major_risks
                  .length > 0 && (
                  <div className="space-y-2">
                    <h4 className="text-sm font-semibold flex items-center gap-1 text-destructive">
                      <Flag className="h-4 w-4" />
                      Major Risks
                    </h4>

                    <ul className="text-sm text-muted-foreground list-disc list-inside space-y-1">
                      {summary.major_risks.map(
                        (item, i) => (
                          <li key={i}>
                            {item}
                          </li>
                        )
                      )}
                    </ul>
                  </div>
                )}

              {summary.recommendations &&
                summary.recommendations
                  .length > 0 && (
                  <div className="space-y-2">
                    <h4 className="text-sm font-semibold flex items-center gap-1">
                      <ThumbsUp className="h-4 w-4" />
                      Recommendations
                    </h4>

                    <ul className="text-sm text-muted-foreground list-disc list-inside space-y-1">
                      {summary.recommendations.map(
                        (item, i) => (
                          <li key={i}>
                            {item}
                          </li>
                        )
                      )}
                    </ul>
                  </div>
                )}
            </div>
          </CardContent>
        )}
      </Card>

      {/* Clauses Section */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <h2 className="text-2xl font-bold">
            Clause Details
          </h2>

          <Badge
            variant="outline"
            className="text-base"
          >
            {results.length}
          </Badge>
        </div>

        <div className="grid gap-4">
          {results.map(
            (
              c: any,
              index: number
            ) => {
              const domain =
                c.classification?.domain ||
                c.metadata?.domain ||
                "Other";

              const riskLevel =
                c.classification
                  ?.risk_level ||
                "Unknown";

              const riskLower =
                riskLevel.toLowerCase();

              return (
                <Card
                  key={c.id}
                  className={`transition-all hover:shadow-md ${
                    riskLower === "high"
                      ? "border-l-4 border-l-red-500"
                      : riskLower ===
                          "medium"
                        ? "border-l-4 border-l-yellow-500"
                        : riskLower ===
                            "low"
                          ? "border-l-4 border-l-green-500"
                          : ""
                  }`}
                >
                  <CardHeader className="pb-3">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1">
                        <CardTitle className="text-lg flex items-center gap-2">
                          {getDomainIcon(
                            domain
                          )}
                          {generateProperTitle(
                            c,
                            index
                          )}
                        </CardTitle>

                        <CardDescription className="mt-1.5 flex items-center gap-2">
                          <Badge
                            variant="outline"
                            className="gap-1"
                          >
                            {getDomainIcon(
                              domain
                            )}
                            {domain}
                          </Badge>

                          {getRiskBadge(
                            riskLevel
                          )}
                        </CardDescription>
                      </div>
                    </div>
                  </CardHeader>

                  <CardContent className="space-y-4">
                    {/* Clause Text */}
                    <div className="rounded-lg bg-muted/50 p-4">
                      <p className="text-sm leading-relaxed whitespace-pre-wrap">
                        {c.text}
                      </p>
                    </div>

                    {/* Risk Reasons */}
                    {c.classification
                      ?.reasons &&
                      c.classification
                        .reasons.length >
                        0 && (
                        <Alert>
                          <Info className="h-4 w-4" />

                          <AlertDescription>
                            <span className="font-semibold">
                              Risk Factors:{" "}
                            </span>

                            {c.classification.reasons.join(
                              "; "
                            )}
                          </AlertDescription>
                        </Alert>
                      )}

                    {/* Policy Information */}
                    {c.policy &&
                      (c.policy
                        .violations
                        ?.length > 0 ||
                        c.policy
                          .matched_policies
                          ?.length >
                          0) && (
                        <div className="space-y-2">
                          <Separator />

                          <div>
                            <h4 className="text-sm font-semibold mb-2 flex items-center gap-2">
                              <Shield className="h-4 w-4" />
                              Policy Assessment
                            </h4>

                            <div className="flex flex-wrap gap-2">
                              {(
                                c.policy
                                  .violations ||
                                []
                              ).map(
                                (
                                  v: any
                                ) => (
                                  <Badge
                                    key={
                                      v.id
                                    }
                                    variant="destructive"
                                    className="gap-1"
                                  >
                                    <AlertTriangle className="h-3 w-3" />
                                    {v.name ||
                                      v.id}{" "}
                                    (
                                    {
                                      v.risk_weight
                                    }
                                    )
                                  </Badge>
                                )
                              )}

                              {(
                                c.policy
                                  .matched_policies ||
                                []
                              ).map(
                                (
                                  m: any
                                ) => {
                                  const name =
                                    policyNameMap[
                                      m
                                    ] ||
                                    m;

                                  const color =
                                    policyColorMap[
                                      m
                                    ] ||
                                    "#64748b";

                                  const lvl =
                                    policyRiskLevelMap[
                                      m
                                    ] ||
                                    "medium";

                                  const w =
                                    weightForLevel(
                                      lvl
                                    );

                                  return (
                                    <span
                                      key={
                                        m
                                      }
                                      className="inline-flex items-center rounded-full px-3 py-1 text-xs font-medium shadow-sm"
                                      style={{
                                        backgroundColor:
                                          color,
                                        color:
                                          "#fff",
                                      }}
                                    >
                                      {name}{" "}
                                      ({w})
                                    </span>
                                  );
                                }
                              )}
                            </div>
                          </div>
                        </div>
                      )}

                    {/* Recommendation for High Risk Clauses */}
                    {riskLower ===
                      "high" && (
                      <div className="space-y-2">
                        <Separator />

                        <div className="flex items-center justify-between">
                          <h4 className="text-sm font-semibold flex items-center gap-2">
                            <Lightbulb className="h-4 w-4 text-amber-500" />
                            Alternative Wording
                            Suggestion
                          </h4>

                          {!recommendations[
                            c.id
                          ] && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => {
                                setLoadingRec(
                                  (
                                    prev
                                  ) => ({
                                    ...prev,
                                    [c.id]:
                                      true,
                                  })
                                );

                                recommendMutation.mutate(
                                  {
                                    text: c.text,
                                    risk_level:
                                      riskLevel,
                                    reasons:
                                      c
                                        .classification
                                        ?.reasons ||
                                      [],
                                    clauseId:
                                      c.id,
                                  }
                                );
                              }}
                              disabled={
                                loadingRec[
                                  c.id
                                ]
                              }
                              className="gap-2"
                            >
                              {loadingRec[
                                c.id
                              ] ? (
                                <>
                                  <Loader2 className="h-3 w-3 animate-spin" />
                                  Generating...
                                </>
                              ) : (
                                <>
                                  <Lightbulb className="h-3 w-3" />
                                  Get Suggestion
                                </>
                              )}
                            </Button>
                          )}
                        </div>

                        {recommendations[
                          c.id
                        ] && (
                          <Alert className="bg-amber-50 dark:bg-amber-950/20 border-amber-200 dark:border-amber-900">
                            <Lightbulb className="h-4 w-4 text-amber-600" />

                            <AlertDescription className="text-sm">
                              <span className="font-semibold text-amber-900 dark:text-amber-100">
                                Recommended
                                Alternative:
                              </span>

                              <p className="mt-2 text-amber-800 dark:text-amber-200 leading-relaxed">
                                {
                                  recommendations[
                                    c.id
                                  ]
                                }
                              </p>
                            </AlertDescription>
                          </Alert>
                        )}
                      </div>
                    )}
                  </CardContent>
                </Card>
              );
            }
          )}
        </div>
      </div>
    </div>
  );
}