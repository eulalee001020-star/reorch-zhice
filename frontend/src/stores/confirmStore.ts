import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';
import type { ConfirmAction } from '@/types';

interface ConfirmState {
  /** Current confirmation status (null = not yet acted) */
  confirmStatus: ConfirmAction | null;
  /** Draft adjustments for micro-adjustment mode */
  adjustmentDraft: Record<string, unknown>[] | null;
  /** Override reason text (required when rejecting) */
  overrideReason: string;

  setConfirmStatus: (status: ConfirmAction | null) => void;
  setAdjustmentDraft: (draft: Record<string, unknown>[] | null) => void;
  setOverrideReason: (reason: string) => void;
  reset: () => void;
}

export const useConfirmStore = create<ConfirmState>()(
  immer((set) => ({
    confirmStatus: null,
    adjustmentDraft: null,
    overrideReason: '',

    setConfirmStatus: (status) => {
      set((s) => { s.confirmStatus = status; });
    },

    setAdjustmentDraft: (draft) => {
      set((s) => { s.adjustmentDraft = draft; });
    },

    setOverrideReason: (reason) => {
      set((s) => { s.overrideReason = reason; });
    },

    reset: () => {
      set((s) => {
        s.confirmStatus = null;
        s.adjustmentDraft = null;
        s.overrideReason = '';
      });
    },
  })),
);
