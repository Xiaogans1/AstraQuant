import {
  useEffect,
  useState,
} from "react";
import type { FormEvent } from "react";

import type { Settings } from "../api/contracts";
import { Panel } from "../components/Panel";
import {
  applyBackgroundEffect,
  applyReducedMotion,
  applyTheme,
} from "../theme/theme";

export function SettingsPage({
  settings,
  saving,
  onSave,
}: {
  settings: Settings;
  saving: boolean;
  onSave: (settings: Settings) => Promise<Settings>;
}) {
  const [draft, setDraft] = useState(settings);
  const [saveError, setSaveError] = useState(false);

  useEffect(() => {
    setDraft(settings);
  }, [settings]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSaveError(false);
    try {
      const saved = await onSave(draft);
      applyTheme(saved.theme);
      applyReducedMotion(saved.reduced_motion);
      applyBackgroundEffect(saved.background_effect);
    } catch {
      setSaveError(true);
    }
  }

  return (
    <Panel title="界面偏好" eyebrow="LOCAL SETTINGS">
      <form className="settings-form" onSubmit={submit}>
        <label>
          <span>主题</span>
          <select
            value={draft.theme}
            onChange={(event) =>
              setDraft({ ...draft, theme: event.target.value as Settings["theme"] })
            }
          >
            <option value="astra-minimal">Astra Minimal</option>
            <option value="astra-light">Astra Light</option>
          </select>
        </label>
        <label>
          <span>背景效果</span>
          <select
            value={draft.background_effect}
            onChange={(event) =>
              setDraft({
                ...draft,
                background_effect: event.target
                  .value as Settings["background_effect"],
              })
            }
          >
            <option value="none">无</option>
            <option value="nebula">星云</option>
            <option value="grid">网格</option>
          </select>
        </label>
        <label className="settings-toggle">
          <span>
            <strong>减少动画</strong>
            <small>缩短过渡时间，不隐藏任务进度。</small>
          </span>
          <input
            aria-label="减少动画"
            type="checkbox"
            checked={draft.reduced_motion}
            onChange={(event) =>
              setDraft({ ...draft, reduced_motion: event.target.checked })
            }
          />
        </label>
        <label className="settings-toggle">
          <span>
            <strong>默认收起侧栏</strong>
            <small>为数据和图表保留更多横向空间。</small>
          </span>
          <input
            aria-label="默认收起侧栏"
            type="checkbox"
            checked={draft.sidebar_collapsed}
            onChange={(event) =>
              setDraft({ ...draft, sidebar_collapsed: event.target.checked })
            }
          />
        </label>
        {saveError ? <p className="form-error">设置保存失败</p> : null}
        <button className="button button--primary" type="submit" disabled={saving}>
          {saving ? "正在保存…" : "保存设置"}
        </button>
      </form>
    </Panel>
  );
}
