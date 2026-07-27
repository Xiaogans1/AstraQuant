import { render, screen } from "@testing-library/react";

import { App } from "./App";

it("renders the desktop bootstrap", () => {
  render(<App />);
  expect(screen.getByText("AstraQuant desktop bootstrap")).toBeVisible();
});
