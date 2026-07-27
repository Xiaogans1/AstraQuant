import { render, screen } from "@testing-library/react";

import { App } from "./App";

it("renders the responsive workspace shell", () => {
  render(<App />);
  expect(
    screen.getByRole("banner", { name: "AstraQuant 状态栏" }),
  ).toHaveTextContent("AstraQuant");
  expect(
    screen.getByRole("navigation", { name: "工作区导航" }),
  ).toBeVisible();
  expect(screen.getByRole("button", { name: "总览" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});
