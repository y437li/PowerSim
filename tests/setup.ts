import { afterEach } from "vitest";
import { expect } from "vitest";
import * as matchers from "@testing-library/jest-dom/matchers";
import { cleanup } from "@testing-library/react";

expect.extend(matchers);

// Ensure the DOM is cleaned up between tests (required with globals: false)
afterEach(() => {
  cleanup();
});
