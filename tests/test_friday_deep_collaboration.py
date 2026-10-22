from friday_deep import CollaborationLoop, MentorFeedback
from friday_deep.contracts import ExecutionResult, PlanEnvelope, PlanNode, Status


def test_collaboration_loop_revises_after_mentor_feedback():
    attempts = []
    revisions = []

    def planner(goal, feedback, previous):
        revisions.append(feedback.adjustment if feedback else "initial")
        return PlanEnvelope(
            goal=goal,
            plan_id=f"plan-{len(revisions)}",
            nodes=[PlanNode(node_id="open", title="Open app", description="Open the app")],
        )

    def executor(node):
        attempts.append(node.node_id)
        return ExecutionResult(
            task_id=node.node_id,
            agent_id="desktop",
            status=Status.SUCCEEDED,
            output="opened",
        )

    def mentor(node, result):
        if len(attempts) == 1:
            return MentorFeedback(node.node_id, passed=False, observation="Wrong window", adjustment="Refocus app", retry_node=True)
        return MentorFeedback(node.node_id, passed=True, observation="Expected window visible")

    run = CollaborationLoop(planner, executor, mentor).run("Open the app")

    assert run.status is Status.SUCCEEDED
    assert run.revisions == 1
    assert attempts == ["open", "open"]
    assert revisions == ["initial", "Refocus app"]


def test_collaboration_loop_stops_for_approval():
    def planner(goal, feedback, previous):
        return PlanEnvelope(goal=goal, plan_id="plan-approval", nodes=[PlanNode("send", "Send", "Send message")])

    def executor(node):
        return ExecutionResult("send", "messaging", Status.WAITING_APPROVAL, error="User approval required")

    run = CollaborationLoop(planner, executor, lambda node, result: MentorFeedback(node.node_id, True)).run("Send a message")

    assert run.status is Status.WAITING_APPROVAL
    assert run.state_history[-1].value == "waiting_approval"
