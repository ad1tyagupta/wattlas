import { describe, expect, it } from "vitest";

import { connectorLabel, formatSnapshotTime } from "@/lib/format";

describe("formatSnapshotTime", () => {
  it("uses a deterministic timezone for server and browser rendering", () => {
    expect(formatSnapshotTime("2026-06-27T11:55:27Z")).toBe("27 Jun, 11:55 UTC");
  });
});

describe("connectorLabel", () => {
  it("names the community infrastructure feed clearly", () => {
    expect(connectorLabel("osm_infrastructure")).toBe("OpenStreetMap infrastructure");
  });
});
