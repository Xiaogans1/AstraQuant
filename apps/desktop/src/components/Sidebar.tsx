export type WorkspaceView =
  | "overview"
  | "paper"
  | "strategy"
  | "data"
  | "tasks"
  | "activity"
  | "settings";

interface SidebarProps {
  currentView: WorkspaceView;
  collapsed: boolean;
  onNavigate: (view: WorkspaceView) => void;
  onToggle: () => void;
}

interface NavigationItem {
  id: WorkspaceView;
  label: string;
  glyph: string;
  groupStart?: boolean;
}

const navigation: NavigationItem[] = [
  { id: "overview", label: "市场首页", glyph: "MK" },
  { id: "paper", label: "Paper 模拟", glyph: "PP", groupStart: true },
  { id: "strategy", label: "策略实验室", glyph: "ST" },
  { id: "data", label: "数据与连接", glyph: "DT", groupStart: true },
  { id: "tasks", label: "任务", glyph: "TK" },
  { id: "activity", label: "本地活动", glyph: "AC" },
  { id: "settings", label: "设置", glyph: "SE" },
];

export function Sidebar({
  currentView,
  collapsed,
  onNavigate,
  onToggle,
}: SidebarProps) {
  return (
    <aside className="sidebar" data-collapsed={collapsed}>
      <nav className="sidebar__nav" aria-label="工作区导航">
        {navigation.map((item) => (
          <div
            className={item.groupStart ? "sidebar__item sidebar__item--future" : "sidebar__item"}
            key={item.id}
          >
            <button
              type="button"
              aria-current={item.id === currentView ? "page" : undefined}
              aria-label={item.label}
              title={collapsed ? item.label : undefined}
              onClick={() => onNavigate(item.id)}
            >
              <span className="sidebar__glyph" aria-hidden="true">
                {item.glyph}
              </span>
              <span className="sidebar__label">{item.label}</span>
            </button>
          </div>
        ))}
      </nav>
      <button
        className="sidebar__toggle"
        type="button"
        aria-label={collapsed ? "展开侧栏" : "收起侧栏"}
        onClick={onToggle}
      >
        <span aria-hidden="true">{collapsed ? "›" : "‹"}</span>
        <span className="sidebar__label">收起</span>
      </button>
    </aside>
  );
}
