import apiClient from './client';
import type { CurrentUser, LoginResponse } from '@/types';

export async function login(username: string, password: string): Promise<LoginResponse> {
  const res = await apiClient.post<LoginResponse>('/auth/login', { username, password });
  return res.data;
}

export async function getMe(): Promise<CurrentUser> {
  const res = await apiClient.get<CurrentUser>('/auth/me');
  return res.data;
}
