import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';
import type { AgentTraceStep } from '@/types';

/**
 * Two primary workbench views as defined in Requirement 31.11.
 */
export type WorkbenchView = 'incident_analysis' | 'multi_plan_selection';

interface WorkbenchState {
  /** Current active view */
  currentView: WorkbenchView;
  /** Incident ID shared across all workbench panels */
  incidentContextId: string | null;
  /** Auditable Agent call chain from the latest decision flow */
  agentTrace: AgentTraceStep[];

  setCurrentView: (view: WorkbenchView) => void;
  setIncidentContext: (incidentId: string | null) => void;
  setAgentTrace: (trace: AgentTraceStep[]) => void;
}

export const useWorkbenchStore = create<WorkbenchState>()(
  immer((set) => ({
    currentView: 'incident_analysis' as WorkbenchView,
    incidentContextId: null,
    agentTrace: [],

    setCurrentView: (view) => {
      set((s) => { s.currentView = view; });
    },

    setIncidentContext: (incidentId) => {
      set((s) => { s.incidentContextId = incidentId; });
    },

    setAgentTrace: (trace) => {
      set((s) => { s.agentTrace = trace; });
    },
  })),
);
