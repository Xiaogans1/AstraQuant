export type WorkspaceView =
  | "overview"
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
  id: WorkspaceView | "research" | "trading";
  label: string;
  glyph: string;
  disabled?: boolean;
}

const navigation: NavigationItem[] = [
  { id: "overview", label: "总览", glyph: "OV" },
  { id: "data", label: "数据中心", glyph: "DT" },
  { id: "tasks", label: "任务", glyph: "TK" },
  { id: "activity", label: "本地活动", glyph: "AC" },
  { id: "settings", label: "设置", glyph: "ST" },
  { id: "research", label: "研究中心", glyph: "RS", disabled: true },
  { id: "trading", label: "交易中心", glyph: "TR", disabled: true },
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
        {navigation.map((item, index) => (
          <div
            className={
              index === 5 ? "sidebar__item sidebar__item--future" : "sidebar__item"
            }
            key={item.id}
          >
            <button
              type="button"
              aria-current={item.id === currentView ? "page" : undefined}
              aria-label={item.label}
              disabled={item.disabled}
              title={collapsed ? item.label : undefined}
              onClick={() => {
                if (!item.disabled) {
                  onNavigate(item.id as WorkspaceView);
                }
              }}
            >
              <span className="sidebar__glyph" aria-hidden="true">
                {item.glyph}
              </span>
              <span className="sidebar__label">{item.label}</span>
              {item.disabled ? (
                <span className="sidebar__later">Later</span>
              ) : null}
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
