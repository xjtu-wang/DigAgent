export function shouldSubmitComposer(event, options) {
  const { enterToSend, isComposing } = options;
  if (!enterToSend) {
    return false;
  }
  if (event.key !== "Enter") {
    return false;
  }
  if (event.shiftKey || event.nativeEvent?.shiftKey) {
    return false;
  }
  if (isComposing || event.nativeEvent?.isComposing) {
    return false;
  }
  return true;
}

const MENTION_NAME_RE = /[A-Za-z0-9._-]/;

function isMentionBoundary(value) {
  return !value || /\s|[([{"'`]/.test(value);
}

function normalizeAgentValue(agent) {
  if (!agent) {
    return null;
  }
  if (typeof agent === "string") {
    const name = agent.trim();
    return name ? { description: "", name } : null;
  }
  const name = String(agent.name || "").trim();
  if (!name) {
    return null;
  }
  return {
    description: String(agent.description || "").trim(),
    name,
  };
}

export function normalizeMentionAgents(agents = []) {
  const seen = new Set();
  return agents
    .map(normalizeAgentValue)
    .filter((agent) => {
      if (!agent || seen.has(agent.name)) {
        return false;
      }
      seen.add(agent.name);
      return true;
    });
}

function findMentionEnd(text, index) {
  let end = index;
  while (end < text.length && MENTION_NAME_RE.test(text[end])) {
    end += 1;
  }
  return end;
}

export function collectComposerMentions(text, agents = []) {
  const value = String(text || "");
  const knownAgents = new Set(normalizeMentionAgents(agents).map((agent) => agent.name));
  const seen = new Set();
  const mentions = [];
  for (let index = 0; index < value.length; index += 1) {
    if (value[index] !== "@" || !isMentionBoundary(value[index - 1])) {
      continue;
    }
    const end = findMentionEnd(value, index + 1);
    if (end <= index + 1) {
      continue;
    }
    const name = value.slice(index + 1, end);
    if (seen.has(name)) {
      index = end - 1;
      continue;
    }
    seen.add(name);
    mentions.push({
      configured: knownAgents.has(name),
      end,
      name,
      start: index,
    });
    index = end - 1;
  }
  return mentions;
}

export function resolveActiveMention(text, selectionStart = 0) {
  const value = String(text || "");
  const caret = Math.max(0, Math.min(selectionStart, value.length));
  let index = caret - 1;
  while (index >= 0 && MENTION_NAME_RE.test(value[index])) {
    index -= 1;
  }
  if (value[index] !== "@" || !isMentionBoundary(value[index - 1])) {
    return null;
  }
  const start = index;
  const end = findMentionEnd(value, start + 1);
  if (caret > end) {
    return null;
  }
  return {
    end,
    query: value.slice(start + 1, caret),
    start,
    text: value.slice(start, end),
  };
}

export function searchMentionCandidates(agents = [], query = "") {
  const normalizedAgents = normalizeMentionAgents(agents);
  const keyword = String(query || "").trim().toLowerCase();
  return normalizedAgents
    .filter((agent) => !keyword || agent.name.toLowerCase().includes(keyword))
    .sort((left, right) => {
      const leftStartsWith = left.name.toLowerCase().startsWith(keyword);
      const rightStartsWith = right.name.toLowerCase().startsWith(keyword);
      if (leftStartsWith !== rightStartsWith) {
        return leftStartsWith ? -1 : 1;
      }
      return left.name.localeCompare(right.name);
    });
}

export function applyMentionCompletion(text, mention, agentName) {
  const value = String(text || "");
  if (!mention?.text || !agentName) {
    return { selectionStart: value.length, value };
  }
  const prefix = value.slice(0, mention.start);
  const suffix = value.slice(mention.end);
  const trailing = suffix.startsWith(" ") || suffix.startsWith("\n") || !suffix ? "" : " ";
  const nextValue = `${prefix}@${agentName}${trailing}${suffix}`;
  return {
    selectionStart: `${prefix}@${agentName}${trailing}`.length,
    value: nextValue,
  };
}
