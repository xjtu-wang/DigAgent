import React from "react";
import {
  TimelineApprovalBlock,
  TimelineClusterBlock,
  TimelineMessageBlock,
  TimelineReportBlock,
  TimelineRunningBlock,
} from "./chat-timeline-blocks";

export function ChatTimeline(props) {
  const { pendingApprovals = [], running, timeline } = props;

  const timelineApprovalIds = new Set();
  for (const group of timeline) {
    for (const item of group.items) {
      if (item?.data?.approval_id) {
        timelineApprovalIds.add(item.data.approval_id);
      }
    }
  }

  const visiblePendingApprovals = pendingApprovals.filter((item) => !timelineApprovalIds.has(item.approval_id));
  return (
    <div className="mx-auto flex min-w-0 w-full max-w-[52rem] flex-col gap-5 overflow-x-hidden">
      {timeline.map((group) => <RenderedGroup key={group.id} {...props} group={group} />)}
      {visiblePendingApprovals.map((approval) => (
        <TimelineApprovalBlock
          key={approval.approval_id}
          item={{ event_id: `pending-${approval.approval_id}`, type: "approval_request", data: approval }}
          onResolveApproval={props.onResolveApproval}
          resolvedApprovalIds={props.resolvedApprovalIds}
          resolvingApprovalIds={props.resolvingApprovalIds}
          supersededApprovalIds={props.supersededApprovalIds}
          supersededApprovals={props.supersededApprovals}
        />
      ))}
      {running ? <TimelineRunningBlock /> : null}
    </div>
  );
}

function RenderedGroup(props) {
  const { group } = props;
  if (group.layout === "message" || group.layout === "agent-message") {
    return <TimelineMessageBlock {...props} />;
  }
  if (group.layout === "approval") {
    return <TimelineApprovalBlock {...props} />;
  }
  if (group.layout === "report") {
    return <TimelineReportBlock {...props} />;
  }
  return <TimelineClusterBlock {...props} />;
}
