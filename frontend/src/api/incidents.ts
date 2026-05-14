import apiClient from './client';
import type { Incident, IncidentCreateRequest } from '@/types';

export interface ListIncidentsParams {
  incident_type?: string;
  severity?: string;
  status?: string;
  start_time?: string;
  end_time?: string;
}

export async function createIncident(data: IncidentCreateRequest): Promise<Incident> {
  const res = await apiClient.post<Incident>('/incidents', data);
  return res.data;
}

export async function listIncidents(params?: ListIncidentsParams): Promise<Incident[]> {
  const res = await apiClient.get<Incident[]>('/incidents', { params });
  return res.data;
}

export async function getIncident(incidentId: string): Promise<Incident> {
  const res = await apiClient.get<Incident>(`/incidents/${incidentId}`);
  return res.data;
}
