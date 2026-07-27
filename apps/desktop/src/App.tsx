import { useState } from "react";

import { EmptyState } from "./components/EmptyState";
import { Panel } from "./components/Panel";
import {
  Sidebar,
} from "./components/Sidebar";
import type { WorkspaceView } from "./components/Sidebar";
import { StatusRail } from "./components/StatusRail";

const viewCopy: Record<
  WorkspaceView,
  { index: string; title: string; summary: string }
> = {
  overview: {
    index: "WORKSPACE / 01",
    title: "总览",
    summary: "从本机服务、任务和活动记录开始，逐步搭建中国市场量化研究与执行闭环。",
  },
  tasks: {
    index: "WORKSPACE / 02",
    title: "任务中心",
    summary: "查看长任务的状态、进度和恢复结果。真实交互将在下一阶段接入。",
  },
  activity: {
    index: "WORKSPACE / 03",
    title: "本地活动",
    summary: "以关联 ID 串联服务与任务事件，不暴露原始环境信息或凭据。",
  },
  settings: {
    index: "WORKSPACE / 04",
    title: "设置",
    summary: "主题、动态效果与侧栏偏好只保存在本机状态库中。",
  },
};

export function App() {
  const [currentView, setCurrentView] = useState<WorkspaceView>("overview");
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const copy = viewCopy[currentView];

  return (
    <div className="app">
      <StatusRail status="starting" protocolVersion={1} />
      <div
        className="workspace"
        data-sidebar-collapsed={sidebarCollapsed}
      >
        <Sidebar
          currentView={currentView}
          collapsed={sidebarCollapsed}
          onNavigate={setCurrentView}
          onToggle={() => setSidebarCollapsed((value) => !value)}
        />
        <main className="workspace-main">
          <header className="page-heading">
            <div>
              <p className="page-heading__index">{copy.index}</p>
              <h1>{copy.title}</h1>
            </div>
            <p className="page-heading__summary">{copy.summary}</p>
          </header>
          <div className="workspace-content">
            {currentView === "overview" ? (
              <OverviewShell />
            ) : (
              <Panel className="placeholder-view">
                <EmptyState
                  title={`${copy.title}正在接线`}
                  description="工作区结构已经就位，真实本地数据与操作会在下一批次接入。"
                />
              </Panel>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}

function OverviewShell() {
  return (
    <>
      <div className="metric-strip" aria-label="平台边界">
        <Metric label="服务通道" value="准备接入" accent />
        <Metric label="运行模式" value="LOCAL" />
        <Metric label="数据边界" value=".astraquant" />
        <Metric label="当前阶段" value="PHASE 01" />
      </div>
      <div className="preview-grid">
        <Panel title="本地闭环" eyebrow="SYSTEM MAP">
          <div className="phase-map">
            <PhaseRow code="01" name="桌面壳层" note="Tauri / Windows" />
            <PhaseRow code="02" name="控制服务" note="FastAPI / Loopback" />
            <PhaseRow code="03" name="任务执行" note="Worker / SQLite" />
            <PhaseRow code="04" name="市场能力" note="A 股与国内期货 / Later" />
          </div>
        </Panel>
        <Panel title="下一接入点" eyebrow="UP NEXT">
          <EmptyState
            title="等待真实任务数据"
            description="下一批次会接入运行状态、示例任务进度和最近活动，不使用模拟交易数据。"
          />
        </Panel>
      </div>
    </>
  );
}

function Metric({
  label,
  value,
  accent = false,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div className="metric">
      <span className="metric__label">{label}</span>
      <strong
        className={accent ? "metric__value metric__value--accent" : "metric__value"}
      >
        {value}
      </strong>
    </div>
  );
}

function PhaseRow({
  code,
  name,
  note,
}: {
  code: string;
  name: string;
  note: string;
}) {
  return (
    <div className="phase-map__row">
      <span className="phase-map__code">{code}</span>
      <span className="phase-map__name">{name}</span>
      <span className="phase-map__note">{note}</span>
    </div>
  );
}
