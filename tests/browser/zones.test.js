import { describe, test } from "node:test";
import assert from "node:assert/strict";
import { resolve } from "node:path";

const zonesPath = resolve("app-v2/src/screens/zones.js");

describe("browser: zones screen", () => {
  test("renderZones uses display.x/y (data-x, left:%)", async () => {
    const { renderZones } = await import(zonesPath);
    assert.equal(typeof renderZones, "function", "renderZones must be exported");
    const html = renderZones([{ zone_id: "paiporta-ground-floor", name: "Paiporta", display: { x: 18, y: 62 } }]);
    if (!html.includes('data-x="18"') || !html.includes("left:18%")) {
      throw new Error("zones not using display.x/y (expected data-x=\"18\" and left:18%)");
    }
    // also check data-y and top
    assert.ok(html.includes('data-y="62"'), "should include data-y=\"62\"");
    assert.ok(html.includes("top:62%") || html.includes("top: 62%"), "should include top:62%");
    assert.ok(html.includes("paiporta-ground-floor"), "should include zone_id");
  });

  test("renderZones renders SeverityMeter placeholder and col-head parity", async () => {
    const { renderZones } = await import(zonesPath);
    const html = renderZones([
      { zone_id: "paiporta-ground-floor", name: "Paiporta", display: { x: 18, y: 62 }, kind: "residential" },
      { zone_id: "catarroja-health-centre", name: "Catarroja", display: { x: 45, y: 40 }, kind: "infrastructure" },
    ]);
    // parity with Zonas.body.html: col-head, count, SeverityMeter placeholder
    assert.ok(html.includes("col-head") || html.includes("col-title"), "should include col-head structure from Zonas.body.html");
    assert.ok(html.includes("SeverityMeter") || html.includes("severity") || html.includes("data-testid=\"zone-item\""), "should include SeverityMeter placeholder or zone row");
  });

  test("renderZones handles empty list", async () => {
    const { renderZones } = await import(zonesPath);
    const html = renderZones([]);
    assert.ok(html.includes("Sin zonas"), "empty should show Sin zonas");
  });
});
