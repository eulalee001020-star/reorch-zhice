import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';

/**
 * Two primary workbench views as defined in Requirement 31.11.
 */
export type WorkbenchView = 'incident_analysis' | 'multi_plan_selection';

interface WorkbenchState {
  /** Current active view */
  currentView: WorkbenchView;
  /** Incident ID shared across all workbench panels */
  incidentContextId: string | null;

  setCurrentView: (view: WorkbenchView) => void;
  setIncidentContext: (incidentId: string | null) => void;
}

export const useWorkbenchStore = create<WorkbenchState>()(
  immer((set) => ({
    currentView: 'incident_analysis' as WorkbenchView,
    incidentContextId: null,

    setCurrentView: (view) => {
      set((s) => { s.currentView = view; });
    },

    setIncidentContext: (incidentId) => {
      set((s) => { s.incidentContextId = incidentId; });
    },
  })),
);
