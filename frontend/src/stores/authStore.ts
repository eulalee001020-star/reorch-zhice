import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';
import type { CurrentUser } from '@/types';
import { getMe, login as loginApi } from '@/api/auth';

interface AuthState {
  apiKey: string | null;
  user: CurrentUser | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  restore: () => Promise<void>;
  logout: () => void;
}

const storedApiKey = localStorage.getItem('reorch_api_key');
const storedUser = localStorage.getItem('reorch_user');

export const useAuthStore = create<AuthState>()(
  immer((set, get) => ({
    apiKey: storedApiKey,
    user: storedUser ? JSON.parse(storedUser) : null,
    loading: false,

    login: async (username, password) => {
      set((s) => { s.loading = true; });
      try {
        const result = await loginApi(username, password);
        localStorage.setItem('reorch_api_key', result.api_key);
        localStorage.setItem('reorch_user', JSON.stringify(result.user));
        set((s) => {
          s.apiKey = result.api_key;
          s.user = result.user;
        });
      } finally {
        set((s) => { s.loading = false; });
      }
    },

    restore: async () => {
      if (!get().apiKey) return;
      set((s) => { s.loading = true; });
      try {
        const user = await getMe();
        localStorage.setItem('reorch_user', JSON.stringify(user));
        set((s) => { s.user = user; });
      } catch {
        get().logout();
      } finally {
        set((s) => { s.loading = false; });
      }
    },

    logout: () => {
      localStorage.removeItem('reorch_api_key');
      localStorage.removeItem('reorch_user');
      set((s) => {
        s.apiKey = null;
        s.user = null;
      });
    },
  })),
);
