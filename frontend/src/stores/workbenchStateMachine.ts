/**
 * Workbench state machine — orchestrates view transitions and context resets.
 *
 * Requirements: 10.10, 11.8, 12.11, 13.12, 31.3, 31.4, 31.11
 *
 * Rules:
 *  - Default view: incident_analysis
 *  - Transition to multi_plan_selection ONLY when impactReport AND candidatePlans are ready
 *  - On incident switch: clear selectedPlanId, manualWeights, autoPreselected, adjustmentDraft
 *  - On GoalMode change: force-refresh PlanSelectionOutput
 *  - After recommendation refresh: recompute auto-preselection and confirm panel state
 */

import { useAnalysisStore } from './analysisStore';
import { usePlanStore } from './planStore';
import { useConfirmStore } from './confirmStore';
import { useWorkbenchStore, type WorkbenchView } from './workbenchStore';
import { useIncidentStore } from './incidentStore';
import { recommendPlan, runAgentDecisionFlow } from '@/api';

// ---------------------------------------------------------------------------
// Guard: can we transition to multi_plan_selection?
// ---------------------------------------------------------------------------

export function canEnterPlanSelection(): boolean {
  const { impactReport } = useAnalysisStore.getState();
  const { candidatePlans } = usePlanStore.getState();
  return impactReport !== null && candidatePlans.length > 0;
}

// ---------------------------------------------------------------------------
// Transition helper
// ---------------------------------------------------------------------------

export function transitionView(target: WorkbenchView): boolean {
  if (target === 'multi_plan_selection' && !canEnterPlanSelection()) {
    return false;
  }
  useWorkbenchStore.getState().setCurrentView(target);
  return true;
}

// ---------------------------------------------------------------------------
// Incident switch — reset dependent state
// ---------------------------------------------------------------------------

export async function switchIncident(incidentId: string): Promise<void> {
  const incidentStore = useIncidentStore.getState();
  const analysisStore = useAnalysisStore.getState();
  const planStore = usePlanStore.getState();
  const confirmStore = useConfirmStore.getState();
  const workbenchStore = useWorkbenchStore.getState();

  // 1. Set new incident context
  incidentStore.setSelectedIncidentId(incidentId);
  workbenchStore.setIncidentContext(incidentId);

  // 2. Reset downstream state (Req 10.10, 31.11)
  planStore.reset();
  confirmStore.reset();
  analysisStore.reset();

  // 3. Return to default view
  workbenchStore.setCurrentView('incident_analysis');

  // 4. Run controlled Agent workflow: Impact -> Strategy -> Solver -> Evaluation.
  useAnalysisStore.setState((s) => {
    s.loadingImpact = true;
    s.loadingStrategy = true;
  });
  usePlanStore.setState((s) => {
    s.loadingPlans = true;
    s.loadingRecommendation = true;
  });

  const flowPlanState = usePlanStore.getState();
  try {
    const output = await runAgentDecisionFlow({
      incident_id: incidentId,
      goal_mode: flowPlanState.goalMode,
      manual_weights: flowPlanState.manualWeights,
      auto_solve: true,
      auto_recommend: true,
    });

    useAnalysisStore.setState((s) => {
      s.impactReport = output.impact_report;
      s.strategyRecommendation = output.strategy;
    });
    usePlanStore.setState((s) => {
      s.candidatePlans = output.candidate_plans;
      s.planSelectionOutput = output.recommendation ?? null;
      s.autoPreselected = output.recommendation?.auto_preselected ?? false;
      if (output.recommendation?.auto_preselected) {
        s.selectedPlanId = output.recommendation.recommended_plan_id;
      }
    });
  } catch {
    await Promise.all([
      analysisStore.fetchImpactReport(incidentId),
      analysisStore.fetchStrategy(incidentId),
    ]);
  } finally {
    useAnalysisStore.setState((s) => {
      s.loadingImpact = false;
      s.loadingStrategy = false;
    });
    usePlanStore.setState((s) => {
      s.loadingPlans = false;
      s.loadingRecommendation = false;
    });
  }
}

// ---------------------------------------------------------------------------
// GoalMode change — force refresh PlanSelectionOutput (Req 12.11)
// ---------------------------------------------------------------------------

export async function changeGoalMode(
  incidentId: string,
  mode: import('@/types').GoalMode,
): Promise<void> {
  const planStore = usePlanStore.getState();

  planStore.setGoalMode(mode);

  // Force refresh recommendation with new goal mode
  planStore.setSelectedPlanId(null);

  try {
    const output = await recommendPlan(incidentId, {
      goal_mode: mode,
      manual_weights: planStore.manualWeights ?? undefined,
    });

    usePlanStore.setState((s) => {
      s.planSelectionOutput = output;
      s.autoPreselected = output.auto_preselected;
      if (output.auto_preselected) {
        s.selectedPlanId = output.recommended_plan_id;
      }
    });

    // Reset confirm panel after recommendation refresh (Req 13.12)
    useConfirmStore.getState().reset();
  } catch {
    // Keep previous state on error — UI should show error toast
  }
}

// ---------------------------------------------------------------------------
// Refresh recommendation (e.g. after manual weight change)
// ---------------------------------------------------------------------------

export async function refreshRecommendation(incidentId: string): Promise<void> {
  const planStore = usePlanStore.getState();

  planStore.setSelectedPlanId(null);

  try {
    const output = await recommendPlan(incidentId, {
      goal_mode: planStore.goalMode,
      manual_weights: planStore.manualWeights ?? undefined,
    });

    usePlanStore.setState((s) => {
      s.planSelectionOutput = output;
      s.autoPreselected = output.auto_preselected;
      if (output.auto_preselected) {
        s.selectedPlanId = output.recommended_plan_id;
      }
    });

    useConfirmStore.getState().reset();
  } catch {
    // Keep previous state on error
  }
}
