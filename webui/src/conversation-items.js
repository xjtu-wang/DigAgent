import {
  PRIMARY_CONVERSATION_ITEM_TYPES,
  KEY_SYSTEM_CONVERSATION_ITEM_TYPES,
  asArray,
  compareConversationItems,
  normalizeConversationOptions,
  normalizeSpeaker,
  uniqueList,
} from "./conversation-item-utils.js";
import { buildEventItems, buildTurnMetadata } from "./conversation-event-items.js";

export {
  KEY_SYSTEM_CONVERSATION_ITEM_TYPES,
  PRIMARY_CONVERSATION_ITEM_TYPES,
};

function buildMessageItem(message) {
  const addressedParticipants = uniqueList([
    ...asArray(message.addressed_participants),
    ...asArray(message.mentions),
  ]);
  return {
    event_id: `msg-${message.message_id}`,
    session_id: message.session_id,
    turn_id: message.turn_id || null,
    type: message.role === "user" ? "user_message" : "assistant_message",
    created_at: message.created_at,
    data: {
      message: message.content,
      markdown: message.content,
      message_id: message.message_id,
      speaker_profile: normalizeSpeaker(message.speaker_profile, message.role === "assistant" ? "assistant" : "user"),
      addressed_participants: addressedParticipants,
      evidence_refs: message.evidence_refs || [],
      artifact_refs: message.artifact_refs || [],
    },
  };
}

export function buildConversationItems(messages, events, options) {
  const normalizedOptions = normalizeConversationOptions(options);
  const turnMetadata = buildTurnMetadata(messages, events, normalizedOptions);
  const messageItems = asArray(messages).map(buildMessageItem);
  const eventItems = buildEventItems(events, turnMetadata, normalizedOptions);
  return [...messageItems, ...eventItems].sort(compareConversationItems);
}
