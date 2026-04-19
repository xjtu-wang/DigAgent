import React from "react";
import {
  ApprovalItem,
  MessageItem,
  NoticeItem,
  ParticipantHandoffItem,
  ParticipantMessageItem,
  RunningItem,
  ThoughtItem,
  ToolItem,
} from "./chat-stream-items";
import { TurnFlowThread } from "./chat-flow-blocks";

function TimelineItem(props) {
  const { item } = props;
  if (item.type === "local_user" || item.type === "user_message" || item.type === "assistant_message") {
    return <MessageItem {...props} />;
  }
  if (item.type === "turn_card") {
    return (
      <TurnFlowThread
        expanded={props.expandedItems.has(item.event_id)}
        item={item}
        onDownloadReport={props.onDownloadReport}
        onToggle={props.onToggleItem}
        onToggleReport={props.onToggleReport}
        reportOpenIds={props.reportOpenIds}
        reportsById={props.reportsById}
      />
    );
  }
  if (item.type === "assistant_process" || item.type === "assistant_thought") {
    return <ThoughtItem item={item} />;
  }
  if (item.type === "tool_action") {
    return <ToolItem item={item} />;
  }
  if (item.type === "tool_observation") {
    return <ToolItem item={item} observation />;
  }
  if (item.type === "participant_handoff") {
    return <ParticipantHandoffItem item={item} />;
  }
  if (item.type === "participant_message") {
    return <ParticipantMessageItem item={item} />;
  }
  if (item.type === "approval_required" || item.type === "approval_request") {
    return <ApprovalItem {...props} />;
  }
  return <NoticeItem item={item} />;
}

export function ChatTimeline(props) {
  const { pendingApprovals = [], running, timeline } = props;
  const timelineApprovalIds = new Set(timeline.map((item) => item?.data?.approval_id).filter(Boolean));
  const visiblePendingApprovals = pendingApprovals.filter((item) => !timelineApprovalIds.has(item.approval_id));
  return (
    <div className="mx-auto flex min-w-0 w-full max-w-3xl flex-col gap-5 overflow-x-hidden">
      {timeline.map((item) => <TimelineItem key={item.event_id} {...props} item={item} />)}
      {visiblePendingApprovals.map((approval) => (
        <ApprovalItem
          key={approval.approval_id}
          item={{ event_id: `pending-${approval.approval_id}`, type: "approval_request", data: approval }}
          onResolveApproval={props.onResolveApproval}
          resolvedApprovalIds={props.resolvedApprovalIds}
          resolvingApprovalIds={props.resolvingApprovalIds}
          supersededApprovalIds={props.supersededApprovalIds}
          supersededApprovals={props.supersededApprovals}
        />
      ))}
      {running ? <RunningItem /> : null}
    </div>
  );
}
