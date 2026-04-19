import test from "node:test";
import assert from "node:assert/strict";
import {
  applyMentionCompletion,
  collectComposerMentions,
  normalizeMentionAgents,
  resolveActiveMention,
  searchMentionCandidates,
  shouldSubmitComposer,
} from "./composer-utils.js";

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

test("normalizeMentionAgents keeps configured names unique", () => {
  assert.deepEqual(
    normalizeMentionAgents([
      { name: "sisyphus-default", description: "planner" },
      "report-writer",
      { name: "sisyphus-default", description: "duplicate" },
      null,
    ]),
    [
      { description: "planner", name: "sisyphus-default" },
      { description: "", name: "report-writer" },
    ],
  );
});

test("collectComposerMentions parses multiple mentions and marks configured entries", () => {
  assert.deepEqual(
    collectComposerMentions("@sisyphus-default 先看，再找 @report-writer，最后 @unknown", [
      { name: "sisyphus-default" },
      { name: "report-writer" },
    ]),
    [
      { configured: true, end: 17, name: "sisyphus-default", start: 0 },
      { configured: true, end: 38, name: "report-writer", start: 24 },
      { configured: false, end: 50, name: "unknown", start: 42 },
    ],
  );
});

test("resolveActiveMention finds the mention under the caret", () => {
  assert.deepEqual(
    resolveActiveMention("请 @sisy 看一下，再 @rep", 19),
    {
      end: 18,
      query: "rep",
      start: 14,
      text: "@rep",
    },
  );
});

test("searchMentionCandidates prefers prefix matches", () => {
  assert.deepEqual(
    searchMentionCandidates(
      [{ name: "report-writer" }, { name: "repo-searcher" }, { name: "sisyphus-default" }],
      "rep",
    ).map((item) => item.name),
    ["repo-searcher", "report-writer"],
  );
});

test("applyMentionCompletion replaces the active token and keeps plain text content", () => {
  assert.deepEqual(
    applyMentionCompletion("请 @rep 看下这个报告", { start: 2, end: 6, text: "@rep" }, "report-writer"),
    {
      selectionStart: 16,
      value: "请 @report-writer 看下这个报告",
    },
  );
});
