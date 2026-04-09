from __future__ import annotations

from pathlib import Path

from digagent.models import Scope, TaskNodeKind


def test_vendored_ctf_skills_are_loaded_from_data_dir(manager):
    skills = manager.skills.load_all()
    skills_root = manager.settings.data_dir / "skills"

    assert len(skills) == 41
    assert "ctf-sandbox-orchestrator" in skills
    assert "competition-crypto-mobile" in skills

    orchestrator = skills["ctf-sandbox-orchestrator"]
    crypto_child = skills["competition-crypto-mobile"]

    assert orchestrator.allow_implicit_invocation is True
    assert orchestrator.downstream_only is False
    assert crypto_child.allow_implicit_invocation is False
    assert crypto_child.downstream_only is True
    assert orchestrator.references
    assert orchestrator.agent_config_path
    assert Path(orchestrator.path).is_file()
    assert Path(orchestrator.path).is_relative_to(skills_root)
    assert Path(crypto_child.path).is_relative_to(skills_root)
    assert Path(orchestrator.agent_config_path).is_relative_to(skills_root)


def test_ctf_test_graph_uses_vendored_skill_chain(manager):
    graph = manager.agent.build_test_task_graph(
        run_id="run_ctf",
        task="一道密码学 CTF 题：一只小羊翻过了 2 个栅栏 `fa{fe13f590lg6d46d0d0}`",
        scope=Scope(),
    )

    skill_names = [node.metadata.get("skill_name") for node in graph.nodes if node.kind == TaskNodeKind.SKILL]
    tool_names = [node.metadata.get("tool_name") for node in graph.nodes if node.kind == TaskNodeKind.TOOL]
    subagent_nodes = [node for node in graph.nodes if node.kind == TaskNodeKind.SUBAGENT]

    assert skill_names[0] == "ctf-sandbox-orchestrator"
    assert "competition-crypto-mobile" in skill_names
    assert "ctf-crypto-basics" not in skill_names
    assert "crypto_helper" not in tool_names
    assert subagent_nodes
