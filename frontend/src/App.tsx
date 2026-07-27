import { lazy, Suspense, useEffect, useState } from 'react';
import { Alert, App as AntdApp, Button, Card, ConfigProvider, Form, Input, Layout, Menu, Space, Spin, Tag } from 'antd';
import {
  AuditOutlined,
  ApiOutlined,
  BranchesOutlined,
  ClusterOutlined,
  CloudServerOutlined,
  DashboardOutlined,
  DatabaseOutlined,
  DeploymentUnitOutlined,
  ExperimentOutlined,
  ProfileOutlined,
  SafetyCertificateOutlined,
  ScheduleOutlined,
} from '@ant-design/icons';
import zhCN from 'antd/locale/zh_CN';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import { useAuthStore } from '@/stores';

dayjs.locale('zh-cn');

const { Header } = Layout;

const ProductOverviewPage = lazy(() => import('@/pages/ProductOverviewPage'));
const DecisionWorkbench = lazy(() => import('@/pages/DecisionWorkbench'));
const CaseLibraryPage = lazy(() => import('@/pages/CaseLibraryPage'));
const DataReadinessPage = lazy(() => import('@/pages/DataReadinessPage'));
const DesignPartnerPreflightPage = lazy(() => import('@/pages/DesignPartnerPreflightPage'));
const EvidenceCenterPage = lazy(() => import('@/pages/EvidenceCenterPage'));
const InitialSchedulingPage = lazy(() => import('@/pages/InitialSchedulingPage'));
const NgsLabPage = lazy(() => import('@/pages/NgsLabPage'));
const PocDashboardPage = lazy(() => import('@/pages/PocDashboardPage'));
const PreferenceProfilePage = lazy(() => import('@/pages/PreferenceProfilePage'));
const RuleCandidateReviewPage = lazy(() => import('@/pages/RuleCandidateReviewPage'));
const ProductionRuntimePage = lazy(() => import('@/pages/ProductionRuntimePage'));
const IntegrationControlPage = lazy(() => import('@/pages/IntegrationControlPage'));

function App() {
  const [activeTab, setActiveTab] = useState<string>('overview');
  const [loginError, setLoginError] = useState<string | null>(null);
  const user = useAuthStore((s) => s.user);
  const loading = useAuthStore((s) => s.loading);
  const login = useAuthStore((s) => s.login);
  const logout = useAuthStore((s) => s.logout);

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      const nav = document.querySelector<HTMLElement>('.primary-nav');
      const selected = nav?.querySelector<HTMLElement>('.ant-menu-item-selected');
      if (!nav || !selected) return;
      const centeredLeft = selected.offsetLeft - (nav.clientWidth - selected.offsetWidth) / 2;
      nav.scrollTo({ left: Math.max(0, centeredLeft), behavior: 'smooth' });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [activeTab]);

  const handleLogin = async (values: { username: string; password: string }) => {
    setLoginError(null);
    try {
      await login(values.username, values.password);
    } catch {
      setLoginError('用户名或密码错误');
    }
  };

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#1d75ff',
          borderRadius: 8,
          fontFamily:
            '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
        },
      }}
    >
      <AntdApp>
      {!user ? (
        <Layout
          style={{
            minHeight: '100vh',
            alignItems: 'center',
            justifyContent: 'center',
            background: '#f5f7fb',
          }}
        >
          <Card title="ReOrch 智策" style={{ width: 360 }}>
            <Form layout="vertical" onFinish={handleLogin} initialValues={{ username: 'planner' }}>
              <Form.Item name="username" label="用户名" rules={[{ required: true }]}>
                <Input autoComplete="username" />
              </Form.Item>
              <Form.Item name="password" label="密码" rules={[{ required: true }]}>
                <Input.Password autoComplete="current-password" />
              </Form.Item>
              <Button type="primary" htmlType="submit" block loading={loading}>
                登录
              </Button>
              {loginError && (
                <Alert
                  type="error"
                  showIcon
                  message={loginError}
                  style={{ marginTop: 12 }}
                />
              )}
            </Form>
          </Card>
        </Layout>
      ) : (
      <Layout className="app-shell" style={{ minHeight: '100vh' }}>
        <Header
          className="app-header"
          style={{
            display: 'flex',
            alignItems: 'center',
          }}
        >
          <div className="brand-lockup">
            <span className="brand-mark">R</span>
            <div>
              <div className="brand-title">ReOrch 智策</div>
              <div className="brand-subtitle">Exception Recovery Layer</div>
            </div>
          </div>
          <Tag
            className="boundary-tag"
            color="geekblue"
            style={{ marginRight: 8 }}
            title="异常决策层，不替代 ERP/MES/MOM"
          >
            异常决策层
          </Tag>
          <Menu
            className="primary-nav"
            theme="dark"
            mode="horizontal"
            disabledOverflow
            selectedKeys={[activeTab]}
            onClick={({ key }) => setActiveTab(key)}
            style={{ flex: 1, minWidth: 0, background: 'transparent' }}
            items={[
              {
                key: 'overview',
                icon: <ClusterOutlined />,
                label: '产品总览',
              },
              {
                key: 'workbench',
                icon: <DashboardOutlined />,
                label: '异常工作台',
              },
              {
                key: 'readiness',
                icon: <SafetyCertificateOutlined />,
                label: 'DataGate',
              },
              {
                key: 'integration',
                icon: <ApiOutlined />,
                label: '接入治理',
              },
              {
                key: 'runtime',
                icon: <CloudServerOutlined />,
                label: '生产运行',
              },
              {
                key: 'initial',
                icon: <ScheduleOutlined />,
                label: '初始排程',
              },
              {
                key: 'partner',
                icon: <DeploymentUnitOutlined />,
                label: '试点预检',
              },
              {
                key: 'rules',
                icon: <BranchesOutlined />,
                label: '规则候选',
              },
              {
                key: 'preference',
                icon: <ProfileOutlined />,
                label: '偏好学习',
              },
              {
                key: 'ngs',
                icon: <ExperimentOutlined />,
                label: 'NGS Lab',
              },
              {
                key: 'evidence',
                icon: <AuditOutlined />,
                label: '证据中心',
              },
              {
                key: 'poc',
                icon: <ExperimentOutlined />,
                label: 'PoC 验收',
              },
              {
                key: 'cases',
                icon: <DatabaseOutlined />,
                label: '案例库',
              },
            ]}
          />
          <Space className="user-cluster" style={{ color: '#fff' }}>
            <Tag color="blue">{user.role}</Tag>
            <span className="user-display-name">{user.display_name}</span>
            <Button size="small" onClick={logout}>退出</Button>
          </Space>
        </Header>
        <Suspense
          fallback={
            <div style={{ padding: 24 }}>
              <Spin />
            </div>
          }
        >
          <div className="app-content">
            {activeTab === 'overview' && <ProductOverviewPage onNavigate={setActiveTab} />}
            {activeTab === 'workbench' && <DecisionWorkbench />}
            {activeTab === 'rules' && <RuleCandidateReviewPage />}
            {activeTab === 'preference' && <PreferenceProfilePage />}
            {activeTab === 'readiness' && <DataReadinessPage />}
            {activeTab === 'initial' && <InitialSchedulingPage />}
            {activeTab === 'partner' && <DesignPartnerPreflightPage />}
            {activeTab === 'poc' && <PocDashboardPage />}
            {activeTab === 'runtime' && <ProductionRuntimePage />}
            {activeTab === 'integration' && <IntegrationControlPage />}
            {activeTab === 'evidence' && <EvidenceCenterPage />}
            {activeTab === 'ngs' && <NgsLabPage />}
            {activeTab === 'cases' && <CaseLibraryPage />}
          </div>
        </Suspense>
      </Layout>
      )}
      </AntdApp>
    </ConfigProvider>
  );
}

export default App;
