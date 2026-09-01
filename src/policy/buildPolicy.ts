import { ROOT_DOMAIN_LABELS, uiLabels, uiPolicies, UILibraryPolicy, PolicyLabel, RiskLevel } from "./policyLibrary";

export interface CompiledPolicy {
  policy_id: string;
  risk_threshold?: number;
  domains: Array<{
    domain_name: string;
    micro_policies: Array<{
      id: string;
      name: string;
      check: string;
      risk_weight: number;
    }>;
  }>;
}

const riskWeight = (level: RiskLevel): number => {
  switch (level) {
    case "high":
      return 5;
    case "medium":
      return 3;
    default:
      return 1;
  }
};

function collectPoliciesForRoot(rootId: string, labels: PolicyLabel[], policies: UILibraryPolicy[]): UILibraryPolicy[] {
  const descendants = new Set<string>();
  const addDesc = (id: string) => {
    descendants.add(id);
    labels.filter(l => l.parentLabelId === id).forEach(l => addDesc(l.id));
  };
  addDesc(rootId);
  const ids = new Set<string>(Array.from(descendants));
  return policies.filter(p => p.labelIds.some(lid => ids.has(lid)));
}

export function buildCompiledPolicy(options?: { includeRoots?: string[]; policyId?: string; riskThreshold?: number }): CompiledPolicy {
  const { includeRoots, policyId = "default_ui_policy", riskThreshold = 10 } = options || {};

  const roots = Object.keys(ROOT_DOMAIN_LABELS).filter(rootId => !includeRoots || includeRoots.includes(rootId));

  const domains = roots.map(rootId => {
    const domain_name = ROOT_DOMAIN_LABELS[rootId] || "Other";
    const list = collectPoliciesForRoot(rootId, uiLabels, uiPolicies);
    const micro_policies = list.map(p => ({
      id: p.id,
      name: p.name,
      check: p.description,
      risk_weight: riskWeight(p.riskLevel),
    }));
    return { domain_name, micro_policies };
  });

  return {
    policy_id: policyId,
    risk_threshold: riskThreshold,
    domains,
  };
}
