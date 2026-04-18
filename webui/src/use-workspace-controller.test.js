import test from "node:test";
import assert from "node:assert/strict";
import { selectActiveTurn } from "./use-workspace-controller.js";

test("selectActiveTurn returns null when the session has no active turn", () => {
  const turns = [{ turn_id: "turn-1" }, { turn_id: "turn-2" }];
  assert.equal(selectActiveTurn(turns, null), null);
});

test("selectActiveTurn only returns the turn referenced by active_turn_id", () => {
  const turns = [{ turn_id: "turn-1" }, { turn_id: "turn-2" }];
  assert.deepEqual(selectActiveTurn(turns, "turn-2"), { turn_id: "turn-2" });
});
