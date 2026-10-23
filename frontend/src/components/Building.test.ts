import { describe, expect, it } from "vitest";
import { interpolatedPosition } from "./Building";
import type { Elevator } from "../types";
const e: Elevator = {
  id: "E1",
  position_floor: 2.5,
  direction: "UP",
  load: 1,
  capacity: 6,
  target_floor: 5,
  phase: "MOVING",
  purpose: "SERVICE",
  distance_floors: 1,
  segment: {
    from_floor: 2,
    to_floor: 3,
    start_us: 1000000,
    end_us: 3000000,
    purpose: "SERVICE",
  },
};
describe("server segment interpolation", () => {
  it("preserves fractional positions and clamps both boundaries", () => {
    expect(interpolatedPosition(e, 2)).toBe(2.5);
    expect(interpolatedPosition(e, 0)).toBe(2);
    expect(interpolatedPosition(e, 100)).toBe(3);
  });
  it("does not invent movement without an authoritative segment", () => {
    expect(interpolatedPosition({ ...e, segment: null }, 100)).toBe(2.5);
  });
});
