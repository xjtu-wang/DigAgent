import test from "node:test";
import assert from "node:assert/strict";
import {
  createHydrationController,
  createTailEventGate,
  resolveHydrateTarget,
  selectActiveTurn,
} from "./use-workspace-controller.js";

function createDeferred() {
  let resolve;
  let reject;
  const promise = new Promise((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, reject, resolve };
}

test("selectActiveTurn returns null when the session has no active turn", () => {
  const turns = [{ turn_id: "turn-1" }, { turn_id: "turn-2" }];
  assert.equal(selectActiveTurn(turns, null), null);
});

test("selectActiveTurn only returns the turn referenced by active_turn_id", () => {
  const turns = [{ turn_id: "turn-1" }, { turn_id: "turn-2" }];
  assert.deepEqual(selectActiveTurn(turns, "turn-2"), { turn_id: "turn-2" });
});

test("createTailEventGate only consumes events after the known tail, including reconnects", () => {
  const gate = createTailEventGate("evt-2");

  assert.equal(gate.shouldProcess({ event_id: "evt-1" }), false);
  assert.equal(gate.shouldProcess({ event_id: "evt-2" }), false);
  assert.equal(gate.shouldProcess({ event_id: "evt-3" }), true);

  gate.reset("evt-3");

  assert.equal(gate.shouldProcess({ event_id: "evt-1" }), false);
  assert.equal(gate.shouldProcess({ event_id: "evt-2" }), false);
  assert.equal(gate.shouldProcess({ event_id: "evt-3" }), false);
  assert.equal(gate.shouldProcess({ event_id: "evt-4" }), true);
});

test("resolveHydrateTarget keeps the intended session instead of falling back to stale history order", () => {
  const sessionList = [{ session_id: "sess-old" }, { session_id: "sess-new" }];

  assert.equal(resolveHydrateTarget(sessionList, { forceHydrate: true, intendedSessionId: "sess-new" }), "sess-new");
  assert.equal(resolveHydrateTarget([{ session_id: "sess-old" }], { forceHydrate: true, intendedSessionId: "sess-new" }), null);
});

test("createHydrationController aborts stale cross-session hydrates before they can apply", async () => {
  const inflight = [];
  const applied = [];
  const controller = createHydrationController(async (sessionId, request) => {
    const deferred = createDeferred();
    inflight.push({ deferred, request, sessionId });
    await deferred.promise;
    if (!request.isCurrent()) {
      return null;
    }
    applied.push(sessionId);
    return sessionId;
  });

  const oldHydrate = controller.request("sess-old");
  const newHydrate = controller.request("sess-new");

  assert.equal(inflight[0].request.signal.aborted, true);
  assert.equal(inflight.length, 2);

  inflight[0].deferred.resolve();
  inflight[1].deferred.resolve();

  assert.equal(await oldHydrate, null);
  assert.equal(await newHydrate, "sess-new");
  assert.deepEqual(applied, ["sess-new"]);
});

test("createHydrationController coalesces repeated hydrates for the same session into one rerun", async () => {
  const inflight = [];
  const runs = [];
  const controller = createHydrationController(async (sessionId, request) => {
    const deferred = createDeferred();
    inflight.push(deferred);
    runs.push({ epoch: request.epoch, sessionId });
    await deferred.promise;
    return request.isCurrent() ? `${sessionId}:${request.epoch}` : null;
  });

  const firstHydrate = controller.request("sess-1");
  const secondHydrate = controller.request("sess-1");
  const thirdHydrate = controller.request("sess-1");

  assert.equal(runs.length, 1);
  assert.equal(secondHydrate, thirdHydrate);

  inflight[0].resolve();
  assert.equal(await firstHydrate, "sess-1:1");
  assert.equal(runs.length, 2);

  inflight[1].resolve();
  assert.equal(await secondHydrate, "sess-1:2");
  assert.deepEqual(runs.map((item) => item.epoch), [1, 2]);
});
