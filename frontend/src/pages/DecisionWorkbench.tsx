/**
 * Decision_Workbench 主布局 — 工作台式多区块同屏布局。
 *
 * 五个同屏区块：
 *  1. IncidentListPanel — 异常事件列表区
 *  2. ProcessingStatusPanel — 当前处理状态区
 *  3. ImpactAnalysisPanel — 影响范围分析区
 *  4. PlanComparisonPanel — 候选方案比较区
 *  5. ConfirmationPanel — 推荐与确认区
 *
 * 两种视图：incident_analysis / multi_plan_selection
 * 桌面端多区块同屏，移动端分步退化。
 *
 * Requirements: 31.1, 31.2, 31.3, 31.5, 31.9, 31.10, 31.11
 */

import React from 'react';
import { Layout, Row, Col, Grid } from 'antd';
import { useWorkbenchStore } from '@/stores';
import { IncidentListPanel } from '@/components/IncidentListPanel';
import { ProcessingStatusPanel } from '@/components/ProcessingStatusPanel';
import { ImpactAnalysisPanel } from '@/components/ImpactAnalysisPanel';
import { PlanComparisonPanel } from '@/components/PlanComparisonPanel';
import { ConfirmationPanel } from '@/components/ConfirmationPanel';
import { CaseReferencePanel } from '@/components/CaseReferencePanel';

const { Content } = Layout;
const { useBreakpoint } = Grid;

const DecisionWorkbench: React.FC = () => {
  const currentView = useWorkbenchStore((s) => s.currentView);
  const screens = useBreakpoint();
  const isDesktop = screens.lg;

  if (!isDesktop) {
    // Mobile / narrow: step-by-step fallback, still shares incident context
    return (
      <Layout style={{ minHeight: '100vh', background: '#f0f2f5' }}>
        <Content style={{ padding: 12 }}>
          <ProcessingStatusPanel />
          <div style={{ marginTop: 12 }}>
            <IncidentListPanel />
          </div>
          {currentView === 'incident_analysis' && (
            <div style={{ marginTop: 12 }}>
              <ImpactAnalysisPanel />
            </div>
          )}
          {currentView === 'multi_plan_selection' && (
            <>
              <div style={{ marginTop: 12 }}>
                <PlanComparisonPanel />
              </div>
              <div style={{ marginTop: 12 }}>
                <ConfirmationPanel />
              </div>
            </>
          )}
          <div style={{ marginTop: 12 }}>
            <CaseReferencePanel />
          </div>
        </Content>
      </Layout>
    );
  }

  // Desktop: multi-panel side-by-side workbench layout
  return (
    <Layout style={{ minHeight: '100vh', background: '#f0f2f5' }}>
      <Content style={{ padding: 16 }}>
        {/* Top bar: processing status */}
        <ProcessingStatusPanel />

        <Row gutter={12} style={{ marginTop: 12 }}>
          {/* Left column: incident list */}
          <Col span={5}>
            <IncidentListPanel />
          </Col>

          {/* Center column: analysis or plan comparison */}
          <Col span={13}>
            {currentView === 'incident_analysis' ? (
              <ImpactAnalysisPanel />
            ) : (
              <PlanComparisonPanel />
            )}
            {/* Case reference always visible on workbench (Req 31.6) */}
            <div style={{ marginTop: 12 }}>
              <CaseReferencePanel />
            </div>
          </Col>

          {/* Right column: confirmation panel */}
          <Col span={6}>
            <ConfirmationPanel />
          </Col>
        </Row>
      </Content>
    </Layout>
  );
};

export default DecisionWorkbench;
