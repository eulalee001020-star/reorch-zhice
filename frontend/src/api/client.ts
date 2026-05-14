import axios, { AxiosError, InternalAxiosRequestConfig } from 'axios';

const apiClient = axios.create({
  baseURL: '/api/v1',
  timeout: 70_000,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor — attach auth token if available
apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem('reorch_api_key');
    if (token && config.headers) {
      config.headers['X-API-Key'] = token;
    }
    return config;
  },
  (error: AxiosError) => Promise.reject(error),
);

// Response interceptor — unified error handling
apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError<{ detail?: string }>) => {
    if (error.response) {
      const { status, data } = error.response;

      if (status === 401) {
        localStorage.removeItem('reorch_api_key');
        localStorage.removeItem('reorch_user');
      }

      if (status === 403) {
        console.error('[ReOrch] 权限不足:', data?.detail);
      }

      if (status === 429) {
        console.warn('[ReOrch] 请求过于频繁，请稍后重试');
      }

      if (status >= 500) {
        console.error('[ReOrch] 服务端错误:', data?.detail);
      }
    } else if (error.request) {
      console.error('[ReOrch] 网络错误: 无法连接到服务器');
    }

    return Promise.reject(error);
  },
);

export default apiClient;
