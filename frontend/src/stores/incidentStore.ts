import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';
import type { Incident } from '@/types';
import { listIncidents, getIncident, type ListIncidentsParams } from '@/api';

interface IncidentState {
  /** Currently selected incident ID */
  selectedIncidentId: string | null;
  /** Full list of incidents */
  incidents: Incident[];
  /** Active filter params */
  filters: ListIncidentsParams;
  /** Loading flag */
  loading: boolean;

  // Actions
  setSelectedIncidentId: (id: string | null) => void;
  setFilters: (filters: ListIncidentsParams) => void;
  fetchIncidents: () => Promise<void>;
  fetchIncident: (id: string) => Promise<Incident>;
  upsertIncident: (incident: Incident) => void;
}

export const useIncidentStore = create<IncidentState>()(
  immer((set, get) => ({
    selectedIncidentId: null,
    incidents: [],
    filters: {},
    loading: false,

    setSelectedIncidentId: (id) => {
      set((s) => {
        s.selectedIncidentId = id;
      });
    },

    setFilters: (filters) => {
      set((s) => {
        s.filters = filters;
      });
    },

    fetchIncidents: async () => {
      set((s) => { s.loading = true; });
      try {
        const data = await listIncidents(get().filters);
        set((s) => { s.incidents = data; });
      } finally {
        set((s) => { s.loading = false; });
      }
    },

    fetchIncident: async (id) => {
      const incident = await getIncident(id);
      set((s) => {
        const idx = s.incidents.findIndex((i) => i.incident_id === id);
        if (idx >= 0) {
          s.incidents[idx] = incident;
        } else {
          s.incidents.push(incident);
        }
      });
      return incident;
    },

    /** Insert or update a single incident (e.g. from WebSocket push). */
    upsertIncident: (incident) => {
      set((s) => {
        const idx = s.incidents.findIndex((i) => i.incident_id === incident.incident_id);
        if (idx >= 0) {
          s.incidents[idx] = incident;
        } else {
          s.incidents.unshift(incident);
        }
      });
    },
  })),
);
