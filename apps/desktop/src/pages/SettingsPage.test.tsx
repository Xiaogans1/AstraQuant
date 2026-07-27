import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Settings } from "../api/contracts";
import { applyTheme } from "../theme/theme";
import { SettingsPage } from "./SettingsPage";

const initialSettings: Settings = {
  theme: "astra-minimal",
  reduced_motion: false,
  sidebar_collapsed: false,
  background_effect: "nebula",
};

it("persists all supported preferences before applying them", async () => {
  const savedSettings: Settings = {
    theme: "astra-light",
    reduced_motion: true,
    sidebar_collapsed: true,
    background_effect: "grid",
  };
  const save = vi.fn().mockResolvedValue(savedSettings);
  applyTheme(initialSettings.theme);
  render(
    <SettingsPage
      settings={initialSettings}
      saving={false}
      onSave={save}
    />,
  );

  await userEvent.selectOptions(screen.getByLabelText("主题"), "astra-light");
  await userEvent.click(screen.getByLabelText("减少动画"));
  await userEvent.click(screen.getByLabelText("默认收起侧栏"));
  await userEvent.selectOptions(screen.getByLabelText("背景效果"), "grid");
  await userEvent.click(screen.getByRole("button", { name: "保存设置" }));

  expect(save).toHaveBeenCalledWith(savedSettings);
  expect(document.documentElement.dataset.theme).toBe("astra-light");
});

it("keeps the applied theme when persistence fails", async () => {
  const save = vi.fn().mockRejectedValue(new Error("offline"));
  applyTheme(initialSettings.theme);
  render(
    <SettingsPage
      settings={initialSettings}
      saving={false}
      onSave={save}
    />,
  );

  await userEvent.selectOptions(screen.getByLabelText("主题"), "astra-light");
  await userEvent.click(screen.getByRole("button", { name: "保存设置" }));

  expect(await screen.findByText("设置保存失败")).toBeVisible();
  expect(document.documentElement.dataset.theme).toBe("astra-minimal");
});
