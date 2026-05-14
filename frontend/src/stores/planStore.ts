import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';
import type { CandidatePlan, PlanSelectionOutput } from '@/types';
import { GoalMode } from '@/types';
import { listCandidatePlans, getRecommendation } from '@/api';

interface PlanState {
  candidatePlans: CandidatePlan[];
  planSelectionOutput: PlanSelectionOutput | null;
  selectedPlanId: string | null;
  goalMode: GoalMode;
  manualWeights: Record<string, number> | null;
  autoPreselected: boolean;
  loadingPlans: boolean;
  loadingRecommendation: boolean;

  fetchCandidatePlans: (incidentId: string) => Promise<void>;
  fetchRecommendation: (incidentId: string) => Promise<void>;
  setSelectedPlanId: (id: string | null) => void;
  setGoalMode: (mode: GoalMode) => void;
  setManualWeights: (weights: Record<string, number> | null) => void;
  reset: () => void;
}

export const usePlanStore = create<PlanState>()(
  immer((set) => ({
    candidatePlans: [],
    planSelectionOutput: null,
    selectedPlanId: null,
    goalMode: GoalMode.BALANCED,
    manualWeights: null,
    autoPreselected: false,
    loadingPlans: false,
    loadingRecommendation: false,

    fetchCandidatePlans: async (incidentId) => {
      set((s) => { s.loadingPlans = true; });
      try {
        const data = await listCandidatePlans(incidentId);
        set((s) => { s.candidatePlans = data; });
      } finally {
        set((s) => { s.loadingPlans = false; });
      }
    },

    fetchRecommendation: async (incidentId) => {
      set((s) => { s.loadingRecommendation = true; });
      try {
        const data = await getRecommendation(incidentId);
        set((s) => {
          s.planSelectionOutput = data;
          s.autoPreselected = data.auto_preselected;
          if (data.auto_preselected) {
            s.selectedPlanId = data.recommended_plan_id;
          }
        });
      } finally {
        set((s) => { s.loadingRecommendation = false; });
      }
    },

    setSelectedPlanId: (id) => {
      set((s) => { s.selectedPlanId = id; });
    },

    setGoalMode: (mode) => {
      set((s) => { s.goalMode = mode; });
    },

    setManualWeights: (weights) => {
      set((s) => { s.manualWeights = weights; });
    },

    reset: () => {
      set((s) => {
        s.candidatePlans = [];
        s.planSelectionOutput = null;
        s.selectedPlanId = null;
        s.goalMode = GoalMode.BALANCED;
        s.manualWeights = null;
        s.autoPreselected = false;
        s.loadingPlans = false;
        s.loadingRecommendation = false;
      });
    },
  })),
);
