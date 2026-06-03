import { lazy, Suspense, useState } from 'react';
import { Button, Card, ConfigProvider, Form, Input, Layout, Menu, Space, Spin, Tag, message } from 'antd';
import {
  AuditOutlined,
  BranchesOutlined,
  DashboardOutlined,
  DatabaseOutlined,
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

const DecisionWorkbench = lazy(() => import('@/pages/DecisionWorkbench'));
const CaseLibraryPage = lazy(() => import('@/pages/CaseLibraryPage'));
const DataReadinessPage = lazy(() => import('@/pages/DataReadinessPage'));
const EvidenceCenterPage = lazy(() => import('@/pages/EvidenceCenterPage'));
const InitialSchedulingPage = lazy(() => import('@/pages/InitialSchedulingPage'));
const NgsLabPage = lazy(() => import('@/pages/NgsLabPage'));
const PocDashboardPage = lazy(() => import('@/pages/PocDashboardPage'));
const PreferenceProfilePage = lazy(() => import('@/pages/PreferenceProfilePage'));
const RuleCandidateReviewPage = lazy(() => import('@/pages/RuleCandidateReviewPage'));

function App() {
  const [activeTab, setActiveTab] = useState<string>('workbench');
  const user = useAuthStore((s) => s.user);
  const loading = useAuthStore((s) => s.loading);
  const login = useAuthStore((s) => s.login);
  const logout = useAuthStore((s) => s.logout);

  const handleLogin = async (values: { username: string; password: string }) => {
    try {
      await login(values.username, values.password);
      message.success('登录成功');
    } catch {
      message.error('用户名或密码错误');
    }
  };

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#1677ff',
        },
      }}
    >
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
            </Form>
          </Card>
        </Layout>
      ) : (
      <Layout style={{ minHeight: '100vh' }}>
        <Header
          style={{
            display: 'flex',
            alignItems: 'center',
            padding: '0 16px',
            background: '#001529',
          }}
        >
          <div
            style={{
              color: '#fff',
              fontWeight: 600,
              fontSize: 16,
              marginRight: 12,
              whiteSpace: 'nowrap',
            }}
          >
            ReOrch 智策
          </div>
          <Tag
            color="geekblue"
            style={{ marginRight: 8 }}
            title="异常决策层，不替代 ERP/MES/MOM"
          >
            异常决策层
          </Tag>
          <Menu
            theme="dark"
            mode="horizontal"
            selectedKeys={[activeTab]}
            onClick={({ key }) => setActiveTab(key)}
            style={{ flex: 1, minWidth: 0 }}
            items={[
              {
                key: 'workbench',
                icon: <DashboardOutlined />,
                label: '决策工作台',
              },
              {
                key: 'rules',
                icon: <BranchesOutlined />,
                label: '规则审核',
              },
              {
                key: 'preference',
                icon: <ProfileOutlined />,
                label: '偏好画像',
              },
              {
                key: 'readiness',
                icon: <SafetyCertificateOutlined />,
                label: '数据就绪',
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
                key: 'initial',
                icon: <ScheduleOutlined />,
                label: '初始调度',
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
          <Space style={{ color: '#fff' }}>
            <Tag color="blue">{user.role}</Tag>
            <span>{user.display_name}</span>
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
          {activeTab === 'workbench' && <DecisionWorkbench />}
          {activeTab === 'rules' && <RuleCandidateReviewPage />}
          {activeTab === 'preference' && <PreferenceProfilePage />}
          {activeTab === 'readiness' && <DataReadinessPage />}
          {activeTab === 'initial' && <InitialSchedulingPage />}
          {activeTab === 'poc' && <PocDashboardPage />}
          {activeTab === 'evidence' && <EvidenceCenterPage />}
          {activeTab === 'ngs' && <NgsLabPage />}
          {activeTab === 'cases' && <CaseLibraryPage />}
        </Suspense>
      </Layout>
      )}
    </ConfigProvider>
  );
}

export default App;
