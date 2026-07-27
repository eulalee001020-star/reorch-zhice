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
import { Layout, Row, Col, Grid, Tag } from 'antd';
import { useWorkbenchStore } from '@/stores';
import { IncidentListPanel } from '@/components/IncidentListPanel';
import { ProcessingStatusPanel } from '@/components/ProcessingStatusPanel';
import { ImpactAnalysisPanel } from '@/components/ImpactAnalysisPanel';
import { PlanComparisonPanel } from '@/components/PlanComparisonPanel';
import { ConfirmationPanel } from '@/components/ConfirmationPanel';
import { CaseReferencePanel } from '@/components/CaseReferencePanel';

const { Content } = Layout;
const { useBreakpoint } = Grid;

const recoveryLoop = [
  ['01', 'Incident', '异常进入'],
  ['02', 'State', '状态检索'],
  ['03', 'Constraints', '约束编译'],
  ['04', 'Options', '候选方案'],
  ['05', 'Gate', '质量门'],
  ['06', 'Decision + Feedback', '确认与复盘'],
];

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
    <Layout style={{ minHeight: '100%', background: 'transparent' }}>
      <Content className="demo-page">
        <div className="demo-hero demo-hero-dark">
          <Row gutter={[18, 18]} align="middle">
            <Col xs={24} lg={12}>
              <div className="hero-eyebrow">Demo Scenario / CNC machine-down recovery</div>
              <h1 className="hero-title">设备故障后的异常恢复决策层</h1>
              <div className="hero-subtitle">
                异常进入系统后，ReOrch 先做影响分析，再生成候选恢复方案，并通过质量门和计划员确认控制生产风险。
              </div>
            </Col>
            <Col xs={24} lg={12}>
              <div className="metric-strip">
                <div className="metric-tile">
                  <div className="metric-label">当前异常</div>
                  <div className="metric-value">M-03</div>
                  <div className="metric-note">设备故障</div>
                </div>
                <div className="metric-tile">
                  <div className="metric-label">影响范围</div>
                  <div className="metric-value">5 / 15</div>
                  <div className="metric-note">工单 / 工序</div>
                </div>
                <div className="metric-tile">
                  <div className="metric-label">决策方式</div>
                  <div className="metric-value">Top-K</div>
                  <div className="metric-note">方案取舍</div>
                </div>
                <div className="metric-tile">
                  <div className="metric-label">执行边界</div>
                  <div className="metric-value">人审</div>
                  <div className="metric-note">不自动写回</div>
                </div>
              </div>
            </Col>
          </Row>
          <div style={{ marginTop: 14 }}>
            <Tag color="blue">异常识别</Tag>
            <Tag color="cyan">影响分析</Tag>
            <Tag color="geekblue">候选方案</Tag>
            <Tag color="gold">质量门</Tag>
            <Tag color="green">计划员确认</Tag>
          </div>
        </div>

        <div className="workbench-loop-strip">
          {recoveryLoop.map(([no, title, body]) => (
            <div className="workbench-loop-step" key={title}>
              <span>{no}</span>
              <strong>{title}</strong>
              <div>{body}</div>
            </div>
          ))}
        </div>

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
