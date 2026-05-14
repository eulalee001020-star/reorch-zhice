/**
 * WebSocket client for real-time incident event push.
 *
 * Supported event types:
 *   incident_created, incident_updated, impact_report_ready,
 *   strategy_selected, plans_generated, recommendation_updated,
 *   writeback_status_changed
 */

export type WsEventType =
  | 'incident_created'
  | 'incident_updated'
  | 'impact_report_ready'
  | 'strategy_selected'
  | 'plans_generated'
  | 'recommendation_updated'
  | 'writeback_status_changed';

export interface WsMessage {
  event: WsEventType;
  payload: unknown;
  timestamp: string;
}

type WsListener = (msg: WsMessage) => void;

class ReOrchWebSocket {
  private ws: WebSocket | null = null;
  private listeners: Map<WsEventType | '*', Set<WsListener>> = new Map();
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private baseDelay = 1000;
  private url: string;

  constructor() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    this.url = `${protocol}//${window.location.host}/api/v1/ws/incidents`;
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return;

    const token = localStorage.getItem('reorch_token');
    const urlWithAuth = token ? `${this.url}?token=${token}` : this.url;

    this.ws = new WebSocket(urlWithAuth);

    this.ws.onopen = () => {
      console.info('[ReOrch WS] 连接已建立');
      this.reconnectAttempts = 0;
    };

    this.ws.onmessage = (event: MessageEvent) => {
      try {
        const msg: WsMessage = JSON.parse(event.data);
        this.dispatch(msg);
      } catch {
        console.warn('[ReOrch WS] 无法解析消息:', event.data);
      }
    };

    this.ws.onclose = () => {
      console.info('[ReOrch WS] 连接已关闭');
      this.scheduleReconnect();
    };

    this.ws.onerror = (err) => {
      console.error('[ReOrch WS] 连接错误:', err);
    };
  }

  disconnect(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.reconnectAttempts = this.maxReconnectAttempts; // prevent reconnect
    this.ws?.close();
    this.ws = null;
  }

  on(event: WsEventType | '*', listener: WsListener): () => void {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event)!.add(listener);

    // Return unsubscribe function
    return () => {
      this.listeners.get(event)?.delete(listener);
    };
  }

  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  private dispatch(msg: WsMessage): void {
    // Notify specific event listeners
    this.listeners.get(msg.event)?.forEach((fn) => fn(msg));
    // Notify wildcard listeners
    this.listeners.get('*')?.forEach((fn) => fn(msg));
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.warn('[ReOrch WS] 已达最大重连次数，停止重连');
      return;
    }
    const delay = this.baseDelay * Math.pow(2, this.reconnectAttempts);
    this.reconnectAttempts++;
    console.info(`[ReOrch WS] ${delay}ms 后尝试第 ${this.reconnectAttempts} 次重连`);
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }
}

// Singleton instance
const wsClient = new ReOrchWebSocket();
export default wsClient;
