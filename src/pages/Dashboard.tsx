import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { AlertTriangle, CheckCircle2, FileText, Shield, TrendingUp, BarChart3, PieChart as PieChartIcon, Activity } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { listAnalyses } from "@/services/analysis";
import { uiPolicies } from "@/policy/policyLibrary";
import { PieChart, Pie, Cell, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";

export default function Dashboard() {
  const { data, isLoading } = useQuery({
    queryKey: ["analyses"],
    queryFn: () => listAnalyses(),
  });

  const analyses = (data as any[] | undefined) || [];
  
  // Calculate real statistics
  const totalContracts = analyses.length;
  const activePolicies = uiPolicies.length;
  
  let totalClauses = 0;
  let highRiskCount = 0;
  let mediumRiskCount = 0;
  let lowRiskCount = 0;
  const domainStats: Record<string, number> = {};
  const recentAnalyses = analyses.slice(0, 5);
  
  analyses.forEach((a: any) => {
    const results = a.results || a.clauses || [];
    totalClauses += results.length;
    results.forEach((r: any) => {
      const risk = (r.classification?.risk_level || "").toLowerCase();
      if (risk === "high") highRiskCount++;
      else if (risk === "medium") mediumRiskCount++;
      else if (risk === "low") lowRiskCount++;
      
      // Track domain statistics
      const domain = r.classification?.domain || "Other";
      domainStats[domain] = (domainStats[domain] || 0) + 1;
    });
  });
  
  // Prepare chart data
  const riskDistributionData = [
    { name: "High Risk", value: highRiskCount, color: "#ef4444" },
    { name: "Medium Risk", value: mediumRiskCount, color: "#eab308" },
    { name: "Low Risk", value: lowRiskCount, color: "#22c55e" },
  ].filter(item => item.value > 0);
  
  const domainData = Object.entries(domainStats)
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 6);
  
  const riskPercentage = totalClauses > 0 ? Math.round((highRiskCount / totalClauses) * 100) : 0;

  const stats = [
    {
      title: "Total Contracts",
      value: isLoading ? "..." : totalContracts.toString(),
      icon: FileText,
      description: "Analyzed contracts",
      trend: totalContracts > 0 ? "+" + totalContracts : undefined,
    },
    {
      title: "Total Clauses",
      value: isLoading ? "..." : totalClauses.toString(),
      icon: Shield,
      description: "Clauses analyzed",
    },
    {
      title: "High Risk Clauses",
      value: isLoading ? "..." : highRiskCount.toString(),
      icon: AlertTriangle,
      description: "Requiring attention",
      highlight: highRiskCount > 0,
    },
    {
      title: "Low Risk Clauses",
      value: isLoading ? "..." : lowRiskCount.toString(),
      icon: CheckCircle2,
      description: "Meeting standards",
    },
  ];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">
          Contract risk analysis overview and statistics
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat: any) => (
          <Card key={stat.title} className={(stat.highlight ? "border-red-500 border-2" : "")}>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">
                {stat.title}
              </CardTitle>
              <stat.icon className={(stat.highlight ? "h-4 w-4 text-red-500" : "h-4 w-4 text-muted-foreground")} />
            </CardHeader>
            <CardContent>
              <div className={(stat.highlight ? "text-2xl font-bold text-red-600" : "text-2xl font-bold")}>{stat.value}</div>
              <p className="text-xs text-muted-foreground">
                {stat.description}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Risk Distribution Chart */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <PieChartIcon className="h-5 w-5" />
              Risk Distribution
            </CardTitle>
            <CardDescription>Breakdown of risk levels across all clauses</CardDescription>
          </CardHeader>
          <CardContent>
            {totalClauses > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <PieChart>
                  <Pie
                    data={riskDistributionData}
                    cx="50%"
                    cy="50%"
                    labelLine={false}
                    label={({ name, percent }) => `${name}: ${(percent * 100).toFixed(0)}%`}
                    outerRadius={80}
                    fill="#8884d8"
                    dataKey="value"
                  >
                    {riskDistributionData.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[300px] flex items-center justify-center text-muted-foreground">
                <p>No data available. Upload contracts to see risk distribution.</p>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BarChart3 className="h-5 w-5" />
              Clauses by Domain
            </CardTitle>
            <CardDescription>Distribution across contract domains</CardDescription>
          </CardHeader>
          <CardContent>
            {domainData.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={domainData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" angle={-45} textAnchor="end" height={100} />
                  <YAxis />
                  <Tooltip />
                  <Bar dataKey="value" fill="#8b5cf6" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[300px] flex items-center justify-center text-muted-foreground">
                <p>No data available. Upload contracts to see domain distribution.</p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Risk Score Overview */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="h-5 w-5" />
            Overall Risk Score
          </CardTitle>
          <CardDescription>Percentage of high-risk clauses in your portfolio</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium">High Risk Level</span>
              <span className={`font-bold ${riskPercentage > 20 ? 'text-red-600' : riskPercentage > 10 ? 'text-yellow-600' : 'text-green-600'}`}>
                {riskPercentage}%
              </span>
            </div>
            <Progress value={riskPercentage} className="h-2" />
          </div>
          <div className="grid grid-cols-3 gap-4 pt-4">
            <div className="text-center">
              <p className="text-2xl font-bold text-red-600">{highRiskCount}</p>
              <p className="text-xs text-muted-foreground">High Risk</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-yellow-600">{mediumRiskCount}</p>
              <p className="text-xs text-muted-foreground">Medium Risk</p>
            </div>
            <div className="text-center">
              <p className="text-2xl font-bold text-green-600">{lowRiskCount}</p>
              <p className="text-xs text-muted-foreground">Low Risk</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Recent Activity */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Analyses</CardTitle>
          <CardDescription>
            Latest contract analyses
          </CardDescription>
        </CardHeader>
        <CardContent>
          {recentAnalyses.length > 0 ? (
            <div className="space-y-4">
              {recentAnalyses.map((a: any) => {
                const results = a.results || a.clauses || [];
                const highRisk = results.filter((r: any) => (r.classification?.risk_level || "").toLowerCase() === "high").length;
                const dateStr = a.updated_at || a.created_at;
                return (
                  <Link key={a.analysis_id} to={`/analyses/${a.analysis_id}`}>
                    <div className="flex items-center justify-between p-3 rounded-lg border hover:bg-accent transition-colors cursor-pointer">
                      <div className="flex items-center gap-3">
                        <FileText className="h-5 w-5 text-muted-foreground" />
                        <div>
                          <p className="font-medium">{a.filename || `Analysis ${a.analysis_id?.slice(0, 8)}`}</p>
                          <p className="text-xs text-muted-foreground">
                            {dateStr ? new Date(dateStr).toLocaleDateString() : 'Unknown date'} • {results.length} clauses
                          </p>
                        </div>
                      </div>
                      <Badge variant={highRisk > 0 ? "destructive" : "secondary"}>
                        {highRisk > 0 ? `${highRisk} High Risk` : 'Low Risk'}
                      </Badge>
                    </div>
                  </Link>
                );
              })}
            </div>
          ) : (
            <div className="text-center py-8 text-muted-foreground">
              <FileText className="h-12 w-12 mx-auto mb-2 opacity-50" />
              <p>No analyses yet. Upload a contract to get started.</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
