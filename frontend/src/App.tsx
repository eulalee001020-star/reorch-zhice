import { useState } from 'react';
import { ConfigProvider, Layout, Menu } from 'antd';
import {
  DashboardOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  ScheduleOutlined,
} from '@ant-design/icons';
import zhCN from 'antd/locale/zh_CN';
import dayjs from 'dayjs';
import 'dayjs/locale/zh-cn';
import DecisionWorkbench from '@/pages/DecisionWorkbench';
import CaseLibraryPage from '@/pages/CaseLibraryPage';
import InitialSchedulingPage from '@/pages/InitialSchedulingPage';
import PocDashboardPage from '@/pages/PocDashboardPage';

dayjs.locale('zh-cn');

const { Header } = Layout;

function App() {
  const [activeTab, setActiveTab] = useState<string>('workbench');

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: '#1677ff',
        },
      }}
    >
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
              marginRight: 24,
              whiteSpace: 'nowrap',
            }}
          >
            ReOrch 智策
          </div>
          <Menu
            theme="dark"
            mode="horizontal"
            selectedKeys={[activeTab]}
            onClick={({ key }) => setActiveTab(key)}
            style={{ flex: 1 }}
            items={[
              {
                key: 'workbench',
                icon: <DashboardOutlined />,
                label: '决策工作台',
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
        </Header>
        {activeTab === 'workbench' && <DecisionWorkbench />}
        {activeTab === 'initial' && <InitialSchedulingPage />}
        {activeTab === 'poc' && <PocDashboardPage />}
        {activeTab === 'cases' && <CaseLibraryPage />}
      </Layout>
    </ConfigProvider>
  );
}

export default App;
