import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';
import type { ImpactReport, StrategyRecommendation } from '@/types';
import { getImpactReport, getStrategy } from '@/api';

interface AnalysisState {
  impactReport: ImpactReport | null;
  strategyRecommendation: StrategyRecommendation | null;
  loadingImpact: boolean;
  loadingStrategy: boolean;

  fetchImpactReport: (incidentId: string) => Promise<void>;
  fetchStrategy: (incidentId: string) => Promise<void>;
  reset: () => void;
}

export const useAnalysisStore = create<AnalysisState>()(
  immer((set) => ({
    impactReport: null,
    strategyRecommendation: null,
    loadingImpact: false,
    loadingStrategy: false,

    fetchImpactReport: async (incidentId) => {
      set((s) => { s.loadingImpact = true; });
      try {
        const data = await getImpactReport(incidentId);
        set((s) => { s.impactReport = data; });
      } finally {
        set((s) => { s.loadingImpact = false; });
      }
    },

    fetchStrategy: async (incidentId) => {
      set((s) => { s.loadingStrategy = true; });
      try {
        const data = await getStrategy(incidentId);
        set((s) => { s.strategyRecommendation = data; });
      } finally {
        set((s) => { s.loadingStrategy = false; });
      }
    },

    reset: () => {
      set((s) => {
        s.impactReport = null;
        s.strategyRecommendation = null;
        s.loadingImpact = false;
        s.loadingStrategy = false;
      });
    },
  })),
);
