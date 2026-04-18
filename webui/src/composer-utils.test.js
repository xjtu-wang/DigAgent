import test from "node:test";
import assert from "node:assert/strict";
import { shouldSubmitComposer } from "./composer-utils.js";

test("Enter submits when enabled and not composing", () => {
  assert.equal(
    shouldSubmitComposer(
      { key: "Enter", shiftKey: false, nativeEvent: { isComposing: false, shiftKey: false } },
      { enterToSend: true, isComposing: false },
    ),
    true,
  );
});

test("Shift+Enter never submits", () => {
  assert.equal(
    shouldSubmitComposer(
      { key: "Enter", shiftKey: true, nativeEvent: { isComposing: false, shiftKey: true } },
      { enterToSend: true, isComposing: false },
    ),
    false,
  );
});

test("IME composition blocks submit", () => {
  assert.equal(
    shouldSubmitComposer(
      { key: "Enter", shiftKey: false, nativeEvent: { isComposing: true, shiftKey: false } },
      { enterToSend: true, isComposing: true },
    ),
    false,
  );
});
